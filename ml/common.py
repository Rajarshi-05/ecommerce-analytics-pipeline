from __future__ import annotations

import logging
import os
from datetime import UTC, datetime

import pandas as pd
from sqlalchemy import Engine, create_engine, text

log = logging.getLogger(__name__)

ML_SCHEMA = "ml"

_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        url = os.getenv("DATABASE_URL")
        if not url:
            url = (
                f"postgresql+psycopg2://{os.getenv('POSTGRES_USER', 'analytics')}:"
                f"{os.getenv('POSTGRES_PASSWORD', 'analytics')}@"
                f"{os.getenv('POSTGRES_HOST', 'localhost')}:"
                f"{os.getenv('POSTGRES_PORT', '5432')}/"
                f"{os.getenv('POSTGRES_DB', 'ecommerce')}"
            )
        _engine = create_engine(url, pool_pre_ping=True, future=True)
    return _engine


def read_sql(query: str) -> pd.DataFrame:
    with get_engine().connect() as conn:
        return pd.read_sql(text(query), conn)


def write_table(frame: pd.DataFrame, table: str, run_id: str | None = None) -> int:
    """Replace an ML output table, stamping every row with the producing run.

    Replace rather than append: these are full recomputations over the whole
    mart, so appending would just accumulate stale generations of the same
    prediction.
    """
    stamped = frame.copy()
    stamped["generated_at"] = datetime.now(UTC)
    stamped["run_id"] = run_id

    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{ML_SCHEMA}"'))

    stamped.to_sql(
        table,
        engine,
        schema=ML_SCHEMA,
        if_exists="replace",
        index=False,
        chunksize=10_000,
        method="multi",
    )
    log.info("Wrote %s.%s (%d rows)", ML_SCHEMA, table, len(stamped))
    return len(stamped)


def configure_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)-22s %(message)s",
        datefmt="%H:%M:%S",
    )
    # Prophet/cmdstanpy chatter drowns out everything else at INFO.
    for noisy in ("cmdstanpy", "prophet", "matplotlib"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
