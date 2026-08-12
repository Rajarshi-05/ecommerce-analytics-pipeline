"""Export the mart, analytics and ML tables to Parquet.

Why this exists: the brief calls for a *live* dashboard link, and Streamlit
Community Cloud cannot reach a Postgres running in Docker on a laptop. Rather
than exposing the warehouse to the internet, the pipeline publishes a
read-only snapshot the deployed app reads directly.

The dashboard picks its backend at runtime - Postgres when DATABASE_URL is set
(local development), the Parquet snapshot otherwise (deployed). Both paths
return identical DataFrames, so there is one set of dashboard code and no risk
of the two showing different numbers.

What gets exported is defined once in `dashboard/lib/queries.py` and shared
with the dashboard's own data layer.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import text

from dashboard.lib.queries import DATASETS
from ml.common import get_engine

log = logging.getLogger(__name__)

DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "dashboard" / "data"


def _relation_exists(engine, relation: str) -> bool:
    schema, _, table = relation.partition(".")
    with engine.connect() as conn:
        return conn.execute(
            text("select to_regclass(:qualified)"), {"qualified": f"{schema}.{table}"}
        ).scalar() is not None


def export(output_dir: Path = DEFAULT_OUTPUT, strict: bool = False) -> dict[str, int]:
    engine = get_engine()
    output_dir.mkdir(parents=True, exist_ok=True)

    written: dict[str, int] = {}
    skipped: list[str] = []

    for dataset in DATASETS:
        if not _relation_exists(engine, dataset.source_relation):
            message = f"{dataset.source_relation} does not exist - skipping {dataset.name}"
            # A missing *required* relation means dbt has not run; that is a
            # broken pipeline, not a partial snapshot. ML tables are optional
            # so the snapshot still works before the models have been trained.
            if strict and dataset.required:
                raise RuntimeError(message)
            log.warning("%s", message)
            skipped.append(dataset.source_relation)
            continue

        with engine.connect() as conn:
            frame = pd.read_sql(text(dataset.sql()), conn)
        frame.to_parquet(output_dir / f"{dataset.name}.parquet", index=False)
        written[dataset.name] = len(frame)
        log.info("%-42s %8d rows -> %s.parquet",
                 dataset.source_relation, len(frame), dataset.name)

    manifest = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "tables": written,
        "skipped": skipped,
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    log.info("Snapshot written to %s (%d tables, %d skipped).",
             output_dir, len(written), len(skipped))
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--strict", action="store_true",
                        help="Fail if a required relation is missing.")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)-8s %(message)s", datefmt="%H:%M:%S")
    export(output_dir=args.output, strict=args.strict)
    return 0


if __name__ == "__main__":
    sys.exit(main())
