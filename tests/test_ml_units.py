"""Unit tests for the pure logic inside the model layer.

Model *training* is exercised by the pipeline itself; what is worth pinning
down here is the deterministic logic around it - text normalisation and cluster
labelling - because both are things a future change could silently break.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ml.segmentation import _label_clusters
from ml.sentiment import normalise


class TestNormalise:
    def test_strips_accents(self):
        # Portuguese reviewers write both forms; without folding they become
        # two unrelated features.
        assert normalise("não") == normalise("nao")
        assert normalise("péssimo") == "pessimo"

    def test_lowercases(self):
        assert normalise("PRODUTO Otimo") == "produto otimo"

    def test_removes_digits_and_punctuation(self):
        assert normalise("chegou em 3 dias!!! nota 10") == "chegou em dias nota"

    def test_removes_urls(self):
        assert "http" not in normalise("veja em http://exemplo.com.br agora")

    def test_collapses_whitespace(self):
        assert normalise("  muito    bom  ") == "muito bom"

    def test_handles_empty_and_non_string_input(self):
        assert normalise("") == ""
        assert normalise("!!!") == ""
        assert normalise(123) == ""


class TestClusterLabels:
    @staticmethod
    def _profile(rows: list[dict]) -> pd.DataFrame:
        return pd.DataFrame(rows, index=pd.Index(range(len(rows)), name="cluster_id"))

    def test_labels_are_unique(self):
        profile = self._profile([
            {"avg_recency_days": 20, "avg_frequency": 1.5, "avg_monetary": 240},
            {"avg_recency_days": 126, "avg_frequency": 2.7, "avg_monetary": 717},
            {"avg_recency_days": 209, "avg_frequency": 2.2, "avg_monetary": 308},
            {"avg_recency_days": 311, "avg_frequency": 1.0, "avg_monetary": 108},
            {"avg_recency_days": 308, "avg_frequency": 1.0, "avg_monetary": 329},
        ])
        labels = _label_clusters(profile)
        assert len(set(labels.values())) == len(profile)

    def test_most_recent_cluster_is_labelled_active(self):
        profile = self._profile([
            {"avg_recency_days": 10, "avg_frequency": 1.0, "avg_monetary": 100},
            {"avg_recency_days": 200, "avg_frequency": 1.0, "avg_monetary": 200},
            {"avg_recency_days": 400, "avg_frequency": 1.0, "avg_monetary": 300},
        ])
        labels = _label_clusters(profile)
        assert labels[0].startswith("Active")
        assert labels[2].startswith("Dormant")

    def test_highest_value_cluster_is_labelled_high_value(self):
        profile = self._profile([
            {"avg_recency_days": 10, "avg_frequency": 1.0, "avg_monetary": 900},
            {"avg_recency_days": 200, "avg_frequency": 1.0, "avg_monetary": 400},
            {"avg_recency_days": 400, "avg_frequency": 1.0, "avg_monetary": 50},
        ])
        labels = _label_clusters(profile)
        assert "High-Value" in labels[0]
        assert "Low-Value" in labels[2]

    def test_repeat_clusters_are_marked(self):
        profile = self._profile([
            {"avg_recency_days": 10, "avg_frequency": 3.2, "avg_monetary": 900},
            {"avg_recency_days": 400, "avg_frequency": 1.0, "avg_monetary": 50},
        ])
        labels = _label_clusters(profile)
        assert labels[0].endswith("Repeaters")
        assert not labels[1].endswith("Repeaters")

    def test_labels_do_not_depend_on_cluster_id_order(self):
        """KMeans ids reshuffle between runs; a cluster's label must follow its
        centroid, or the dashboard's segment names would change meaning."""
        rows = [
            {"avg_recency_days": 10, "avg_frequency": 3.0, "avg_monetary": 900},
            {"avg_recency_days": 200, "avg_frequency": 1.0, "avg_monetary": 400},
            {"avg_recency_days": 400, "avg_frequency": 1.0, "avg_monetary": 50},
        ]
        forward = _label_clusters(self._profile(rows))
        reversed_labels = _label_clusters(self._profile(rows[::-1]))
        assert forward[0] == reversed_labels[2]
        assert forward[2] == reversed_labels[0]


class TestForecastHelpers:
    def test_metrics_are_zero_for_a_perfect_forecast(self):
        from ml.forecasting import _metrics

        actual = np.array([100.0, 200.0, 300.0])
        result = _metrics(actual, actual.copy())
        assert result["mae"] == pytest.approx(0)
        assert result["rmse"] == pytest.approx(0)
        assert result["mape"] == pytest.approx(0)

    def test_mape_ignores_zero_actuals(self):
        from ml.forecasting import _metrics

        result = _metrics(np.array([0.0, 100.0]), np.array([10.0, 110.0]))
        assert result["mape"] == pytest.approx(10.0)
        assert not np.isinf(result["mape"])

    def test_bias_reports_direction(self):
        from ml.forecasting import _metrics

        over = _metrics(np.array([100.0, 100.0]), np.array([110.0, 120.0]))
        assert over["bias"] > 0
        under = _metrics(np.array([100.0, 100.0]), np.array([90.0, 80.0]))
        assert under["bias"] < 0

    def test_trim_tail_drops_partial_final_days(self):
        """The Olist extract stops mid-collection; those trailing partial days
        teach the model a downtrend that is an artefact of the export."""
        from ml.forecasting import _trim_tail

        frame = pd.DataFrame({
            "ds": pd.date_range("2018-01-01", periods=120, freq="D"),
            "y": [1000.0] * 120,
            "order_count": [50] * 115 + [1, 1, 1, 1, 1],
        })
        trimmed = _trim_tail(frame)
        assert len(trimmed) == 115

    def test_trim_tail_leaves_healthy_series_alone(self):
        from ml.forecasting import _trim_tail

        frame = pd.DataFrame({
            "ds": pd.date_range("2018-01-01", periods=120, freq="D"),
            "y": [1000.0] * 120,
            "order_count": [50] * 120,
        })
        assert len(_trim_tail(frame)) == 120
