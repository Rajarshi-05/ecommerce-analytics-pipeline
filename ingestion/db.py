from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, text

from ingestion.config import get_settings

log = logging.getLogger(__name__)

_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(
            settings.database_url,
            pool_pre_ping=True,
            future=True,
        )
    return _engine


@contextmanager
def raw_connection() -> Iterator:
    """psycopg2 connection for COPY. Commits on success, rolls back on error."""
    conn = get_engine().raw_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def ensure_schemas(*schemas: str) -> None:
    with get_engine().begin() as conn:
        for schema in schemas:
            conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))


def table_row_count(schema: str, table: str) -> int:
    with get_engine().connect() as conn:
        result = conn.execute(text(f'SELECT count(*) FROM "{schema}"."{table}"'))
        return int(result.scalar_one())


def table_exists(schema: str, table: str) -> bool:
    with get_engine().connect() as conn:
        result = conn.execute(
            text("SELECT to_regclass(:qualified)"),
            {"qualified": f'"{schema}"."{table}"'},
        )
        return result.scalar() is not None
