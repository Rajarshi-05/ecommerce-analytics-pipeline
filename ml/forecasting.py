"""Revenue forecasting with Prophet, plus an honest baseline to beat.

Two things make this more than a Prophet tutorial:

* **A holdout.** The last `--holdout-months` of history are withheld, the model
  is fit on the rest, and MAPE/RMSE are reported on data the model never saw.
  A forecast without a backtest is decoration.
* **A baseline.** A seasonal-naive forecast (this month = same month last year,
  falling back to last month) is scored on the same holdout. If Prophet cannot
  beat it, that is the finding, and it is recorded rather than hidden.

The series is daily revenue aggregated from fact_orders. Olist's history ends
abruptly in the last weeks of the extract, so the final partial period is
trimmed before fitting - leaving it in drags the trend down and produces a
forecast that is confidently wrong.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import timedelta

import numpy as np
import pandas as pd

from ml.common import configure_logging, read_sql, write_table

log = logging.getLogger(__name__)

DAILY_REVENUE_QUERY = """
    select
        order_purchase_date            as ds,
        sum(order_total)::float        as y,
        count(*)                       as order_count
    from marts.fact_orders
    where order_status not in ('canceled', 'unavailable')
    group by order_purchase_date
    order by order_purchase_date
"""


def _trim_tail(frame: pd.DataFrame, quantile: float = 0.25) -> pd.DataFrame:
    """Drop trailing days whose volume collapses relative to recent history.

    The Olist extract stops mid-collection, so the last stretch of days has
    partial data. Fitting on it teaches the model a downtrend that is an
    artefact of the export, not the business.
    """
    if len(frame) < 60:
        return frame

    typical = frame["order_count"].tail(90).median()
    threshold = typical * quantile

    cutoff = len(frame)
    for i in range(len(frame) - 1, max(len(frame) - 45, 0) - 1, -1):
        if frame.iloc[i]["order_count"] >= threshold:
            break
        cutoff = i

    if cutoff < len(frame):
        dropped = len(frame) - cutoff
        log.info("Trimmed %d trailing low-volume day(s) from %s onward.",
                 dropped, frame.iloc[cutoff]["ds"].date())
    return frame.iloc[:cutoff].reset_index(drop=True)


def _metrics(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    error = predicted - actual
    non_zero = actual != 0
    return {
        "mae": float(np.mean(np.abs(error))),
        "rmse": float(np.sqrt(np.mean(error**2))),
        "mape": float(np.mean(np.abs(error[non_zero] / actual[non_zero])) * 100)
        if non_zero.any() else float("nan"),
        "bias": float(np.mean(error)),
    }


def _seasonal_naive(history: pd.DataFrame, horizon_index: pd.DatetimeIndex) -> np.ndarray:
    """Same day last year where available, otherwise the last 28-day mean."""
    lookup = history.set_index("ds")["y"]
    fallback = float(history["y"].tail(28).mean())
    return np.array([
        float(lookup.get(day - pd.Timedelta(days=364), fallback))
        for day in horizon_index
    ])


def _fit_prophet(train: pd.DataFrame, seed: int):
    from prophet import Prophet

    model = Prophet(
        yearly_seasonality=False,   # <2 years of usable history; would overfit
        weekly_seasonality=True,
        daily_seasonality=False,
        seasonality_mode="multiplicative",
        changepoint_prior_scale=0.05,
        interval_width=0.80,
    )
    model.add_seasonality(name="monthly", period=30.5, fourier_order=5)
    model.fit(train)
    return model


def run(horizon_days: int = 90, holdout_months: int = 3, seed: int = 42,
        run_id: str | None = None) -> dict[str, object]:
    daily = read_sql(DAILY_REVENUE_QUERY)
    if daily.empty:
        raise RuntimeError("marts.fact_orders is empty - run dbt build first.")

    daily["ds"] = pd.to_datetime(daily["ds"])
    daily = _trim_tail(daily)

    # Reindex to a complete daily calendar; genuinely zero-revenue days are
    # information the model should see, not gaps it should interpolate over.
    full_index = pd.date_range(daily["ds"].min(), daily["ds"].max(), freq="D")
    daily = (daily.set_index("ds").reindex(full_index)
             .rename_axis("ds").reset_index())
    daily[["y", "order_count"]] = daily[["y", "order_count"]].fillna(0.0)

    log.info("Series: %s to %s (%d days, total revenue %.0f)",
             daily["ds"].min().date(), daily["ds"].max().date(),
             len(daily), daily["y"].sum())

    # ---------------------------------------------------------- backtest --
    holdout_days = holdout_months * 30
    split_at = daily["ds"].max() - timedelta(days=holdout_days)
    train = daily[daily["ds"] <= split_at].copy()
    test = daily[daily["ds"] > split_at].copy()

    evaluation = []
    if len(test) >= 14 and len(train) >= 180:
        log.info("Backtest: train %d days, holdout %d days.", len(train), len(test))
        backtest_model = _fit_prophet(train[["ds", "y"]], seed)
        backtest_pred = backtest_model.predict(test[["ds"]])["yhat"].to_numpy()

        prophet_metrics = _metrics(test["y"].to_numpy(), backtest_pred)
        naive_metrics = _metrics(test["y"].to_numpy(),
                                 _seasonal_naive(train, pd.DatetimeIndex(test["ds"])))

        for name, values in (("prophet", prophet_metrics), ("seasonal_naive", naive_metrics)):
            evaluation.append({"model": name, "holdout_days": len(test), **values})
            log.info("%-15s MAPE=%.1f%%  RMSE=%.0f  MAE=%.0f",
                     name, values["mape"], values["rmse"], values["mae"])

        winner = min(evaluation, key=lambda r: r["rmse"])["model"]
        log.info("Best on holdout RMSE: %s", winner)
    else:
        log.warning("History too short for a meaningful backtest - skipping.")

    # ---------------------------------------------------------- forecast --
    model = _fit_prophet(daily[["ds", "y"]], seed)
    future = model.make_future_dataframe(periods=horizon_days, freq="D")
    forecast = model.predict(future)

    daily_forecast = forecast[["ds", "yhat", "yhat_lower", "yhat_upper",
                               "trend", "weekly"]].copy()
    daily_forecast = daily_forecast.merge(daily[["ds", "y"]], on="ds", how="left")
    daily_forecast = daily_forecast.rename(columns={"y": "actual_revenue",
                                                    "yhat": "forecast_revenue",
                                                    "yhat_lower": "forecast_lower",
                                                    "yhat_upper": "forecast_upper"})
    daily_forecast["is_forecast"] = daily_forecast["actual_revenue"].isna()
    for column in ("forecast_revenue", "forecast_lower", "forecast_upper"):
        daily_forecast[column] = daily_forecast[column].clip(lower=0).round(2)

    monthly = daily_forecast.assign(
        month_start_date=daily_forecast["ds"].dt.to_period("M").dt.to_timestamp()
    ).groupby("month_start_date").agg(
        forecast_revenue=("forecast_revenue", "sum"),
        forecast_lower=("forecast_lower", "sum"),
        forecast_upper=("forecast_upper", "sum"),
        actual_revenue=("actual_revenue", "sum"),
        days_in_month=("ds", "count"),
        forecast_days=("is_forecast", "sum"),
    ).round(2).reset_index()
    monthly["is_forecast_month"] = monthly["forecast_days"] > 0

    horizon_total = float(
        daily_forecast.loc[daily_forecast["is_forecast"], "forecast_revenue"].sum())
    log.info("Forecast for the next %d days: %.0f (80%% CI %.0f - %.0f)",
             horizon_days, horizon_total,
             daily_forecast.loc[daily_forecast["is_forecast"], "forecast_lower"].sum(),
             daily_forecast.loc[daily_forecast["is_forecast"], "forecast_upper"].sum())

    write_table(daily_forecast, "revenue_forecast_daily", run_id=run_id)
    write_table(monthly, "revenue_forecast_monthly", run_id=run_id)
    if evaluation:
        write_table(pd.DataFrame(evaluation), "forecast_model_metrics", run_id=run_id)

    return {
        "history_days": int(len(daily)),
        "horizon_days": horizon_days,
        "forecast_total": round(horizon_total, 2),
        "evaluation": evaluation,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--horizon-days", type=int, default=90,
                        help="Days to forecast ahead (default 90 = one quarter).")
    parser.add_argument("--holdout-months", type=int, default=3)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    configure_logging(args.verbose)
    summary = run(horizon_days=args.horizon_days, holdout_months=args.holdout_months,
                  seed=args.seed, run_id=args.run_id)
    log.info("Forecast complete: %s", {k: v for k, v in summary.items() if k != "evaluation"})
    return 0


if __name__ == "__main__":
    sys.exit(main())
