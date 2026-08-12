"""The dataset registry is shared by the snapshot exporter and the dashboard.
If the two ever disagreed, the deployed app would silently show different
numbers from the local one - so the contract is tested."""

from __future__ import annotations

import pytest

from dashboard.lib.queries import DATASETS, DATASETS_BY_NAME, get_dataset


def test_dataset_names_are_unique():
    names = [dataset.name for dataset in DATASETS]
    assert len(names) == len(set(names))


@pytest.mark.parametrize("dataset", DATASETS, ids=lambda d: d.name)
def test_every_dataset_resolves_to_a_relation(dataset):
    assert dataset.source_relation, f"{dataset.name} has neither relation nor gated_on"
    assert "." in dataset.source_relation, "relations must be schema-qualified"


@pytest.mark.parametrize("dataset", DATASETS, ids=lambda d: d.name)
def test_every_dataset_produces_sql(dataset):
    sql = dataset.sql().strip().lower()
    assert sql.startswith("select")


@pytest.mark.parametrize("dataset", DATASETS, ids=lambda d: d.name)
def test_row_limit_appears_in_generated_sql(dataset):
    if dataset.row_limit:
        assert f"limit {dataset.row_limit}" in dataset.sql().lower()


def test_customer_grain_tables_are_never_exported():
    """Publishing per-customer rows to a public host would be the wrong default.
    Customer-level data is only ever exported pre-aggregated."""
    for dataset in DATASETS:
        if dataset.source_relation == "analytics.agg_customer_rfm":
            assert "group by" in dataset.sql().lower(), (
                "the RFM export must aggregate, never emit customer rows"
            )
        assert dataset.source_relation != "ml.customer_segments"
        assert dataset.source_relation != "marts.fact_order_items"


def test_ml_datasets_are_optional():
    """The snapshot must still build before the models have ever been trained."""
    for name in ("forecast_daily", "segment_profiles", "sentiment_metrics"):
        assert get_dataset(name).required is False


def test_core_analytics_datasets_are_required():
    for name in ("kpi_summary", "revenue_monthly", "geographic_revenue"):
        assert get_dataset(name).required is True


def test_get_dataset_rejects_unknown_name():
    with pytest.raises(KeyError, match="Unknown dataset"):
        get_dataset("nope")


def test_registry_lookup_matches_the_tuple():
    assert len(DATASETS_BY_NAME) == len(DATASETS)
