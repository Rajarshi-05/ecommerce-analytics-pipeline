from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st  # noqa: E402

from dashboard.lib import charts, data, ui  # noqa: E402

ui.page_setup("Revenue & Growth", icon="📈")
ui.page_header(
    "Revenue and growth",
    "Monthly and quarterly performance, growth rates, and where the revenue concentrates.",
    "What is the revenue trend and growth rate, and which categories and sellers drive it?",
)

monthly = data.load("revenue_monthly")
if monthly.empty:
    ui.empty_state("No revenue data.",
                   "Run the pipeline to populate `analytics.agg_revenue_monthly`.")
    st.stop()

# ---------------------------------------------------------------- controls --
years = sorted(monthly["year_number"].unique())
selected_years = st.multiselect("Filter by year", years, default=years,
                                help="Charts below respond to this filter.")
filtered = monthly[monthly["year_number"].isin(selected_years)] if selected_years else monthly

tiles = st.columns(4)
tiles[0].metric("Revenue in view", ui.compact_brl(filtered["revenue"].sum()))
tiles[1].metric("Orders in view", ui.compact(filtered["order_count"].sum()))
tiles[2].metric("Average order value", ui.brl(
    filtered["revenue"].sum() / max(filtered["order_count"].sum(), 1), 2))
tiles[3].metric("Best month", filtered.loc[filtered["revenue"].idxmax(), "year_month"]
                if not filtered.empty else "-")

st.divider()

# ------------------------------------------------------------------ trends --
ui.section("Monthly revenue")
ui.chart(charts.line_series(
    filtered, "month_start_date",
    [("revenue", "Revenue"), ("revenue_3m_moving_avg", "3-month average")],
    y_title="Revenue",
), height=360)

left, right = st.columns(2)
with left:
    ui.section("Month-over-month growth",
               "Blue is growth, red is contraction. Early months are volatile on a small base.")
    ui.chart(charts.diverging_bar(filtered, "year_month", "mom_growth_pct",
                                  y_title="MoM change"), height=320)
with right:
    ui.section("Cumulative revenue")
    figure = charts.line_series(filtered, "month_start_date",
                                [("cumulative_revenue", "Cumulative revenue")],
                                y_title="Cumulative revenue")
    figure.update_traces(fill="tozeroy", fillcolor="rgba(42,120,214,0.12)")
    ui.chart(figure, height=320)

# ------------------------------------------------------------- quarterly ---
ui.section("Quarterly summary")
quarterly = (filtered.groupby("year_quarter", as_index=False)
             .agg(revenue=("revenue", "sum"), orders=("order_count", "sum"),
                  customers=("active_customers", "sum"),
                  avg_order_value=("avg_order_value", "mean"),
                  avg_review=("avg_review_score", "mean")))
quarterly["qoq_growth_pct"] = (quarterly["revenue"].pct_change() * 100).round(1)
st.dataframe(
    quarterly.rename(columns={
        "year_quarter": "Quarter", "revenue": "Revenue", "orders": "Orders",
        "customers": "Active customers", "avg_order_value": "Avg order value",
        "avg_review": "Avg review", "qoq_growth_pct": "QoQ growth %"}),
    use_container_width=True, hide_index=True,
    column_config={
        "Revenue": st.column_config.NumberColumn(format="R$ %.0f"),
        "Avg order value": st.column_config.NumberColumn(format="R$ %.2f"),
        "Avg review": st.column_config.NumberColumn(format="%.2f"),
        "QoQ growth %": st.column_config.NumberColumn(format="%.1f%%"),
    },
)

st.divider()

# ---------------------------------------------------------------- category --
categories = data.load("category_performance")
if not categories.empty:
    ui.section("Category concentration",
               "Cumulative revenue share, ranked. The table gives the exact figures.")
    left, right = st.columns([3, 2])
    with left:
        ui.chart(charts.bar_ranked(categories, "product_category", "revenue", top_n=12),
                 height=440)
    with right:
        top_ten_share = categories.nlargest(10, "revenue")["revenue_share_pct"].sum()
        ui.finding(
            f"The top 10 categories carry {top_ten_share:.0f}% of revenue.",
            f"Across {len(categories)} categories, revenue is concentrated but not "
            f"extreme — no single category exceeds "
            f"{categories['revenue_share_pct'].max():.0f}%. That argues for "
            f"category-level merchandising rather than a single-category bet.",
        )
        st.dataframe(
            categories[["product_category", "revenue", "revenue_share_pct",
                        "avg_review_score"]].head(12).rename(columns={
                            "product_category": "Category", "revenue": "Revenue",
                            "revenue_share_pct": "Share %",
                            "avg_review_score": "Avg review"}),
            use_container_width=True, hide_index=True, height=300,
            column_config={
                "Revenue": st.column_config.NumberColumn(format="R$ %.0f"),
                "Share %": st.column_config.NumberColumn(format="%.1f%%"),
                "Avg review": st.column_config.NumberColumn(format="%.2f"),
            },
        )

# ------------------------------------------------------------------ seller --
sellers = data.load("seller_performance")
if not sellers.empty:
    ui.section("Top sellers",
               "Revenue alongside delivery quality — volume without reliability is a liability.")
    display = sellers.nlargest(20, "revenue")[[
        "seller_id", "seller_state", "revenue", "order_count",
        "avg_review_score", "late_delivery_pct", "is_at_risk_seller"]].copy()
    display["seller_id"] = display["seller_id"].str.slice(0, 10) + "…"
    st.dataframe(
        display.rename(columns={
            "seller_id": "Seller", "seller_state": "State", "revenue": "Revenue",
            "order_count": "Orders", "avg_review_score": "Avg review",
            "late_delivery_pct": "Late %", "is_at_risk_seller": "At risk"}),
        use_container_width=True, hide_index=True,
        column_config={
            "Revenue": st.column_config.NumberColumn(format="R$ %.0f"),
            "Avg review": st.column_config.NumberColumn(format="%.2f"),
            "Late %": st.column_config.NumberColumn(format="%.1f%%"),
            "At risk": st.column_config.CheckboxColumn(
                help="20+ orders and more than 15% late deliveries."),
        },
    )
    at_risk = int(sellers["is_at_risk_seller"].fillna(False).sum())
    if at_risk:
        ui.finding(
            f"{at_risk} sellers are flagged at risk.",
            "These carry meaningful volume (20+ orders) while missing the promised "
            "delivery date on more than 15% of them. They are the shortlist for "
            "an operational review.",
        )
