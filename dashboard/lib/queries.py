"""Single registry of everything the dashboard reads.

Both consumers use this module: `scripts/export_snapshot.py` to write the
Parquet snapshot, and `dashboard/lib/data.py` to read either backend. Keeping
one definition is what guarantees the deployed app and the local app show the
same numbers - if the two lists drifted, the snapshot would silently serve
stale or differently-shaped data.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Dataset:
    name: str
    relation: str | None = None
    query: str | None = None
    gated_on: str = ""
    row_limit: int | None = None
    required: bool = True
    description: str = ""

    def sql(self) -> str:
        if self.query:
            return self.query
        statement = f"select * from {self.relation}"
        if self.row_limit:
            statement += f" limit {self.row_limit}"
        return statement

    @property
    def source_relation(self) -> str:
        """The relation whose existence gates this dataset."""
        return self.relation or self.gated_on


# Customer-level and item-level tables are deliberately absent. They are large,
# no view needs them at row grain, and publishing per-customer rows to a public
# host would be the wrong default.
DATASETS: tuple[Dataset, ...] = (
    Dataset("kpi_summary", relation="analytics.agg_kpi_summary",
            description="Headline KPI tiles."),
    Dataset("revenue_monthly", relation="analytics.agg_revenue_monthly",
            description="Monthly revenue with MoM/YoY growth."),
    Dataset("category_performance", relation="analytics.agg_category_performance",
            description="Category league table."),
    Dataset("seller_performance", relation="analytics.agg_seller_performance",
            row_limit=500, description="Top 500 sellers by revenue."),
    Dataset("delivery_performance", relation="analytics.agg_delivery_performance",
            description="Delivery-speed distribution per month."),
    Dataset("delivery_review", relation="analytics.agg_delivery_review_correlation",
            description="Review score by how late the order was."),
    Dataset("cohort_retention", relation="analytics.agg_cohort_retention",
            description="Retention triangle by acquisition month."),
    Dataset("geographic_revenue", relation="analytics.agg_geographic_revenue",
            description="Revenue and freight burden by state."),

    Dataset("segment_profiles", relation="ml.segment_profiles", required=False,
            description="KMeans cluster centroids."),
    Dataset("segment_metrics", relation="ml.segment_model_metrics", required=False,
            description="Silhouette sweep across candidate k."),
    Dataset("forecast_daily", relation="ml.revenue_forecast_daily", required=False,
            description="Daily actuals and forecast with prediction interval."),
    Dataset("forecast_monthly", relation="ml.revenue_forecast_monthly", required=False,
            description="Monthly roll-up of the forecast."),
    Dataset("forecast_metrics", relation="ml.forecast_model_metrics", required=False,
            description="Backtest: Prophet versus seasonal-naive."),
    Dataset("sentiment_metrics", relation="ml.sentiment_model_metrics", required=False,
            description="Holdout metrics for the review classifier."),
    Dataset("sentiment_terms", relation="ml.sentiment_top_terms", required=False,
            description="Most predictive positive and negative terms."),

    Dataset(
        "rfm_segments",
        gated_on="analytics.agg_customer_rfm",
        query="""
            select
                rfm_segment,
                lifecycle_stage,
                count(*)                          as customer_count,
                round(avg(recency_days))          as avg_recency_days,
                round(avg(frequency), 2)          as avg_frequency,
                round(avg(monetary), 2)           as avg_monetary,
                round(sum(monetary), 2)           as total_monetary,
                round(avg(avg_review_score), 2)   as avg_review_score
            from analytics.agg_customer_rfm
            group by rfm_segment, lifecycle_stage
            order by total_monetary desc
        """,
        description="RFM segments aggregated - never exported at customer grain.",
    ),
    Dataset(
        "sentiment_summary",
        gated_on="ml.review_sentiment",
        required=False,
        query="""
            select
                predicted_sentiment,
                rating_sentiment,
                is_late_delivery,
                count(*)                                       as review_count,
                round(avg(sentiment_probability)::numeric, 4)  as avg_probability,
                round(avg(review_score), 2)                    as avg_review_score
            from ml.review_sentiment
            group by predicted_sentiment, rating_sentiment, is_late_delivery
        """,
        description="Sentiment agreement with star ratings, split by lateness.",
    ),
)

DATASETS_BY_NAME: dict[str, Dataset] = {d.name: d for d in DATASETS}


def get_dataset(name: str) -> Dataset:
    try:
        return DATASETS_BY_NAME[name]
    except KeyError:
        known = ", ".join(sorted(DATASETS_BY_NAME))
        raise KeyError(f"Unknown dataset '{name}'. Available: {known}") from None
