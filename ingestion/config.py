from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=False)


def _project_root() -> Path:
    if env_root := os.getenv("PROJECT_ROOT"):
        return Path(env_root)
    return Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    database_url: str
    raw_schema: str
    data_dir: Path
    kaggle_dataset: str
    sample_mode: bool
    sample_rows: int

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    url = os.getenv("DATABASE_URL")
    if not url:
        user = os.getenv("POSTGRES_USER", "analytics")
        password = os.getenv("POSTGRES_PASSWORD", "analytics")
        host = os.getenv("POSTGRES_HOST", "localhost")
        port = os.getenv("POSTGRES_PORT", "5432")
        database = os.getenv("POSTGRES_DB", "ecommerce")
        url = f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{database}"

    return Settings(
        database_url=url,
        raw_schema=os.getenv("RAW_SCHEMA", "raw"),
        data_dir=Path(os.getenv("DATA_DIR", _project_root() / "data")),
        kaggle_dataset=os.getenv("KAGGLE_DATASET", "olistbr/brazilian-ecommerce"),
        sample_mode=os.getenv("INGEST_SAMPLE_MODE", "false").lower() == "true",
        sample_rows=int(os.getenv("INGEST_SAMPLE_ROWS", "5000")),
    )
