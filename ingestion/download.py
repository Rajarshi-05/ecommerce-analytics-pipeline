"""Fetch the Olist dataset from Kaggle into `data/raw/`.

Credentials come from KAGGLE_USERNAME/KAGGLE_KEY or a kaggle.json. The download
is skipped when every expected CSV is already present, so the Airflow task is
safe to re-run.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys
from pathlib import Path

from ingestion import provenance
from ingestion.config import get_settings
from ingestion.schemas import TABLE_SPECS

log = logging.getLogger(__name__)

CREDENTIAL_HELP = (
    "Kaggle credentials not found.\n"
    "  1. Go to https://www.kaggle.com/settings -> API -> 'Create New Token'\n"
    "  2. Either set KAGGLE_USERNAME and KAGGLE_KEY in your .env,\n"
    "     or place the downloaded kaggle.json at ~/.kaggle/kaggle.json\n"
    "Alternatively run `python -m ingestion.cli seed --synthetic` to generate a\n"
    "schema-compatible sample dataset and exercise the pipeline without Kaggle."
)


class MissingCredentialsError(RuntimeError):
    pass


def _hydrate_credentials_from_file() -> None:
    """Promote a kaggle.json into env vars so the SDK finds it anywhere."""
    if os.getenv("KAGGLE_USERNAME") and os.getenv("KAGGLE_KEY"):
        return

    candidates = [
        Path.home() / ".kaggle" / "kaggle.json",
        Path(os.getenv("KAGGLE_CONFIG_DIR", "/dev/null")) / "kaggle.json",
        Path.cwd() / "kaggle.json",
    ]
    for path in candidates:
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if payload.get("username") and payload.get("key"):
            os.environ["KAGGLE_USERNAME"] = payload["username"]
            os.environ["KAGGLE_KEY"] = payload["key"]
            log.info("Loaded Kaggle credentials from %s", path)
            return


def missing_files(raw_dir: Path) -> list[str]:
    return [s.source_file for s in TABLE_SPECS if not (raw_dir / s.source_file).is_file()]


def download_dataset(force: bool = False) -> Path:
    settings = get_settings()
    raw_dir = settings.raw_dir
    raw_dir.mkdir(parents=True, exist_ok=True)

    absent = missing_files(raw_dir)
    if not absent and not force:
        log.info("All %d source files already present in %s - skipping download.",
                 len(TABLE_SPECS), raw_dir)
        return raw_dir

    log.info("Missing %d source file(s): %s", len(absent), ", ".join(absent))
    _hydrate_credentials_from_file()
    if not (os.getenv("KAGGLE_USERNAME") and os.getenv("KAGGLE_KEY")):
        raise MissingCredentialsError(CREDENTIAL_HELP)

    # Imported lazily: the kaggle package authenticates at import time and
    # raises if credentials are absent, which would break `--help` and tests.
    from kaggle.api.kaggle_api_extended import KaggleApi

    api = KaggleApi()
    api.authenticate()
    log.info("Downloading %s -> %s", settings.kaggle_dataset, raw_dir)
    api.dataset_download_files(settings.kaggle_dataset, path=str(raw_dir), unzip=True, quiet=False)

    _flatten_nested_csvs(raw_dir)

    still_absent = missing_files(raw_dir)
    if still_absent:
        raise FileNotFoundError(
            f"Download finished but these files are still missing: {still_absent}"
        )
    provenance.write(
        raw_dir, source="kaggle", dataset=settings.kaggle_dataset,
        files=len(TABLE_SPECS),
    )
    log.info("Download complete: %d files in %s", len(TABLE_SPECS), raw_dir)
    return raw_dir


def _flatten_nested_csvs(raw_dir: Path) -> None:
    """Kaggle archives occasionally unzip into a subdirectory - flatten it."""
    expected = {s.source_file for s in TABLE_SPECS}
    for nested in raw_dir.rglob("*.csv"):
        if nested.parent == raw_dir or nested.name not in expected:
            continue
        target = raw_dir / nested.name
        if not target.exists():
            shutil.move(str(nested), str(target))
            log.info("Flattened %s -> %s", nested, target)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download the Olist dataset from Kaggle.")
    parser.add_argument("--force", action="store_true", help="Re-download even if files exist.")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(message)s")
    try:
        download_dataset(force=args.force)
    except MissingCredentialsError as exc:
        log.error("%s", exc)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
