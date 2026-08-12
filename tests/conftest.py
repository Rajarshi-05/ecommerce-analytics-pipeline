from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def synthetic_frames():
    """A small generated dataset, built once and shared across the module.

    Generation is the expensive part, so it is session-scoped; tests that need
    to mutate a frame take their own copy.
    """
    from ingestion.synthetic import generate

    return generate(n_orders=1_500, seed=7)


@pytest.fixture
def raw_dir(tmp_path: Path, synthetic_frames) -> Path:
    from ingestion.synthetic import write_csvs

    destination = tmp_path / "raw"
    write_csvs(synthetic_frames, destination, seed=7)
    return destination
