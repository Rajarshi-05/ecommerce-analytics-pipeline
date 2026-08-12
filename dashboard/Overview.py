"""Overview page and app entry point."""

from __future__ import annotations

import sys
from pathlib import Path

# Streamlit runs this file as a script, so the repo root is not importable by
# default. Prepending it lets the pages share dashboard.lib.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st  # noqa: E402

from dashboard.lib import charts, data, ui  # noqa: E402

ui.page_setup("Overview", icon="📦")

with st.sidebar:
    st.markdown("### Olist E-Commerce Analytics")
    st.caption(
        "End-to-end pipeline: Kaggle CSVs → Postgres → dbt star schema → "
        "ML → this dashboard, orchestrated by Airflow."
    )
    st.divider()
    st.caption(data.freshness_caption())
    # Query results are cached for 10 minutes. After a pipeline run finishes,
    # this is how you see the new numbers without restarting the app.
    if st.button("Refresh data", use_container_width=True):
        st.cache_data.clear()
        st.cache_resource.clear()
        st.rerun()

ui.page_header(
    "Marketplace overview",
    "~100k Brazilian marketplace orders, 2016-2018. Every number here is "
    "computed by a tested dbt model, not by this app.",
)

kpi = data.kpis()
if kpi.empty:
    ui.empty_state(
        "No data yet.",
        "Run `make pipeline` (or trigger the Airflow DAG) to load the warehouse, "
        "then refresh this page.",
    )
    st.stop()

# ------------------------------------------------------------------- tiles --
row_one = st.columns(4)
row_one[0].metric("Revenue", ui.compact_brl(kpi["total_revenue"]),
                  help="Item value plus freight, excluding cancelled orders.")
row_one[1].metric("Orders", ui.compact(kpi["total_orders"]))
row_one[2].metric("Customers", ui.compact(kpi["total_customers"]),
                  help="Distinct people, resolved via customer_unique_id.")
row_one[3].metric("Average order value", ui.brl(kpi["avg_order_value"], 2))

row_two = st.columns(4)
row_two[0].metric("On-time delivery", ui.pct(kpi["on_time_delivery_pct"]))
row_two[1].metric("Average review", f"{kpi['avg_review_score']:.2f} / 5")
row_two[2].metric("Repeat customers", ui.pct(kpi["repeat_customer_pct"]),
                  help="Share of customers with more than one order.")
row_two[3].metric("Avg delivery time", f"{kpi['avg_delivery_days']:.1f} days")

st.caption(
    f"Coverage: {kpi['first_order_date']} to {kpi['last_order_date']} · "
    f"{ui.compact(kpi['total_products'])} products · "
    f"{ui.compact(kpi['total_sellers'])} sellers · "
    f"{ui.compact(kpi['canceled_orders'])} cancelled orders excluded"
)
st.divider()

# ----------------------------------------------------------------- revenue --
monthly = data.load("revenue_monthly")
if not monthly.empty:
    ui.section("Revenue trend",
               "Monthly revenue with a 3-month moving average to damp the seasonal spikes.")
    figure = charts.line_series(
        monthly, "month_start_date",
        [("revenue", "Monthly revenue"), ("revenue_3m_moving_avg", "3-month average")],
        y_title="Revenue",
    )
    ui.chart(figure, height=360)

    peak = monthly.loc[monthly["revenue"].idxmax()]
    recent = monthly.tail(6)["mom_growth_pct"].mean()
    ui.finding(
        f"Peak month was {peak['year_month']} at {ui.compact_brl(peak['revenue'])}.",
        f"Average month-over-month growth across the last six months is "
        f"{recent:+.1f}%. The trend is dominated by the marketplace's expansion "
        f"phase rather than by seasonality — see the Revenue page for the split.",
    )

# --------------------------------------------------------------- two-panel --
left, right = st.columns(2)

with left:
    categories = data.load("category_performance")
    if not categories.empty:
        ui.section("Top categories by revenue")
        ui.chart(charts.bar_ranked(categories, "product_category", "revenue", top_n=10),
                 height=400)

with right:
    states = data.load("geographic_revenue")
    if not states.empty:
        ui.section("Top states by revenue")
        ui.chart(charts.bar_ranked(states, "state", "revenue", top_n=10,
                                   color=ui.CATEGORICAL[1]), height=400)

st.divider()

# ------------------------------------------------------------ the headline --
correlation = data.load("delivery_review")
if not correlation.empty:
    ui.section("The headline finding", "Review score against delivery lateness.")
    buckets = correlation[correlation["lateness_bucket"] != "ALL DELIVERED"]
    overall = correlation[correlation["lateness_bucket"] == "ALL DELIVERED"]

    figure = charts.bar_ranked(
        buckets.assign(order=range(len(buckets))), "lateness_bucket",
        "avg_review_score", top_n=len(buckets), currency=False,
        color=ui.CATEGORICAL[1],
    )
    figure.update_layout(xaxis=dict(title="Average review score", range=[0, 5.4],
                                    tickprefix=""))
    ui.chart(figure, height=340)

    if not overall.empty:
        coefficient = overall.iloc[0]["correlation_coefficient"]
        on_time = buckets[buckets["lateness_bucket"].str.contains("early|promise")]
        late = buckets[buckets["lateness_bucket"].str.contains("late")]
        if not on_time.empty and not late.empty:
            gap = on_time["avg_review_score"].mean() - late["avg_review_score"].mean()
            ui.finding(
                f"Late delivery costs about {gap:.1f} stars.",
                f"Orders delivered before the promise date average "
                f"{on_time['avg_review_score'].mean():.2f}/5; late ones average "
                f"{late['avg_review_score'].mean():.2f}/5. Pearson correlation between "
                f"days-late and review score is {coefficient:.3f}. Delivery reliability, "
                f"not product quality, is the dominant driver of satisfaction here.",
            )

st.divider()
st.caption(
    "Built with Python · PostgreSQL · dbt · Airflow · scikit-learn · Prophet · Streamlit. "
    "Source: Brazilian E-Commerce Public Dataset by Olist."
)
