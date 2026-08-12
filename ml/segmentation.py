"""KMeans customer segmentation on top of the RFM mart.

The dbt model `agg_customer_rfm` already produces a rules-based segmentation.
This module answers a different question: if we let the data choose the
boundaries instead of imposing quintiles, do we get segments a marketing team
could actually act on?

Design notes worth being able to defend:

* RFM values are heavily skewed (monetary is long-tailed, frequency is almost
  always 1). Log1p before scaling, or KMeans will just isolate the outliers.
* k is chosen by silhouette score over a candidate range rather than fixed, and
  the full sweep is written to `ml.segment_model_metrics` so the choice is
  auditable instead of asserted.
* Clusters are labelled by comparing each centroid against the population mean,
  so the names stay correct even if the cluster ordering changes between runs.
"""

from __future__ import annotations

import argparse
import logging
import sys

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import calinski_harabasz_score, davies_bouldin_score, silhouette_score
from sklearn.preprocessing import StandardScaler

from ml.common import configure_logging, read_sql, write_table

log = logging.getLogger(__name__)

FEATURES = ["recency_days", "frequency", "monetary", "avg_order_value"]
SILHOUETTE_SAMPLE = 10_000  # silhouette is O(n^2); sample above this size

RFM_QUERY = """
    select
        customer_key,
        customer_state,
        acquisition_cohort_month,
        recency_days,
        frequency,
        monetary,
        avg_order_value,
        total_items,
        avg_review_score,
        rfm_score,
        rfm_segment
    from analytics.agg_customer_rfm
"""


def _prepare_features(frame: pd.DataFrame) -> np.ndarray:
    # log1p tames the monetary tail so the clusters describe the bulk of the
    # customer base rather than carving off the top 0.1% of spenders.
    transformed = np.column_stack([
        np.log1p(frame["recency_days"].clip(lower=0)),
        np.log1p(frame["frequency"]),
        np.log1p(frame["monetary"].clip(lower=0)),
        np.log1p(frame["avg_order_value"].clip(lower=0)),
    ])
    return StandardScaler().fit_transform(transformed)


def _evaluate_k(matrix: np.ndarray, k_range: range, seed: int) -> pd.DataFrame:
    sample_idx = None
    if len(matrix) > SILHOUETTE_SAMPLE:
        rng = np.random.default_rng(seed)
        sample_idx = rng.choice(len(matrix), SILHOUETTE_SAMPLE, replace=False)

    rows = []
    for k in k_range:
        model = KMeans(n_clusters=k, random_state=seed, n_init=10)
        labels = model.fit_predict(matrix)

        scored_matrix = matrix if sample_idx is None else matrix[sample_idx]
        scored_labels = labels if sample_idx is None else labels[sample_idx]

        rows.append({
            "k": k,
            "inertia": float(model.inertia_),
            "silhouette": float(silhouette_score(scored_matrix, scored_labels)),
            "davies_bouldin": float(davies_bouldin_score(scored_matrix, scored_labels)),
            "calinski_harabasz": float(calinski_harabasz_score(scored_matrix, scored_labels)),
        })
        log.info("k=%d  inertia=%.1f  silhouette=%.4f", k, rows[-1]["inertia"],
                 rows[-1]["silhouette"])
    return pd.DataFrame(rows)


REPEAT_THRESHOLD = 1.5


def _label_clusters(profile: pd.DataFrame) -> dict[int, str]:
    """Name clusters from where their centroid sits *relative to the others*.

    KMeans cluster ids are arbitrary and reshuffle between runs, so the label
    has to be derived from the profile or the dashboard's segment names would
    change meaning on every rebuild.

    Ranking rather than absolute thresholds is what keeps this stable: a
    threshold tuned to one dataset breaks the moment the data shifts, whereas
    "this cluster is the most recent of the five" stays true and stays
    interpretable.
    """
    count = len(profile)
    # Ascending recency rank: position 0 is the most recently active cluster.
    recency_position = profile["avg_recency_days"].rank(method="first").sub(1) / count
    # Descending monetary rank: position 0 is the highest-value cluster.
    monetary_position = profile["avg_monetary"].rank(method="first", ascending=False).sub(1) / count

    def tier(position: float, names: tuple[str, str, str]) -> str:
        if position < 1 / 3:
            return names[0]
        return names[1] if position < 2 / 3 else names[2]

    labels: dict[int, str] = {}
    for cluster in profile.index:
        parts = [
            tier(recency_position[cluster], ("Active", "Cooling", "Dormant")),
            tier(monetary_position[cluster], ("High-Value", "Mid-Value", "Low-Value")),
        ]
        if profile.at[cluster, "avg_frequency"] >= REPEAT_THRESHOLD:
            parts.append("Repeaters")
        name = " ".join(parts)

        # Two centroids can land in the same tier pair at high k. Disambiguate
        # with the recency ordering rather than a meaningless numeric suffix.
        if name in labels.values():
            name = f"{name} (recency rank {int(recency_position[cluster] * count) + 1})"
        labels[cluster] = name
    return labels


def run(k_min: int = 3, k_max: int = 8, seed: int = 42,
        run_id: str | None = None) -> dict[str, object]:
    frame = read_sql(RFM_QUERY)
    if frame.empty:
        raise RuntimeError("analytics.agg_customer_rfm is empty - run dbt build first.")
    log.info("Clustering %d customers on %s", len(frame), ", ".join(FEATURES))

    matrix = _prepare_features(frame)
    metrics = _evaluate_k(matrix, range(k_min, k_max + 1), seed)

    best_k = int(metrics.loc[metrics["silhouette"].idxmax(), "k"])
    log.info("Selected k=%d by silhouette score.", best_k)

    model = KMeans(n_clusters=best_k, random_state=seed, n_init=10)
    frame["cluster_id"] = model.fit_predict(matrix)

    profile = frame.groupby("cluster_id").agg(
        customer_count=("customer_key", "size"),
        avg_recency_days=("recency_days", "mean"),
        avg_frequency=("frequency", "mean"),
        avg_monetary=("monetary", "mean"),
        avg_order_value=("avg_order_value", "mean"),
        avg_review_score=("avg_review_score", "mean"),
        total_revenue=("monetary", "sum"),
    ).round(2)

    labels = _label_clusters(profile)
    frame["cluster_label"] = frame["cluster_id"].map(labels)

    profile = profile.reset_index()
    profile["cluster_label"] = profile["cluster_id"].map(labels)
    profile["revenue_share_pct"] = (
        100 * profile["total_revenue"] / profile["total_revenue"].sum()).round(2)
    profile["customer_share_pct"] = (
        100 * profile["customer_count"] / profile["customer_count"].sum()).round(2)
    profile["selected_k"] = best_k

    metrics["selected"] = metrics["k"] == best_k

    write_table(frame[[
        "customer_key", "customer_state", "acquisition_cohort_month",
        "recency_days", "frequency", "monetary", "avg_order_value",
        "rfm_score", "rfm_segment", "cluster_id", "cluster_label",
    ]], "customer_segments", run_id=run_id)
    write_table(profile, "segment_profiles", run_id=run_id)
    write_table(metrics, "segment_model_metrics", run_id=run_id)

    log.info("\n%s", profile[[
        "cluster_label", "customer_count", "avg_recency_days",
        "avg_frequency", "avg_monetary", "revenue_share_pct",
    ]].to_string(index=False))

    return {
        "customers_scored": int(len(frame)),
        "selected_k": best_k,
        "silhouette": float(metrics.loc[metrics["selected"], "silhouette"].iloc[0]),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--k-min", type=int, default=3)
    parser.add_argument("--k-max", type=int, default=8)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    configure_logging(args.verbose)
    summary = run(k_min=args.k_min, k_max=args.k_max, seed=args.seed, run_id=args.run_id)
    log.info("Segmentation complete: %s", summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
