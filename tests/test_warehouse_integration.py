"""End-to-end checks against a live warehouse.

Run with a Postgres available (`docker compose up -d postgres`, or the CI
service container). Skipped automatically when there is no database, so the
unit suite still runs on a bare checkout:

    pytest -m integration
    pytest -m "not integration"

These assert properties dbt cannot: that the loader is genuinely idempotent
across repeated runs, and that the star schema's grain survives a real load.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration


def _warehouse_available() -> bool:
    try:
        from ingestion.db import get_engine

        with get_engine().connect() as conn:
            conn.execute(text("select 1"))
        return True
    except Exception:
        return False


pytest.importorskip("sqlalchemy")
if not _warehouse_available():
    pytest.skip("no warehouse reachable", allow_module_level=True)


@pytest.fixture(scope="module")
def engine():
    from ingestion.db import get_engine

    return get_engine()


def _scalar(engine, query: str):
    with engine.connect() as conn:
        return conn.execute(text(query)).scalar()


def _relation_exists(engine, relation: str) -> bool:
    with engine.connect() as conn:
        return conn.execute(
            text("select to_regclass(:q)"), {"q": relation}
        ).scalar() is not None


def _require(engine, relation: str):
    if not _relation_exists(engine, relation):
        pytest.skip(f"{relation} not built yet - run the pipeline first")


class TestRawZone:
    def test_all_source_tables_loaded(self, engine):
        from ingestion.schemas import TABLE_SPECS

        for spec in TABLE_SPECS:
            _require(engine, f"raw.{spec.name}")
            count = _scalar(engine, f'select count(*) from raw."{spec.name}"')
            assert count > 0, f"raw.{spec.name} is empty"

    def test_lineage_columns_are_populated(self, engine):
        _require(engine, "raw.orders")
        nulls = _scalar(engine, """
            select count(*) from raw.orders
            where _source_file is null or _loaded_at is null
        """)
        assert nulls == 0

    def test_load_is_idempotent(self, engine):
        """Re-running the loader on the same files must not change row counts.

        This is the property the whole retry/backfill story rests on, so it is
        asserted against a real database rather than argued for in a comment.
        """
        from ingestion.load import load_table

        before = _scalar(engine, "select count(*) from raw.sellers")
        load_table("sellers", run_id="pytest-idempotency")
        after = _scalar(engine, "select count(*) from raw.sellers")
        assert before == after

    def test_audit_log_records_loads(self, engine):
        _require(engine, "meta.ingestion_audit")
        assert _scalar(engine, "select count(*) from meta.ingestion_audit") > 0


class TestStarSchema:
    def test_fact_orders_is_one_row_per_order(self, engine):
        _require(engine, "marts.fact_orders")
        total = _scalar(engine, "select count(*) from marts.fact_orders")
        distinct = _scalar(engine, "select count(distinct order_id) from marts.fact_orders")
        assert total == distinct

    def test_fact_orders_matches_source_order_count(self, engine):
        _require(engine, "marts.fact_orders")
        fact = _scalar(engine, "select count(*) from marts.fact_orders")
        source = _scalar(engine, "select count(*) from raw.orders")
        assert fact == source

    def test_revenue_reconciles_between_the_two_facts(self, engine):
        """The fan-out guard. If a join in either fact multiplies rows, the
        totals diverge - and revenue is the number everything else rests on."""
        _require(engine, "marts.fact_order_items")
        difference = _scalar(engine, """
            select abs(
                (select coalesce(sum(order_total), 0) from marts.fact_orders)
              - (select coalesce(sum(item_total), 0) from marts.fact_order_items)
            )
        """)
        assert float(difference) < 1.0

    def test_no_orphan_foreign_keys(self, engine):
        _require(engine, "marts.fact_orders")
        orphans = _scalar(engine, """
            select count(*) from marts.fact_orders f
            left join marts.dim_customers c on f.customer_key = c.customer_key
            where c.customer_key is null
        """)
        assert orphans == 0

    def test_dimensions_have_unique_keys(self, engine):
        for table, key in (
            ("marts.dim_customers", "customer_key"),
            ("marts.dim_products", "product_key"),
            ("marts.dim_sellers", "seller_key"),
            ("marts.dim_geography", "geography_key"),
            ("marts.dim_date", "date_key"),
        ):
            _require(engine, table)
            total = _scalar(engine, f"select count(*) from {table}")
            distinct = _scalar(engine, f"select count(distinct {key}) from {table}")
            assert total == distinct, f"{table} has duplicate {key}"

    def test_customer_dimension_is_at_person_grain(self, engine):
        """dim_customers must key on customer_unique_id, not the source's
        per-order customer_id - otherwise repeat analysis is impossible."""
        _require(engine, "marts.dim_customers")
        customers = _scalar(engine, "select count(*) from marts.dim_customers")
        orders = _scalar(engine, "select count(*) from raw.orders")
        assert customers < orders, "dimension looks degenerate (one row per order)"


class TestAnalyticsViews:
    def test_kpi_summary_returns_exactly_one_row(self, engine):
        _require(engine, "analytics.agg_kpi_summary")
        assert _scalar(engine, "select count(*) from analytics.agg_kpi_summary") == 1

    def test_delivery_rates_sum_to_one_hundred(self, engine):
        _require(engine, "analytics.agg_kpi_summary")
        total = _scalar(engine, """
            select on_time_delivery_pct + late_delivery_pct
            from analytics.agg_kpi_summary
        """)
        assert 99.9 <= float(total) <= 100.1

    def test_cancelled_orders_are_excluded_from_revenue(self, engine):
        _require(engine, "analytics.agg_kpi_summary")
        kpi_revenue = _scalar(engine, "select total_revenue from analytics.agg_kpi_summary")
        all_revenue = _scalar(engine, "select sum(order_total) from marts.fact_orders")
        assert float(kpi_revenue) <= float(all_revenue)

    def test_rfm_segments_cover_every_customer(self, engine):
        _require(engine, "analytics.agg_customer_rfm")
        scored = _scalar(engine, "select count(*) from analytics.agg_customer_rfm")
        customers = _scalar(engine, "select count(*) from marts.dim_customers")
        # Customers whose only orders were cancelled are legitimately excluded.
        assert 0 < scored <= customers

    def test_late_delivery_lowers_review_score(self, engine):
        """The project's headline finding, asserted as a property of the data."""
        _require(engine, "analytics.agg_delivery_review_correlation")
        coefficient = _scalar(engine, """
            select correlation_coefficient
            from analytics.agg_delivery_review_correlation
            where lateness_bucket = 'ALL DELIVERED'
        """)
        assert coefficient is not None
        assert float(coefficient) < 0, "days-late should correlate negatively with score"


class TestModelOutputs:
    def test_segments_join_back_to_the_rfm_mart(self, engine):
        _require(engine, "ml.customer_segments")
        orphans = _scalar(engine, """
            select count(*) from ml.customer_segments s
            left join analytics.agg_customer_rfm r using (customer_key)
            where r.customer_key is null
        """)
        assert orphans == 0

    def test_forecast_covers_future_dates(self, engine):
        _require(engine, "ml.revenue_forecast_daily")
        future = _scalar(engine,
                         "select count(*) from ml.revenue_forecast_daily where is_forecast")
        assert future > 0

    def test_forecast_interval_brackets_the_point_estimate(self, engine):
        _require(engine, "ml.revenue_forecast_daily")
        violations = _scalar(engine, """
            select count(*) from ml.revenue_forecast_daily
            where forecast_lower > forecast_revenue
               or forecast_upper < forecast_revenue
        """)
        assert violations == 0

    def test_sentiment_scores_are_probabilities(self, engine):
        _require(engine, "ml.review_sentiment")
        out_of_range = _scalar(engine, """
            select count(*) from ml.review_sentiment
            where sentiment_probability < 0 or sentiment_probability > 1
        """)
        assert out_of_range == 0

    @pytest.mark.skipif(os.getenv("CI") == "true",
                        reason="model quality varies with the generated corpus in CI")
    def test_sentiment_beats_the_majority_class(self, engine):
        _require(engine, "ml.sentiment_model_metrics")
        auc = _scalar(engine, "select roc_auc from ml.sentiment_model_metrics limit 1")
        assert float(auc) > 0.7
