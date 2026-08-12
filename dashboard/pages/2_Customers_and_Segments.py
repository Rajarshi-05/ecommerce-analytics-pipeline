from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st  # noqa: E402

from dashboard.lib import charts, data, ui  # noqa: E402

ui.page_setup("Customers & Segments", icon="👥")
ui.page_header(
    "Customers and segments",
    "Rules-based RFM alongside unsupervised clustering, plus cohort retention.",
    "Who are the valuable customers, and do they come back?",
)

segments = data.load("rfm_segments")
if segments.empty:
    ui.empty_state("No segmentation yet.",
                   "Run the pipeline to populate `analytics.agg_customer_rfm`.")
    st.stop()

total_customers = int(segments["customer_count"].sum())
total_value = float(segments["total_monetary"].sum())

tiles = st.columns(4)
tiles[0].metric("Customers segmented", ui.compact(total_customers))
tiles[1].metric("Lifetime value", ui.compact_brl(total_value))
active = segments[segments["lifecycle_stage"] == "Active"]["customer_count"].sum()
tiles[2].metric("Active", ui.pct(100 * active / max(total_customers, 1)),
                help="Customers in the top two recency quintiles.")
top_segment = segments.iloc[0]
tiles[3].metric("Largest value segment", top_segment["rfm_segment"])

st.divider()

# ---------------------------------------------------------------- RFM view --
ui.section("RFM segments",
           "Quintile scores on Recency, Frequency and Monetary value, mapped to "
           "named segments. Deterministic and directly actionable.")

left, right = st.columns([3, 2])
with left:
    ui.chart(charts.bar_ranked(segments, "rfm_segment", "total_monetary",
                               top_n=len(segments)), height=400)
with right:
    st.dataframe(
        segments[["rfm_segment", "customer_count", "avg_recency_days",
                  "avg_frequency", "avg_monetary"]].rename(columns={
                      "rfm_segment": "Segment", "customer_count": "Customers",
                      "avg_recency_days": "Avg recency (d)",
                      "avg_frequency": "Avg orders", "avg_monetary": "Avg value"}),
        use_container_width=True, hide_index=True, height=400,
        column_config={
            "Avg value": st.column_config.NumberColumn(format="R$ %.0f"),
            "Avg orders": st.column_config.NumberColumn(format="%.2f"),
            "Avg recency (d)": st.column_config.NumberColumn(format="%.0f"),
        },
    )

ui.section("Segment shape", "Recency against value; bubble size is population.")
ui.chart(charts.scatter_bubble(
    segments, "avg_recency_days", "avg_monetary", "customer_count", "rfm_segment",
    x_title="Average recency (days since last order)",
    y_title="Average lifetime value (R$)",
), height=420)

st.divider()

# ------------------------------------------------------------ ML clusters --
profiles = data.load("segment_profiles")
metrics = data.load("segment_metrics")
if not profiles.empty:
    ui.section(
        "KMeans clusters",
        "The unsupervised counterpart. Features are log-scaled RFM values; k is "
        "chosen by silhouette score rather than assumed.",
    )
    left, right = st.columns([3, 2])
    with left:
        st.dataframe(
            profiles[["cluster_label", "customer_count", "avg_recency_days",
                      "avg_frequency", "avg_monetary", "revenue_share_pct"]].rename(
                columns={"cluster_label": "Cluster", "customer_count": "Customers",
                         "avg_recency_days": "Avg recency (d)",
                         "avg_frequency": "Avg orders", "avg_monetary": "Avg value",
                         "revenue_share_pct": "Revenue share %"}),
            use_container_width=True, hide_index=True,
            column_config={
                "Avg value": st.column_config.NumberColumn(format="R$ %.0f"),
                "Avg orders": st.column_config.NumberColumn(format="%.2f"),
                "Avg recency (d)": st.column_config.NumberColumn(format="%.0f"),
                "Revenue share %": st.column_config.NumberColumn(format="%.1f%%"),
            },
        )
    with right:
        if not metrics.empty:
            figure = charts.line_series(metrics.sort_values("k"), "k",
                                        [("silhouette", "Silhouette score")],
                                        y_title="Silhouette", currency=False)
            figure.update_traces(mode="lines+markers", marker=dict(size=9))
            figure.update_layout(xaxis=dict(title="k (number of clusters)", dtick=1))
            ui.chart(figure, height=260)
            best = metrics.loc[metrics["silhouette"].idxmax()]
            st.caption(f"Selected k={int(best['k'])} (silhouette {best['silhouette']:.3f}).")

    top_cluster = profiles.nlargest(1, "revenue_share_pct").iloc[0]
    ui.finding(
        f"'{top_cluster['cluster_label']}' is {top_cluster['customer_share_pct']:.0f}% "
        f"of customers but {top_cluster['revenue_share_pct']:.0f}% of revenue.",
        "The clusters broadly agree with the rules-based RFM segments, which is the "
        "useful result: it means the quintile cut-offs are not arbitrary. Where they "
        "disagree is at the boundary between recent low-value and dormant high-value "
        "customers — worth a look before designing a win-back campaign.",
    )

st.divider()

# ----------------------------------------------------------------- cohorts --
cohorts = data.load("cohort_retention")
if not cohorts.empty:
    ui.section("Cohort retention",
               "Share of each acquisition month still ordering, by months elapsed.")
    trimmed = cohorts[cohorts["months_since_acquisition"] <= 12]
    ui.chart(charts.heatmap(trimmed, "months_since_acquisition", "cohort_label",
                            "retention_pct", colorbar_title="Retention %"), height=460)

    month_one = cohorts[cohorts["months_since_acquisition"] == 1]["retention_pct"].mean()
    ui.finding(
        f"Month-1 retention averages {month_one:.1f}%.",
        "This is a genuinely low repeat rate, and it is the most important thing the "
        "analysis says about the business: Olist behaves like a transactional "
        "marketplace, not a subscription. Spending on retention campaigns would be "
        "chasing a customer base that structurally does not return — the leverage is "
        "in acquisition efficiency and in first-order experience, which loops back to "
        "the delivery finding.",
    )
