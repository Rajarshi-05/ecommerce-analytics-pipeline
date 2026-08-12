"""The table specs drive DDL and load strategy, so their invariants are worth
pinning down: a typo here would silently produce a table nothing can join to."""

from __future__ import annotations

import pytest

from ingestion.schemas import SPECS_BY_NAME, TABLE_SPECS, TableSpec, get_spec


def test_nine_source_tables():
    assert len(TABLE_SPECS) == 9


def test_table_names_are_unique():
    names = [spec.name for spec in TABLE_SPECS]
    assert len(names) == len(set(names))


def test_source_files_are_unique():
    files = [spec.source_file for spec in TABLE_SPECS]
    assert len(files) == len(set(files))


@pytest.mark.parametrize("spec", TABLE_SPECS, ids=lambda s: s.name)
def test_merge_tables_declare_a_primary_key(spec: TableSpec):
    if spec.strategy == "merge":
        assert spec.primary_key, f"{spec.name} merges but has no primary key"


@pytest.mark.parametrize("spec", TABLE_SPECS, ids=lambda s: s.name)
def test_primary_key_columns_exist(spec: TableSpec):
    for column in spec.primary_key:
        assert column in spec.columns, f"{spec.name}: pk column '{column}' is not defined"


@pytest.mark.parametrize("spec", TABLE_SPECS, ids=lambda s: s.name)
def test_ddl_includes_lineage_columns(spec: TableSpec):
    ddl = spec.ddl("raw")
    assert '"_source_file"' in ddl
    assert '"_loaded_at"' in ddl
    assert ddl.startswith("CREATE TABLE IF NOT EXISTS")


@pytest.mark.parametrize("spec", TABLE_SPECS, ids=lambda s: s.name)
def test_ddl_declares_primary_key_only_for_merge(spec: TableSpec):
    ddl = spec.ddl("raw")
    assert ("PRIMARY KEY" in ddl) == (spec.strategy == "merge")


def test_merge_without_primary_key_is_rejected():
    broken = TableSpec(
        name="broken", source_file="x.csv", columns={"a": "TEXT"}, strategy="merge",
    )
    with pytest.raises(ValueError, match="requires a primary_key"):
        broken.ddl("raw")


def test_get_spec_round_trips():
    for name in SPECS_BY_NAME:
        assert get_spec(name).name == name


def test_get_spec_rejects_unknown_table():
    with pytest.raises(KeyError, match="Unknown table"):
        get_spec("does_not_exist")


def test_tables_with_known_duplicate_keys_use_full_refresh():
    # order_reviews has duplicate review_ids in the source and geolocation has
    # no natural key at all; neither can be safely upserted.
    assert get_spec("order_reviews").strategy == "full_refresh"
    assert get_spec("geolocation").strategy == "full_refresh"
