"""The synthetic generator is what CI and a fresh clone run against, so the
properties downstream models depend on have to hold. If any of these break,
dbt tests and the ML layer will fail in confusing ways."""

from __future__ import annotations

import pandas as pd
import pytest

from ingestion.schemas import TABLE_SPECS
from ingestion.synthetic import REPEAT_ORDER_RATE, generate


@pytest.fixture(scope="module")
def frames():
    return generate(n_orders=1_500, seed=7)


def test_produces_every_expected_file(frames):
    expected = {spec.source_file for spec in TABLE_SPECS}
    assert set(frames) == expected


def test_columns_match_the_specs(frames):
    for spec in TABLE_SPECS:
        frame = frames[spec.source_file]
        missing = set(spec.columns) - set(frame.columns)
        assert not missing, f"{spec.name} is missing columns: {sorted(missing)}"


def test_generation_is_deterministic():
    first = generate(n_orders=300, seed=11)["olist_orders_dataset.csv"]
    second = generate(n_orders=300, seed=11)["olist_orders_dataset.csv"]
    pd.testing.assert_frame_equal(first, second)


def test_order_ids_are_unique(frames):
    orders = frames["olist_orders_dataset.csv"]
    assert orders["order_id"].is_unique


def test_order_items_reference_real_orders(frames):
    orders = set(frames["olist_orders_dataset.csv"]["order_id"])
    items = frames["olist_order_items_dataset.csv"]
    assert set(items["order_id"]).issubset(orders)


def test_order_items_reference_real_products_and_sellers(frames):
    products = set(frames["olist_products_dataset.csv"]["product_id"])
    sellers = set(frames["olist_sellers_dataset.csv"]["seller_id"])
    items = frames["olist_order_items_dataset.csv"]
    assert set(items["product_id"]).issubset(products)
    assert set(items["seller_id"]).issubset(sellers)


def test_repeat_rate_matches_the_source(frames):
    """~3% repeat purchasers - the property the cohort analysis turns on."""
    customers = frames["olist_customers_dataset.csv"]
    orders_per_person = customers.groupby("customer_unique_id").size()
    repeat_share = (orders_per_person > 1).mean()
    assert 0.01 <= repeat_share <= 0.08, (
        f"repeat share {repeat_share:.3f} is far from the source's ~3%; "
        "the cohort-retention finding depends on this"
    )
    assert repeat_share == pytest.approx(REPEAT_ORDER_RATE, abs=0.04)


def test_history_spans_more_than_two_years(frames):
    purchases = pd.to_datetime(frames["olist_orders_dataset.csv"]["order_purchase_timestamp"])
    span_days = (purchases.max() - purchases.min()).days
    assert span_days > 700, "Prophet needs a long enough series to model seasonality"


def test_undelivered_orders_have_no_delivery_date(frames):
    orders = frames["olist_orders_dataset.csv"]
    undelivered = orders[orders["order_status"].isin(["canceled", "unavailable"])]
    assert undelivered["order_delivered_customer_date"].isna().all()


def test_late_deliveries_score_worse(frames):
    """The headline finding must actually be present in the generated data."""
    orders = frames["olist_orders_dataset.csv"].copy()
    reviews = frames["olist_order_reviews_dataset.csv"]
    merged = orders.merge(reviews, on="order_id")
    delivered = merged[merged["order_delivered_customer_date"].notna()]

    is_late = (delivered["order_delivered_customer_date"]
               > delivered["order_estimated_delivery_date"])
    late_score = delivered.loc[is_late, "review_score"].mean()
    on_time_score = delivered.loc[~is_late, "review_score"].mean()
    assert late_score < on_time_score - 0.5


def test_reviews_contain_duplicate_ids(frames):
    """The source's duplicate-review_id defect is reproduced on purpose so
    stg_order_reviews' de-duplication is exercised rather than assumed."""
    reviews = frames["olist_order_reviews_dataset.csv"]
    assert reviews["review_id"].duplicated().any()


def test_some_products_have_no_category(frames):
    products = frames["olist_products_dataset.csv"]
    assert products["product_category_name"].isna().any()


def test_review_text_is_not_perfectly_separable(frames):
    """Verbatim templates would make sentiment classification trivially perfect.
    Comments must vary and must sometimes contradict the star rating."""
    reviews = frames["olist_order_reviews_dataset.csv"]
    commented = reviews[reviews["review_comment_message"].notna()]
    assert len(commented) > 100

    # Distinct strings should far outnumber the handful of base templates.
    assert commented["review_comment_message"].nunique() > 100

    # Some five-star reviews should share vocabulary with negative ones.
    positive_text = " ".join(commented[commented["review_score"] == 5]
                             ["review_comment_message"].astype(str)).lower()
    assert any(word in positive_text for word in ("demorou", "atrasada", "pessima",
                                                  "razoavel", "mediano", "amassada"))


def test_categories_are_translatable(frames):
    products = frames["olist_products_dataset.csv"]
    translation = frames["product_category_name_translation.csv"]
    known = set(translation["product_category_name"])
    used = set(products["product_category_name"].dropna())
    assert used.issubset(known)
