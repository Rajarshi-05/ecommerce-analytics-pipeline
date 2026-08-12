"""Loader unit tests that need no database.

The parts worth isolating are the type coercion (a single bad value must become
NULL rather than abort a COPY) and the generated SQL (the merge statement is
what makes the pipeline idempotent).
"""

from __future__ import annotations

import pandas as pd
import pytest

from ingestion.load import _coerce, _full_refresh_sql, _merge_sql
from ingestion.schemas import get_spec


def test_coerce_casts_declared_types():
    spec = get_spec("order_items")
    frame = pd.DataFrame({
        "order_id": [" abc "],
        "order_item_id": ["2"],
        "product_id": ["p1"],
        "seller_id": ["s1"],
        "shipping_limit_date": ["2018-01-05 10:00:00"],
        "price": ["19.90"],
        "freight_value": ["7.50"],
    })
    out = _coerce(frame, spec)

    assert out["order_id"].iloc[0] == "abc"          # trimmed
    assert out["order_item_id"].iloc[0] == 2
    assert out["price"].iloc[0] == pytest.approx(19.90)
    assert isinstance(out["shipping_limit_date"].iloc[0], pd.Timestamp)


def test_coerce_turns_unparseable_values_into_nulls():
    """A bad row must degrade to NULL so dbt's not_null test catches it, rather
    than aborting the COPY and failing the whole load."""
    spec = get_spec("order_items")
    frame = pd.DataFrame({
        "order_id": ["abc"],
        "order_item_id": ["not-a-number"],
        "product_id": ["p1"],
        "seller_id": ["s1"],
        "shipping_limit_date": ["definitely not a date"],
        "price": ["twelve"],
        "freight_value": ["7.50"],
    })
    out = _coerce(frame, spec)

    assert pd.isna(out["order_item_id"].iloc[0])
    assert pd.isna(out["shipping_limit_date"].iloc[0])
    assert pd.isna(out["price"].iloc[0])
    assert out["freight_value"].iloc[0] == pytest.approx(7.50)


def test_coerce_fills_missing_columns_with_nulls():
    spec = get_spec("sellers")
    frame = pd.DataFrame({"seller_id": ["s1"], "seller_state": ["SP"]})
    out = _coerce(frame, spec)

    assert list(out.columns) == list(spec.columns)
    assert pd.isna(out["seller_city"].iloc[0])


def test_coerce_preserves_column_order():
    spec = get_spec("customers")
    frame = pd.DataFrame({column: ["x"] for column in reversed(list(spec.columns))})
    assert list(_coerce(frame, spec).columns) == list(spec.columns)


def test_merge_sql_upserts_on_the_primary_key():
    spec = get_spec("orders")
    sql = _merge_sql(spec, "raw", 'raw."_stg_orders"')

    assert "ON CONFLICT" in sql
    assert '"order_id"' in sql
    assert "DO UPDATE SET" in sql
    # The primary key must not appear in the SET clause.
    set_clause = sql.split("DO UPDATE SET", 1)[1]
    assert '"order_id" = EXCLUDED' not in set_clause
    assert '"order_status" = EXCLUDED."order_status"' in set_clause


def test_merge_sql_dedupes_within_the_incoming_file():
    """ON CONFLICT cannot touch the same target row twice in one statement, so
    duplicate keys inside the source file must be collapsed first."""
    sql = _merge_sql(get_spec("order_items"), "raw", 'raw."_stg_order_items"')
    assert "DISTINCT ON" in sql
    assert '"order_id", "order_item_id"' in sql


def test_merge_sql_refreshes_the_load_timestamp():
    sql = _merge_sql(get_spec("sellers"), "raw", 'raw."_stg_sellers"')
    assert '"_loaded_at" = now()' in sql


def test_full_refresh_sql_replaces_the_table():
    sql = _full_refresh_sql(get_spec("geolocation"), "raw", 'raw."_stg_geolocation"')
    assert "TRUNCATE TABLE" in sql
    assert "INSERT INTO" in sql
    assert sql.index("TRUNCATE") < sql.index("INSERT")


def test_generated_sql_includes_the_lineage_column():
    for builder in (_merge_sql, _full_refresh_sql):
        sql = builder(get_spec("customers"), "raw", 'raw."_stg_customers"')
        assert '"_source_file"' in sql
