from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from dashboard.lib import charts, data, ui  # noqa: E402

ui.page_setup("Forecast", icon="🔮")
ui.page_header(
    "Revenue forecast",
    "Prophet, backtested against a seasonal-naive baseline on held-out data.",
    "What revenue should we expect next quarter?",
)

daily = data.load("forecast_daily")
monthly = data.load("forecast_monthly")
metrics = data.load("forecast_metrics")

if daily.empty:
    ui.empty_state("No forecast yet.", "Run `python -m ml.forecasting` or trigger the Airflow DAG.")
    st.stop()

daily["ds"] = pd.to_datetime(daily["ds"])
future = daily[daily["is_forecast"]]

tiles = st.columns(4)
tiles[0].metric("Forecast horizon", f"{len(future)} days")
tiles[1].metric("Projected revenue", ui.compact_brl(future["forecast_revenue"].sum()))
tiles[2].metric("80% interval",
                f"{ui.compact_brl(future['forecast_lower'].sum())} – "
                f"{ui.compact_brl(future['forecast_upper'].sum())}")
if not metrics.empty:
    prophet_row = metrics[metrics["model"] == "prophet"]
    if not prophet_row.empty:
        tiles[3].metric("Holdout MAPE", f"{prophet_row.iloc[0]['mape']:.1f}%",
                        help="Error on data the model never saw during training.")

st.divider()

ui.section("Actuals and forecast",
           "The shaded band is the 80% prediction interval. The dotted line marks "
           "where history ends and projection begins.")
ui.chart(charts.forecast_band(daily), height=420)

st.divider()

# ---------------------------------------------------------------- backtest --
if not metrics.empty:
    ui.section(
        "Backtest",
        "The model was refit on data up to the holdout window and scored on the "
        "unseen remainder, against a seasonal-naive baseline. A forecast without "
        "this comparison is decoration.",
    )
    left, right = st.columns([2, 3])
    with left:
        st.dataframe(
            metrics[["model", "holdout_days", "mape", "rmse", "mae", "bias"]].rename(
                columns={"model": "Model", "holdout_days": "Holdout days",
                         "mape": "MAPE %", "rmse": "RMSE", "mae": "MAE",
                         "bias": "Bias"}),
            use_container_width=True, hide_index=True,
            column_config={
                "MAPE %": st.column_config.NumberColumn(format="%.1f%%"),
                "RMSE": st.column_config.NumberColumn(format="%.0f"),
                "MAE": st.column_config.NumberColumn(format="%.0f"),
                "Bias": st.column_config.NumberColumn(format="%.0f"),
            },
        )
    with right:
        best = metrics.loc[metrics["rmse"].idxmin()]
        baseline = metrics[metrics["model"] == "seasonal_naive"]
        prophet = metrics[metrics["model"] == "prophet"]
        if not baseline.empty and not prophet.empty:
            improvement = (1 - prophet.iloc[0]["rmse"] / baseline.iloc[0]["rmse"]) * 100
            ui.finding(
                f"Prophet beats the naive baseline by {improvement:.0f}% on holdout RMSE.",
                f"Holdout MAPE is {prophet.iloc[0]['mape']:.1f}% against "
                f"{baseline.iloc[0]['mape']:.1f}% for seasonal-naive. Bias of "
                f"{prophet.iloc[0]['bias']:+,.0f} per day says the model is not "
                f"systematically over- or under-shooting. If the baseline had won, "
                f"the honest answer would have been to ship the baseline.",
            )
        else:
            st.info(f"Best model on holdout RMSE: **{best['model']}**.")

st.divider()

# ----------------------------------------------------------------- monthly --
if not monthly.empty:
    ui.section("Monthly view", "Projected months are flagged; partial months are marked.")
    display = monthly.copy()
    display["month"] = pd.to_datetime(display["month_start_date"]).dt.strftime("%Y-%m")
    st.dataframe(
        display[["month", "actual_revenue", "forecast_revenue", "forecast_lower",
                 "forecast_upper", "is_forecast_month"]].rename(columns={
                     "month": "Month", "actual_revenue": "Actual",
                     "forecast_revenue": "Forecast", "forecast_lower": "Lower 80%",
                     "forecast_upper": "Upper 80%", "is_forecast_month": "Projected"}),
        use_container_width=True, hide_index=True, height=420,
        column_config={
            "Actual": st.column_config.NumberColumn(format="R$ %.0f"),
            "Forecast": st.column_config.NumberColumn(format="R$ %.0f"),
            "Lower 80%": st.column_config.NumberColumn(format="R$ %.0f"),
            "Upper 80%": st.column_config.NumberColumn(format="R$ %.0f"),
            "Projected": st.column_config.CheckboxColumn(),
        },
    )

st.caption(
    "Caveat worth stating in any presentation of this chart: the Olist extract stops "
    "mid-collection, so the final weeks of history are partial. The pipeline trims "
    "those trailing low-volume days before fitting — leaving them in teaches the model "
    "a downtrend that is an artefact of the export, not the business."
)
