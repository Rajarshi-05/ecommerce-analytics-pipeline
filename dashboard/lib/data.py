"""Dashboard data access with two interchangeable backends.

Local development reads the warehouse directly. The deployed app reads the
Parquet snapshot written by `scripts/export_snapshot.py`, because Streamlit
Community Cloud has no route to a Postgres running on a laptop.

The backend is chosen once at import time and every caller gets the same
DataFrame shape either way, so no page needs to know which mode it is in.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from dashboard.lib.queries import get_dataset

log = logging.getLogger(__name__)

SNAPSHOT_DIR = Path(__file__).resolve().parents[1] / "data"
CACHE_TTL_SECONDS = 600


@dataclass(frozen=True)
class Backend:
    mode: str  # "postgres" | "snapshot"
    detail: str
    generated_at: str | None = None


def _database_url() -> str | None:
    if url := os.getenv("DATABASE_URL"):
        return url
    # Streamlit Cloud injects secrets rather than env vars.
    try:
        return st.secrets["DATABASE_URL"]  # type: ignore[index]
    except Exception:
        return None


@st.cache_resource(show_spinner=False)
def _engine():
    from sqlalchemy import create_engine

    return create_engine(_database_url(), pool_pre_ping=True, pool_recycle=1800, future=True)


@st.cache_resource(show_spinner=False)
def get_backend() -> Backend:
    """Prefer the live warehouse; fall back to the snapshot.

    The connection is probed rather than assumed - a DATABASE_URL pointing at a
    stopped container should degrade to the snapshot, not crash the app.
    """
    url = _database_url()
    if url:
        try:
            from sqlalchemy import text

            with _engine().connect() as conn:
                conn.execute(text("select 1"))
            host = url.rsplit("@", 1)[-1]
            return Backend("postgres", f"live warehouse ({host})")
        except Exception as exc:
            log.warning("Warehouse unreachable (%s) - falling back to snapshot.", exc)

    manifest_path = SNAPSHOT_DIR / "manifest.json"
    generated_at = None
    if manifest_path.is_file():
        with contextlib.suppress(json.JSONDecodeError, KeyError, OSError):
            generated_at = json.loads(
                manifest_path.read_text(encoding="utf-8"))["generated_at"]
    return Backend("snapshot", f"parquet snapshot ({SNAPSHOT_DIR.name}/)", generated_at)


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner="Loading data...")
def load(name: str) -> pd.DataFrame:
    """Load one registered dataset. Returns an empty frame if unavailable."""
    dataset = get_dataset(name)
    backend = get_backend()

    if backend.mode == "postgres":
        from sqlalchemy import text

        try:
            with _engine().connect() as conn:
                return pd.read_sql(text(dataset.sql()), conn)
        except Exception as exc:
            log.warning("Query for '%s' failed (%s) - trying snapshot.", name, exc)

    path = SNAPSHOT_DIR / f"{name}.parquet"
    if path.is_file():
        return pd.read_parquet(path)

    if dataset.required:
        log.error("Dataset '%s' is unavailable in both backends.", name)
    return pd.DataFrame()


def is_available(name: str) -> bool:
    return not load(name).empty


def freshness_caption() -> str:
    backend = get_backend()
    if backend.mode == "postgres":
        return f"Source: {backend.detail}"
    if backend.generated_at:
        try:
            stamp = datetime.fromisoformat(backend.generated_at).strftime("%Y-%m-%d %H:%M UTC")
            return f"Source: {backend.detail}, generated {stamp}"
        except ValueError:
            pass
    return f"Source: {backend.detail}"


def kpis() -> pd.Series:
    frame = load("kpi_summary")
    if frame.empty:
        return pd.Series(dtype="object")
    return frame.iloc[0]
