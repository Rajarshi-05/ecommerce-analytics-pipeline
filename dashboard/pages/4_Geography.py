from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402

from dashboard.lib import charts, data, ui  # noqa: E402

ui.page_setup("Geography", icon="🗺️")
ui.page_header(
    "Geography",
    "Where the revenue comes from, and what distance costs in freight and delivery time.",
    "How does revenue distribute across states and regions?",
)

states = data.load("geographic_revenue")
if states.empty:
    ui.empty_state("No geographic data.",
                   "Run the pipeline to populate `analytics.agg_geographic_revenue`.")
    st.stop()

tiles = st.columns(4)
tiles[0].metric("States covered", len(states))
top = states.iloc[0]
tiles[1].metric(f"Largest market ({top['state']})", ui.pct(top["revenue_share_pct"]))
tiles[2].metric("Median freight share", ui.pct(states["freight_to_gmv_pct"].median()))
tiles[3].metric("Delivery spread",
                f"{states['avg_delivery_days'].min():.0f}–"
                f"{states['avg_delivery_days'].max():.0f} days")

st.divider()

left, right = st.columns(2)
with left:
    ui.section("Revenue by state")
    ui.chart(charts.bar_ranked(states, "state", "revenue", top_n=15), height=460)
with right:
    ui.section("Revenue by region")
    regions = (states.groupby("region", as_index=False)
               .agg(revenue=("revenue", "sum"), orders=("order_count", "sum"),
                    customers=("customer_count", "sum"),
                    avg_delivery_days=("avg_delivery_days", "mean"),
                    avg_review_score=("avg_review_score", "mean"),
                    freight_to_gmv_pct=("freight_to_gmv_pct", "mean")))
    ui.chart(charts.bar_ranked(regions, "region", "revenue", top_n=len(regions),
                               color=ui.CATEGORICAL[1]), height=280)
    st.dataframe(
        regions[["region", "revenue", "avg_delivery_days", "avg_review_score",
                 "freight_to_gmv_pct"]].sort_values("revenue", ascending=False).rename(
            columns={"region": "Region", "revenue": "Revenue",
                     "avg_delivery_days": "Avg days", "avg_review_score": "Avg review",
                     "freight_to_gmv_pct": "Freight % of GMV"}),
        use_container_width=True, hide_index=True,
        column_config={
            "Revenue": st.column_config.NumberColumn(format="R$ %.0f"),
            "Avg days": st.column_config.NumberColumn(format="%.1f"),
            "Avg review": st.column_config.NumberColumn(format="%.2f"),
            "Freight % of GMV": st.column_config.NumberColumn(format="%.1f%%"),
        },
    )

st.divider()

# ------------------------------------------------------------------- map ---
mappable = states.dropna(subset=["latitude", "longitude"])
if not mappable.empty:
    ui.section("Revenue map", "Bubble area is revenue; position is the state's customer centroid.")
    sizes = mappable["revenue"] / mappable["revenue"].max() * 55 + 8
    figure = go.Figure(go.Scattergeo(
        lon=mappable["longitude"], lat=mappable["latitude"],
        text=mappable["state"], mode="markers+text",
        textposition="top center",
        textfont=dict(size=10, color=ui.INK_MUTED),
        marker=dict(size=sizes, color=ui.CATEGORICAL[0], opacity=0.7,
                    line=dict(color=ui.SURFACE, width=2)),
        customdata=mappable[["revenue", "order_count", "avg_delivery_days"]],
        hovertemplate=("<b>%{text}</b><br>Revenue: R$ %{customdata[0]:,.0f}"
                       "<br>Orders: %{customdata[1]:,.0f}"
                       "<br>Avg delivery: %{customdata[2]:.1f} days<extra></extra>"),
    ))
    figure.update_geos(
        scope="south america", showcountries=True,
        countrycolor=ui.BASELINE, showland=True, landcolor="#f0efec",
        showocean=True, oceancolor=ui.SURFACE, showlakes=False,
        lataxis=dict(range=[-34, 6]), lonaxis=dict(range=[-75, -33]),
    )
    figure.update_layout(margin=dict(l=0, r=0, t=8, b=0))
    ui.chart(figure, height=520)

st.divider()

# ------------------------------------------------------ distance economics --
ui.section("What distance costs",
           "Freight as a share of goods value against average delivery time. "
           "Bubble size is revenue.")
ui.chart(charts.scatter_bubble(
    states, "avg_delivery_days", "freight_to_gmv_pct", "revenue", "state",
    x_title="Average delivery days", y_title="Freight as % of GMV",
), height=440)

southeast = states[states["region"] == "Southeast"]
north = states[states["region"].isin(["North", "Northeast"])]
if not southeast.empty and not north.empty:
    ui.finding(
        f"Northern states pay {north['freight_to_gmv_pct'].mean():.0f}% of goods value "
        f"in freight versus {southeast['freight_to_gmv_pct'].mean():.0f}% in the Southeast.",
        f"They also wait {north['avg_delivery_days'].mean():.0f} days on average against "
        f"{southeast['avg_delivery_days'].mean():.0f}, and score "
        f"{north['avg_review_score'].mean():.2f}/5 against "
        f"{southeast['avg_review_score'].mean():.2f}. Geography is the upstream cause of "
        f"the satisfaction gap: the same delivery problem, distributed unevenly. Regional "
        f"fulfilment capacity — not a nationwide discount — is the lever.",
    )

st.divider()
ui.section("State detail")
st.dataframe(
    states[["state", "region", "revenue", "order_count", "customer_count",
            "avg_order_value", "avg_delivery_days", "late_delivery_pct",
            "avg_review_score", "freight_to_gmv_pct"]].rename(columns={
                "state": "State", "region": "Region", "revenue": "Revenue",
                "order_count": "Orders", "customer_count": "Customers",
                "avg_order_value": "AOV", "avg_delivery_days": "Avg days",
                "late_delivery_pct": "Late %", "avg_review_score": "Avg review",
                "freight_to_gmv_pct": "Freight %"}),
    use_container_width=True, hide_index=True,
    column_config={
        "Revenue": st.column_config.NumberColumn(format="R$ %.0f"),
        "AOV": st.column_config.NumberColumn(format="R$ %.2f"),
        "Avg days": st.column_config.NumberColumn(format="%.1f"),
        "Late %": st.column_config.NumberColumn(format="%.1f%%"),
        "Avg review": st.column_config.NumberColumn(format="%.2f"),
        "Freight %": st.column_config.NumberColumn(format="%.1f%%"),
    },
)
