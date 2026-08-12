"""Declarative spec for the nine Olist source files.

Everything the loader needs — target table, column types, load strategy, and the
published row count to sanity-check against — lives here so adding a source is a
data change rather than a code change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

LoadStrategy = Literal["merge", "full_refresh"]

# Postgres types for the raw zone. Deliberately permissive: the raw layer is a
# faithful copy of the source, so anything that could be dirty lands as TEXT and
# gets cast in dbt staging where the failure is visible and testable.
TEXT = "TEXT"
INT = "INTEGER"
NUM = "NUMERIC(12,2)"
TS = "TIMESTAMP"
FLOAT = "DOUBLE PRECISION"


@dataclass(frozen=True)
class TableSpec:
    name: str
    source_file: str
    columns: dict[str, str]
    strategy: LoadStrategy
    primary_key: tuple[str, ...] = ()
    expected_rows: int | None = None
    notes: str = ""
    # Tables whose rows must survive sampling intact (reference/lookup data).
    never_sample: bool = False
    parse_dates: tuple[str, ...] = field(default_factory=tuple)

    def ddl(self, schema: str) -> str:
        """Target DDL, including the lineage columns every raw table carries."""
        lines = [f'"{c}" {t}' for c, t in self.columns.items()]
        lines.append('"_source_file" TEXT')
        lines.append('"_loaded_at" TIMESTAMPTZ NOT NULL DEFAULT now()')
        if self.strategy == "merge":
            if not self.primary_key:
                raise ValueError(f"{self.name}: merge strategy requires a primary_key")
            pk = ", ".join(f'"{c}"' for c in self.primary_key)
            lines.append(f"CONSTRAINT {self.name}_pkey PRIMARY KEY ({pk})")
        body = ",\n    ".join(lines)
        return f'CREATE TABLE IF NOT EXISTS {schema}."{self.name}" (\n    {body}\n);'


TABLE_SPECS: tuple[TableSpec, ...] = (
    TableSpec(
        name="customers",
        source_file="olist_customers_dataset.csv",
        columns={
            "customer_id": TEXT,
            "customer_unique_id": TEXT,
            "customer_zip_code_prefix": TEXT,
            "customer_city": TEXT,
            "customer_state": TEXT,
        },
        strategy="merge",
        primary_key=("customer_id",),
        expected_rows=99_441,
        notes="customer_id is per-order; customer_unique_id is the real person.",
    ),
    TableSpec(
        name="geolocation",
        source_file="olist_geolocation_dataset.csv",
        columns={
            "geolocation_zip_code_prefix": TEXT,
            "geolocation_lat": FLOAT,
            "geolocation_lng": FLOAT,
            "geolocation_city": TEXT,
            "geolocation_state": TEXT,
        },
        strategy="full_refresh",
        expected_rows=1_000_163,
        notes="No natural key - many lat/lng points per zip prefix. dbt averages them.",
    ),
    TableSpec(
        name="order_items",
        source_file="olist_order_items_dataset.csv",
        columns={
            "order_id": TEXT,
            "order_item_id": INT,
            "product_id": TEXT,
            "seller_id": TEXT,
            "shipping_limit_date": TS,
            "price": NUM,
            "freight_value": NUM,
        },
        strategy="merge",
        primary_key=("order_id", "order_item_id"),
        expected_rows=112_650,
        parse_dates=("shipping_limit_date",),
    ),
    TableSpec(
        name="order_payments",
        source_file="olist_order_payments_dataset.csv",
        columns={
            "order_id": TEXT,
            "payment_sequential": INT,
            "payment_type": TEXT,
            "payment_installments": INT,
            "payment_value": NUM,
        },
        strategy="merge",
        primary_key=("order_id", "payment_sequential"),
        expected_rows=103_886,
    ),
    TableSpec(
        name="order_reviews",
        source_file="olist_order_reviews_dataset.csv",
        columns={
            "review_id": TEXT,
            "order_id": TEXT,
            "review_score": INT,
            "review_comment_title": TEXT,
            "review_comment_message": TEXT,
            "review_creation_date": TS,
            "review_answer_timestamp": TS,
        },
        strategy="full_refresh",
        expected_rows=99_224,
        parse_dates=("review_creation_date", "review_answer_timestamp"),
        notes=(
            "review_id is NOT unique in the source (~800 duplicates). Loaded "
            "faithfully; stg_order_reviews de-duplicates to one row per order."
        ),
    ),
    TableSpec(
        name="orders",
        source_file="olist_orders_dataset.csv",
        columns={
            "order_id": TEXT,
            "customer_id": TEXT,
            "order_status": TEXT,
            "order_purchase_timestamp": TS,
            "order_approved_at": TS,
            "order_delivered_carrier_date": TS,
            "order_delivered_customer_date": TS,
            "order_estimated_delivery_date": TS,
        },
        strategy="merge",
        primary_key=("order_id",),
        expected_rows=99_441,
        parse_dates=(
            "order_purchase_timestamp",
            "order_approved_at",
            "order_delivered_carrier_date",
            "order_delivered_customer_date",
            "order_estimated_delivery_date",
        ),
    ),
    TableSpec(
        name="products",
        source_file="olist_products_dataset.csv",
        columns={
            "product_id": TEXT,
            "product_category_name": TEXT,
            "product_name_lenght": INT,
            "product_description_lenght": INT,
            "product_photos_qty": INT,
            "product_weight_g": INT,
            "product_length_cm": INT,
            "product_height_cm": INT,
            "product_width_cm": INT,
        },
        strategy="merge",
        primary_key=("product_id",),
        expected_rows=32_951,
        notes="Source misspells 'length' as 'lenght' - preserved in raw, fixed in staging.",
    ),
    TableSpec(
        name="sellers",
        source_file="olist_sellers_dataset.csv",
        columns={
            "seller_id": TEXT,
            "seller_zip_code_prefix": TEXT,
            "seller_city": TEXT,
            "seller_state": TEXT,
        },
        strategy="merge",
        primary_key=("seller_id",),
        expected_rows=3_095,
    ),
    TableSpec(
        name="product_category_translation",
        source_file="product_category_name_translation.csv",
        columns={
            "product_category_name": TEXT,
            "product_category_name_english": TEXT,
        },
        strategy="merge",
        primary_key=("product_category_name",),
        expected_rows=71,
        never_sample=True,
    ),
)

SPECS_BY_NAME: dict[str, TableSpec] = {s.name: s for s in TABLE_SPECS}


def get_spec(name: str) -> TableSpec:
    try:
        return SPECS_BY_NAME[name]
    except KeyError:
        known = ", ".join(sorted(SPECS_BY_NAME))
        raise KeyError(f"Unknown table '{name}'. Known tables: {known}") from None
