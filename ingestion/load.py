"""Load Olist CSVs into the Postgres `raw` schema, idempotently.

Two strategies, chosen per table in `schemas.py`:

* ``merge``        - COPY into a staging table, then INSERT .. ON CONFLICT DO
                     UPDATE on the natural key. Re-running the same file is a
                     no-op; a file with corrections updates in place. This is
                     what makes the Airflow DAG safe to retry or backfill.
* ``full_refresh`` - COPY into a staging table, then swap it in inside a single
                     transaction. Used where the source has no usable natural
                     key (geolocation) or has known duplicate keys that must be
                     preserved verbatim for dbt to resolve (order_reviews).

Either way the target table is never left partially written: readers see the
old contents until the transaction commits.
"""

from __future__ import annotations

import csv
import io
import logging
import time
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import text

from ingestion.config import get_settings
from ingestion.db import ensure_schemas, get_engine, raw_connection
from ingestion.schemas import TABLE_SPECS, TableSpec, get_spec

log = logging.getLogger(__name__)

CHUNK_ROWS = 100_000


class SourceFileMissingError(FileNotFoundError):
    pass


# --------------------------------------------------------------------- read --
def _coerce(frame: pd.DataFrame, spec: TableSpec) -> pd.DataFrame:
    """Cast a chunk to the target column types, keeping unparseable values NULL.

    Coercion happens here rather than in Postgres so a single bad row degrades
    to a NULL that dbt's not_null tests will catch, instead of aborting the COPY
    and failing the whole load.
    """
    out = pd.DataFrame(index=frame.index)
    for column, pg_type in spec.columns.items():
        if column not in frame.columns:
            log.warning("%s: source is missing column '%s' - filling with NULL",
                        spec.name, column)
            out[column] = pd.NA
            continue

        series = frame[column]
        if pg_type == "INTEGER":
            out[column] = pd.to_numeric(series, errors="coerce").round().astype("Int64")
        elif pg_type in ("NUMERIC(12,2)", "DOUBLE PRECISION"):
            out[column] = pd.to_numeric(series, errors="coerce")
        elif pg_type == "TIMESTAMP":
            out[column] = pd.to_datetime(series, errors="coerce")
        else:
            out[column] = series.astype("string").str.strip()
    return out


def _read_chunks(path: Path, spec: TableSpec, sample_rows: int | None):
    reader = pd.read_csv(
        path,
        dtype=str,
        keep_default_na=True,
        na_values=[""],
        chunksize=CHUNK_ROWS,
        encoding="utf-8",
    )
    emitted = 0
    for chunk in reader:
        if sample_rows is not None:
            remaining = sample_rows - emitted
            if remaining <= 0:
                return
            chunk = chunk.head(remaining)
        emitted += len(chunk)
        yield _coerce(chunk, spec)


# -------------------------------------------------------------------- write --
def _copy_chunk(cursor, frame: pd.DataFrame, qualified: str, columns: list[str],
                source_file: str) -> None:
    buffer = io.StringIO()
    frame.assign(_source_file=source_file).to_csv(
        buffer,
        index=False,
        header=False,
        columns=[*columns, "_source_file"],
        na_rep="",
        quoting=csv.QUOTE_MINIMAL,
        date_format="%Y-%m-%d %H:%M:%S",
    )
    buffer.seek(0)
    column_list = ", ".join(f'"{c}"' for c in [*columns, "_source_file"])
    cursor.copy_expert(
        f"COPY {qualified} ({column_list}) FROM STDIN WITH (FORMAT csv, NULL '')",
        buffer,
    )


def _merge_sql(spec: TableSpec, schema: str, staging: str) -> str:
    columns = list(spec.columns) + ["_source_file"]
    column_list = ", ".join(f'"{c}"' for c in columns)
    pk = ", ".join(f'"{c}"' for c in spec.primary_key)
    updates = ", ".join(
        f'"{c}" = EXCLUDED."{c}"' for c in columns if c not in spec.primary_key
    )
    updates = f"{updates}, \"_loaded_at\" = now()" if updates else '"_loaded_at" = now()'
    # DISTINCT ON guards against duplicate keys *within* the incoming file:
    # ON CONFLICT cannot touch the same target row twice in one statement.
    return f"""
        INSERT INTO {schema}."{spec.name}" ({column_list})
        SELECT DISTINCT ON ({pk}) {column_list}
        FROM {staging}
        ORDER BY {pk}
        ON CONFLICT ({pk}) DO UPDATE SET {updates};
    """


def _full_refresh_sql(spec: TableSpec, schema: str, staging: str) -> str:
    columns = list(spec.columns) + ["_source_file"]
    column_list = ", ".join(f'"{c}"' for c in columns)
    return f"""
        TRUNCATE TABLE {schema}."{spec.name}";
        INSERT INTO {schema}."{spec.name}" ({column_list})
        SELECT {column_list} FROM {staging};
    """


def load_table(table: str, run_id: str | None = None) -> dict[str, object]:
    """Load one source file into `raw`. Returns a summary dict for the DAG log."""
    settings = get_settings()
    spec = get_spec(table)
    path = settings.raw_dir / spec.source_file
    if not path.is_file():
        raise SourceFileMissingError(
            f"{spec.source_file} not found in {settings.raw_dir}. "
            "Run `python -m ingestion.cli download` or `... seed --synthetic` first."
        )

    sample_rows = (
        settings.sample_rows
        if settings.sample_mode and not spec.never_sample
        else None
    )
    schema = settings.raw_schema
    staging = f'{schema}."_stg_{spec.name}"'
    qualified = f'{schema}."{spec.name}"'
    columns = list(spec.columns)

    started_at = datetime.now(UTC)
    clock = time.perf_counter()
    ensure_schemas(schema, "meta")

    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text(spec.ddl(schema)))

    rows_read = 0
    with raw_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(f"DROP TABLE IF EXISTS {staging}")
        cursor.execute(
            f"CREATE UNLOGGED TABLE {staging} "
            f"(LIKE {qualified} INCLUDING DEFAULTS EXCLUDING CONSTRAINTS)"
        )
        for chunk in _read_chunks(path, spec, sample_rows):
            _copy_chunk(cursor, chunk, staging, columns, spec.source_file)
            rows_read += len(chunk)
            log.info("%s: staged %d rows", spec.name, rows_read)

        sql = (_merge_sql(spec, schema, staging) if spec.strategy == "merge"
               else _full_refresh_sql(spec, schema, staging))
        cursor.execute(sql)
        cursor.execute(f"DROP TABLE IF EXISTS {staging}")

        cursor.execute(f"SELECT count(*) FROM {qualified}")
        rows_loaded = int(cursor.fetchone()[0])

        cursor.execute(
            """
            INSERT INTO meta.ingestion_audit
                (table_name, source_file, rows_in_source, rows_loaded,
                 load_strategy, started_at, run_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (spec.name, spec.source_file, rows_read, rows_loaded,
             spec.strategy, started_at, run_id),
        )

    elapsed = time.perf_counter() - clock
    log.info(
        "%-28s %-13s read=%-9d table_total=%-9d %.1fs",
        spec.name, spec.strategy, rows_read, rows_loaded, elapsed,
    )
    return {
        "table": spec.name,
        "strategy": spec.strategy,
        "rows_read": rows_read,
        "rows_in_table": rows_loaded,
        "seconds": round(elapsed, 2),
    }


def reset_raw_zone() -> list[str]:
    """Truncate every raw table.

    The merge strategy is keyed on the source's natural keys, which makes
    re-running the *same* extract a no-op. Loading a *different* extract - a
    regenerated synthetic dataset, or switching from synthetic to the real
    Kaggle download - brings entirely new keys, so those rows are inserted
    alongside the old ones rather than replacing them. That is correct upsert
    behaviour, not a bug, but it means swapping datasets needs an explicit
    reset. This is that reset.
    """
    settings = get_settings()
    schema = settings.raw_schema
    truncated = []
    engine = get_engine()
    with engine.begin() as conn:
        for spec in TABLE_SPECS:
            exists = conn.execute(
                text("SELECT to_regclass(:q)"), {"q": f'"{schema}"."{spec.name}"'}
            ).scalar()
            if exists:
                conn.execute(text(f'TRUNCATE TABLE {schema}."{spec.name}"'))
                truncated.append(spec.name)
    log.warning("Truncated %d raw table(s): %s", len(truncated), ", ".join(truncated))
    return truncated


def load_all(run_id: str | None = None, only: list[str] | None = None) -> list[dict[str, object]]:
    specs = TABLE_SPECS if not only else [get_spec(name) for name in only]
    results = []
    for spec in specs:
        results.append(load_table(spec.name, run_id=run_id))
    total = sum(int(r["rows_read"]) for r in results)
    log.info("Loaded %d tables, %d rows read in total.", len(results), total)
    return results
