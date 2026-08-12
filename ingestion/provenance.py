"""Records where the CSVs in data/raw came from.

The raw-zone validator compares row counts against the published Olist figures.
That check is only meaningful for the real dataset - against synthetic or
sampled data it fails by design. Rather than weakening the check, the loader
records provenance when the files are written and the validator reads it to
decide whether the strict comparison applies.

It also means anyone looking at the warehouse can tell whether the numbers in
front of them came from real data.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

log = logging.getLogger(__name__)

MARKER_FILENAME = "_PROVENANCE.json"
Source = Literal["kaggle", "synthetic", "unknown"]


@dataclass(frozen=True)
class Provenance:
    source: Source
    dataset: str
    written_at: str
    detail: dict[str, object]

    @property
    def is_real_data(self) -> bool:
        return self.source == "kaggle"


def write(raw_dir: Path, source: Source, dataset: str, **detail: object) -> Provenance:
    record = Provenance(
        source=source,
        dataset=dataset,
        written_at=datetime.now(UTC).isoformat(timespec="seconds"),
        detail=detail,
    )
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / MARKER_FILENAME).write_text(
        json.dumps(asdict(record), indent=2), encoding="utf-8"
    )
    log.debug("Recorded provenance: %s", record)
    return record


def read(raw_dir: Path) -> Provenance:
    marker = raw_dir / MARKER_FILENAME
    if not marker.is_file():
        return Provenance("unknown", "unknown", "", {})
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
        return Provenance(
            source=payload.get("source", "unknown"),
            dataset=payload.get("dataset", "unknown"),
            written_at=payload.get("written_at", ""),
            detail=payload.get("detail", {}),
        )
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Could not read %s: %s", marker, exc)
        return Provenance("unknown", "unknown", "", {})
