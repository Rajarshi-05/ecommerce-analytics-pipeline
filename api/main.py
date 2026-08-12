"""Read-only API over the mart and ML layers.

Serves the model outputs the dashboard does not need but a downstream system
would: a customer's segment, the current forecast, category and seller
league tables. Read-only by design - the warehouse is written by the pipeline,
never by a request.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import date
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import Engine, create_engine, text

MAX_PAGE_SIZE = 500


def _database_url() -> str:
    if url := os.getenv("DATABASE_URL"):
        return url
    return (
        f"postgresql+psycopg2://{os.getenv('POSTGRES_USER', 'analytics')}:"
        f"{os.getenv('POSTGRES_PASSWORD', 'analytics')}@"
        f"{os.getenv('POSTGRES_HOST', 'postgres')}:"
        f"{os.getenv('POSTGRES_PORT', '5432')}/"
        f"{os.getenv('POSTGRES_DB', 'ecommerce')}"
    )


_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(_database_url(), pool_pre_ping=True, pool_size=5, future=True)
    return _engine


def fetch_all(query: str, **params: Any) -> list[dict[str, Any]]:
    with get_engine().connect() as conn:
        result = conn.execute(text(query), params)
        return [dict(row) for row in result.mappings()]


def fetch_one(query: str, **params: Any) -> dict[str, Any] | None:
    rows = fetch_all(query, **params)
    return rows[0] if rows else None


def relation_exists(relation: str) -> bool:
    with get_engine().connect() as conn:
        return conn.execute(
            text("select to_regclass(:q)"), {"q": relation}
        ).scalar() is not None


def require(relation: str) -> None:
    if not relation_exists(relation):
        raise HTTPException(
            status_code=503,
            detail=f"{relation} is not available yet - run the pipeline first.",
        )


@asynccontextmanager
async def lifespan(_: FastAPI):
    get_engine()
    yield
    if _engine is not None:
        _engine.dispose()


app = FastAPI(
    title="Olist Analytics API",
    description=__doc__,
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)


# ------------------------------------------------------------------ models --
class Health(BaseModel):
    status: str
    warehouse_reachable: bool
    marts_ready: bool
    ml_ready: bool


class CustomerSegment(BaseModel):
    customer_key: str
    customer_state: str | None = None
    recency_days: int
    frequency: int
    monetary: float
    rfm_segment: str
    lifecycle_stage: str | None = None
    cluster_label: str | None = Field(None, description="KMeans cluster; null before ML has run.")


class ForecastPoint(BaseModel):
    date: date
    forecast_revenue: float
    forecast_lower: float
    forecast_upper: float
    is_forecast: bool


class CategoryRow(BaseModel):
    product_category: str
    revenue: float
    order_count: int
    revenue_share_pct: float | None = None
    avg_review_score: float | None = None


class SellerRow(BaseModel):
    seller_id: str
    seller_state: str | None = None
    revenue: float
    order_count: int
    avg_review_score: float | None = None
    late_delivery_pct: float | None = None
    is_at_risk_seller: bool | None = None


# ---------------------------------------------------------------- endpoints --
@app.get("/health", response_model=Health, tags=["meta"])
def health() -> Health:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("select 1"))
        reachable = True
    except Exception:
        return Health(status="degraded", warehouse_reachable=False,
                      marts_ready=False, ml_ready=False)

    marts = relation_exists("marts.fact_orders")
    ml_ready = relation_exists("ml.customer_segments")
    return Health(
        status="ok" if marts else "warming",
        warehouse_reachable=reachable, marts_ready=marts, ml_ready=ml_ready,
    )


@app.get("/kpis", tags=["analytics"])
def kpis() -> dict[str, Any]:
    require("analytics.agg_kpi_summary")
    row = fetch_one("select * from analytics.agg_kpi_summary")
    if not row:
        raise HTTPException(status_code=404, detail="No KPI row found.")
    return row


@app.get("/customers/{customer_key}/segment", response_model=CustomerSegment,
         tags=["customers"])
def customer_segment(customer_key: str) -> CustomerSegment:
    """Look up one customer's RFM segment and, if available, KMeans cluster."""
    require("analytics.agg_customer_rfm")
    # LEFT JOIN so the endpoint still answers before the ML tasks have run.
    row = fetch_one(
        """
        select
            r.customer_key, r.customer_state, r.recency_days, r.frequency,
            r.monetary, r.rfm_segment, r.lifecycle_stage, s.cluster_label
        from analytics.agg_customer_rfm r
        left join ml.customer_segments s using (customer_key)
        where r.customer_key = :customer_key
        """
        if relation_exists("ml.customer_segments") else
        """
        select
            customer_key, customer_state, recency_days, frequency,
            monetary, rfm_segment, lifecycle_stage, null as cluster_label
        from analytics.agg_customer_rfm
        where customer_key = :customer_key
        """,
        customer_key=customer_key,
    )
    if not row:
        raise HTTPException(status_code=404, detail=f"No customer '{customer_key}'.")
    return CustomerSegment(**row)


@app.get("/segments", tags=["customers"])
def segments() -> list[dict[str, Any]]:
    """Segment sizes and value. Aggregated - never returns customer rows."""
    require("analytics.agg_customer_rfm")
    return fetch_all("""
        select
            rfm_segment, lifecycle_stage,
            count(*)                        as customer_count,
            round(avg(recency_days))        as avg_recency_days,
            round(avg(frequency), 2)        as avg_frequency,
            round(avg(monetary), 2)         as avg_monetary,
            round(sum(monetary), 2)         as total_monetary
        from analytics.agg_customer_rfm
        group by rfm_segment, lifecycle_stage
        order by total_monetary desc
    """)


@app.get("/forecast", response_model=list[ForecastPoint], tags=["forecast"])
def forecast(
    horizon_only: bool = Query(True, description="Return only projected days."),
    limit: int = Query(180, ge=1, le=MAX_PAGE_SIZE),
) -> list[ForecastPoint]:
    require("ml.revenue_forecast_daily")
    rows = fetch_all(
        f"""
        select
            ds::date              as date,
            forecast_revenue,
            forecast_lower,
            forecast_upper,
            is_forecast
        from ml.revenue_forecast_daily
        {"where is_forecast" if horizon_only else ""}
        order by ds
        limit :limit
        """,
        limit=limit,
    )
    return [ForecastPoint(**row) for row in rows]


@app.get("/categories", response_model=list[CategoryRow], tags=["analytics"])
def categories(limit: int = Query(25, ge=1, le=MAX_PAGE_SIZE)) -> list[CategoryRow]:
    require("analytics.agg_category_performance")
    rows = fetch_all(
        """
        select product_category, revenue, order_count, revenue_share_pct, avg_review_score
        from analytics.agg_category_performance
        order by revenue desc
        limit :limit
        """,
        limit=limit,
    )
    return [CategoryRow(**row) for row in rows]


@app.get("/sellers", response_model=list[SellerRow], tags=["analytics"])
def sellers(
    limit: int = Query(50, ge=1, le=MAX_PAGE_SIZE),
    at_risk_only: bool = Query(False, description="Only sellers flagged for delivery issues."),
) -> list[SellerRow]:
    require("analytics.agg_seller_performance")
    rows = fetch_all(
        f"""
        select seller_id, seller_state, revenue, order_count,
               avg_review_score, late_delivery_pct, is_at_risk_seller
        from analytics.agg_seller_performance
        {"where is_at_risk_seller" if at_risk_only else ""}
        order by revenue desc
        limit :limit
        """,
        limit=limit,
    )
    return [SellerRow(**row) for row in rows]


@app.get("/delivery-impact", tags=["analytics"])
def delivery_impact() -> list[dict[str, Any]]:
    """Review score by lateness bucket - the project's headline finding."""
    require("analytics.agg_delivery_review_correlation")
    return fetch_all("select * from analytics.agg_delivery_review_correlation")
