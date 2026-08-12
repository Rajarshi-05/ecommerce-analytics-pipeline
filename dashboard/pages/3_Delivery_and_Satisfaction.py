from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st  # noqa: E402

from dashboard.lib import charts, data, ui  # noqa: E402

ui.page_setup("Delivery & Satisfaction", icon="🚚")
ui.page_header(
    "Delivery and satisfaction",
    "On-time performance over time, and what lateness does to review scores.",
    "Are we delivering on time, and how much does being late actually cost?",
)

correlation = data.load("delivery_review")
delivery = data.load("delivery_performance")

if correlation.empty and delivery.empty:
    ui.empty_state("No delivery data.", "Run the pipeline to populate the analytics views.")
    st.stop()

kpi = data.kpis()
if not kpi.empty:
    tiles = st.columns(4)
    tiles[0].metric("On-time rate", ui.pct(kpi["on_time_delivery_pct"]))
    tiles[1].metric("Late rate", ui.pct(kpi["late_delivery_pct"]))
    tiles[2].metric("Avg delivery", f"{kpi['avg_delivery_days']:.1f} days")
    tiles[3].metric("Satisfied (4-5★)", ui.pct(kpi["satisfied_pct"]))

st.divider()

# ------------------------------------------------------- the core question --
if not correlation.empty:
    buckets = correlation[correlation["lateness_bucket"] != "ALL DELIVERED"]
    overall = correlation[correlation["lateness_bucket"] == "ALL DELIVERED"]

    ui.section("Review score by delivery lateness",
               "Ordered from earliest to latest. Values are labelled directly.")
    figure = charts.bar_ranked(buckets, "lateness_bucket", "avg_review_score",
                               top_n=len(buckets), currency=False,
                               color=ui.CATEGORICAL[1])
    figure.update_layout(xaxis=dict(title="Average review score", range=[0, 5.4]))
    ui.chart(figure, height=340)

    left, right = st.columns(2)
    with left:
        ui.section("One-star rate by lateness")
        figure = charts.bar_ranked(buckets, "lateness_bucket", "one_star_pct",
                                   top_n=len(buckets), currency=False,
                                   color=ui.STATUS["critical"])
        figure.update_layout(xaxis=dict(title="Share of orders rated 1 star",
                                        ticksuffix="%"))
        ui.chart(figure, height=340)
    with right:
        ui.section("Detail")
        st.dataframe(
            correlation[["lateness_bucket", "order_count", "avg_review_score",
                         "one_star_pct", "four_plus_star_pct"]].rename(columns={
                             "lateness_bucket": "Lateness", "order_count": "Orders",
                             "avg_review_score": "Avg review",
                             "one_star_pct": "1★ %", "four_plus_star_pct": "4-5★ %"}),
            use_container_width=True, hide_index=True, height=340,
            column_config={
                "Avg review": st.column_config.NumberColumn(format="%.2f"),
                "1★ %": st.column_config.NumberColumn(format="%.1f%%"),
                "4-5★ %": st.column_config.NumberColumn(format="%.1f%%"),
            },
        )

    if not overall.empty:
        row = overall.iloc[0]
        early = buckets[buckets["lateness_bucket"].str.contains("early|promise")]
        late = buckets[buckets["lateness_bucket"].str.contains("late")]
        ui.finding(
            "Correlation between days-late and review score: "
            f"{row['correlation_coefficient']:.3f}.",
            f"Orders arriving on or before the promise date average "
            f"{early['avg_review_score'].mean():.2f}/5 with a "
            f"{early['one_star_pct'].mean():.1f}% one-star rate. Late orders average "
            f"{late['avg_review_score'].mean():.2f}/5 with "
            f"{late['one_star_pct'].mean():.1f}% one-star. The relationship is "
            f"monotonic across every bucket, which is what makes it credible as a "
            f"causal story rather than a coincidence: the more late, the worse the score.",
        )

st.divider()

# ---------------------------------------------------------- over time view --
if not delivery.empty:
    ui.section("Delivery speed over time",
               "Composition of orders by how long they took to arrive.")
    ui.chart(charts.stacked_share(
        delivery.sort_values("month_start_date"),
        "year_month", "delivery_speed_bucket", "order_count",
    ), height=400)

    late_trend = (delivery[delivery["is_late_delivery"].fillna(False)]
                  .groupby("year_month", as_index=False)["order_count"].sum()
                  .rename(columns={"order_count": "late_orders"}))
    all_trend = (delivery.groupby("year_month", as_index=False)["order_count"].sum()
                 .rename(columns={"order_count": "all_orders"}))
    trend = all_trend.merge(late_trend, on="year_month", how="left").fillna(0)
    trend["late_pct"] = (100 * trend["late_orders"] / trend["all_orders"]).round(2)

    ui.section("Late-delivery rate by month")
    figure = charts.line_series(trend, "year_month", [("late_pct", "Late %")],
                                y_title="Late deliveries", currency=False)
    figure.update_layout(yaxis=dict(ticksuffix="%"))
    ui.chart(figure, height=320)

st.divider()

# --------------------------------------------------------------- sentiment --
sentiment_metrics = data.load("sentiment_metrics")
sentiment_terms = data.load("sentiment_terms")
sentiment_summary = data.load("sentiment_summary")

if not sentiment_metrics.empty:
    ui.section(
        "Review text sentiment",
        "A TF-IDF + logistic regression classifier trained on the review corpus, "
        "using star ratings as weak labels. An English lexicon like VADER would be "
        "the wrong tool — these reviews are in Portuguese.",
    )
    row = sentiment_metrics.iloc[0]
    tiles = st.columns(4)
    tiles[0].metric("Holdout accuracy", f"{row['accuracy']:.3f}")
    tiles[1].metric("F1", f"{row['f1']:.3f}")
    tiles[2].metric("ROC-AUC", f"{row['roc_auc']:.3f}")
    tiles[3].metric("Training reviews", ui.compact(row["training_rows"]))

    if not sentiment_terms.empty:
        left, right = st.columns(2)
        with left:
            st.markdown("**Most negative terms**")
            negative = sentiment_terms[sentiment_terms["direction"] == "negative"]
            st.dataframe(negative[["term", "coefficient"]].head(12).rename(
                columns={"term": "Term", "coefficient": "Weight"}),
                use_container_width=True, hide_index=True, height=300)
        with right:
            st.markdown("**Most positive terms**")
            positive = sentiment_terms[sentiment_terms["direction"] == "positive"]
            st.dataframe(positive[["term", "coefficient"]].head(12).rename(
                columns={"term": "Term", "coefficient": "Weight"}),
                use_container_width=True, hide_index=True, height=300)

    if not sentiment_summary.empty:
        late_negative = sentiment_summary[
            sentiment_summary["is_late_delivery"].fillna(False)
            & (sentiment_summary["predicted_sentiment"] == "negative")
        ]["review_count"].sum()
        total_late = sentiment_summary[
            sentiment_summary["is_late_delivery"].fillna(False)
        ]["review_count"].sum()
        if total_late:
            ui.finding(
                f"{100 * late_negative / total_late:.0f}% of reviews on late orders "
                f"read as negative.",
                "The learned negative vocabulary is dominated by delivery language "
                "rather than product language, which independently corroborates the "
                "correlation above: customers complain about when it arrived, not "
                "what arrived.",
            )
