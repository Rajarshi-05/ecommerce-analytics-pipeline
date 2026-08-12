"""Command-line entry point for the ingestion layer.

    python -m ingestion.cli download            # fetch from Kaggle
    python -m ingestion.cli seed --synthetic    # generate stand-in CSVs
    python -m ingestion.cli load                # CSVs -> raw schema
    python -m ingestion.cli load --table orders
    python -m ingestion.cli load --reset        # truncate first (switching datasets)
    python -m ingestion.cli validate            # raw-zone checks
    python -m ingestion.cli info                # what is currently loaded
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from sqlalchemy import text

from ingestion import provenance
from ingestion.config import get_settings
from ingestion.db import get_engine
from ingestion.download import MissingCredentialsError, download_dataset
from ingestion.load import load_all, reset_raw_zone
from ingestion.schemas import TABLE_SPECS
from ingestion.synthetic import generate, write_csvs
from ingestion.validate import ValidationError, assert_valid, run_checks

log = logging.getLogger(__name__)


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)-22s %(message)s",
        datefmt="%H:%M:%S",
    )


def cmd_download(args: argparse.Namespace) -> int:
    try:
        destination = download_dataset(force=args.force)
    except MissingCredentialsError as exc:
        log.error("%s", exc)
        return 2
    log.info("Source files available in %s", destination)
    return 0


def cmd_seed(args: argparse.Namespace) -> int:
    if not args.synthetic:
        log.error("Pass --synthetic to confirm you want generated (not real) data.")
        return 2
    destination = write_csvs(
        generate(n_orders=args.orders, seed=args.seed),
        get_settings().raw_dir,
        seed=args.seed,
    )
    log.warning(
        "Wrote SYNTHETIC data to %s. Figures derived from it are not real Olist "
        "results - re-run `download` before reporting findings.", destination,
    )
    return 0


def cmd_load(args: argparse.Namespace) -> int:
    if args.reset:
        reset_raw_zone()
    results = load_all(run_id=args.run_id, only=args.table or None)
    print(json.dumps(results, indent=2))
    return 0


def cmd_reset(_: argparse.Namespace) -> int:
    tables = reset_raw_zone()
    print(f"Truncated {len(tables)} raw table(s). Re-run `load` to repopulate.")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    try:
        assert_valid(strict=args.strict)
    except ValidationError as exc:
        log.error("%s", exc)
        return 1
    return 0


def cmd_info(_: argparse.Namespace) -> int:
    settings = get_settings()
    origin = provenance.read(settings.raw_dir)
    print(f"Warehouse : {settings.database_url.rsplit('@', 1)[-1]}")
    print(f"Raw dir   : {settings.raw_dir}")
    print(f"Source    : {origin.source} ({origin.dataset})")
    if not origin.is_real_data:
        print("            ^ NOT the real Olist dataset - figures are illustrative only.")
    print(f"Sample    : {settings.sample_mode} ({settings.sample_rows} rows/table)\n")

    print(f"{'table':<30}{'rows':>12}  {'strategy':<14}{'last loaded':<22}")
    print("-" * 80)
    engine = get_engine()
    with engine.connect() as conn:
        for spec in TABLE_SPECS:
            rows = conn.execute(
                text("SELECT count(*) FROM information_schema.tables "
                     "WHERE table_schema = :s AND table_name = :t"),
                {"s": settings.raw_schema, "t": spec.name},
            ).scalar_one()
            if not rows:
                print(f"{spec.name:<30}{'-':>12}  {spec.strategy:<14}{'not loaded':<22}")
                continue
            count = conn.execute(
                text(f'SELECT count(*) FROM "{settings.raw_schema}"."{spec.name}"')
            ).scalar_one()
            loaded = conn.execute(
                text("SELECT max(finished_at) FROM meta.ingestion_audit WHERE table_name = :t"),
                {"t": spec.name},
            ).scalar()
            stamp = loaded.strftime("%Y-%m-%d %H:%M:%S") if loaded else "unknown"
            print(f"{spec.name:<30}{count:>12,}  {spec.strategy:<14}{stamp:<22}")

    print()
    failures = [r for r in run_checks() if not r.passed]
    print(f"Validation: {'all checks pass' if not failures else f'{len(failures)} FAILING'}")
    for failure in failures:
        print(f"  {failure}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ingestion", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p_download = sub.add_parser("download", help="Fetch the Olist dataset from Kaggle.")
    p_download.add_argument("--force", action="store_true")
    p_download.set_defaults(func=cmd_download)

    p_seed = sub.add_parser("seed", help="Generate schema-compatible synthetic CSVs.")
    p_seed.add_argument("--synthetic", action="store_true", required=False)
    p_seed.add_argument("--orders", type=int, default=20_000)
    p_seed.add_argument("--seed", type=int, default=42)
    p_seed.set_defaults(func=cmd_seed)

    p_load = sub.add_parser("load", help="Load CSVs into the raw schema.")
    p_load.add_argument("--table", action="append", help="Load only this table (repeatable).")
    p_load.add_argument("--run-id", default=None, help="Airflow run id, recorded in the audit log.")
    p_load.add_argument("--reset", action="store_true",
                        help="Truncate raw first. Needed when switching datasets.")
    p_load.set_defaults(func=cmd_load)

    sub.add_parser(
        "reset", help="Truncate the raw schema (use when switching datasets).",
    ).set_defaults(func=cmd_reset)

    p_validate = sub.add_parser("validate", help="Run raw-zone sanity checks.")
    strictness = p_validate.add_mutually_exclusive_group()
    strictness.add_argument("--strict", dest="strict", action="store_true", default=None,
                            help="Enforce published row counts.")
    strictness.add_argument("--no-strict", dest="strict", action="store_false")
    p_validate.set_defaults(func=cmd_validate)

    sub.add_parser("info", help="Show what is loaded.").set_defaults(func=cmd_info)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _configure_logging(args.verbose)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
