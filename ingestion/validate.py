"""Post-load sanity checks on the raw zone.

Deliberately thin: these guard the *load*, not the data model. Anything about
business meaning (uniqueness of a surrogate key, referential integrity between
facts and dimensions, accepted value sets) belongs in dbt tests, where it is
versioned next to the model that depends on it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import text

from ingestion import provenance
from ingestion.config import get_settings
from ingestion.db import get_engine, table_exists
from ingestion.schemas import TABLE_SPECS

log = logging.getLogger(__name__)

COUNT_TOLERANCE = 0.02


class ValidationError(RuntimeError):
    pass


@dataclass
class CheckResult:
    table: str
    check: str
    passed: bool
    detail: str

    def __str__(self) -> str:
        mark = "PASS" if self.passed else "FAIL"
        return f"[{mark}] {self.table:<28} {self.check:<22} {self.detail}"


def is_strict_by_default() -> bool:
    """Published row counts only apply to a full load of the real dataset."""
    settings = get_settings()
    return provenance.read(settings.raw_dir).is_real_data and not settings.sample_mode


def run_checks(strict: bool | None = None) -> list[CheckResult]:
    settings = get_settings()
    schema = settings.raw_schema
    strict = is_strict_by_default() if strict is None else strict
    if not strict:
        log.info(
            "Row-count comparison against published Olist figures is disabled "
            "(data source: %s, sample_mode=%s).",
            provenance.read(settings.raw_dir).source, settings.sample_mode,
        )
    engine = get_engine()
    results: list[CheckResult] = []

    for spec in TABLE_SPECS:
        if not table_exists(schema, spec.name):
            results.append(CheckResult(spec.name, "table_exists", False, "table not found"))
            continue
        results.append(CheckResult(spec.name, "table_exists", True, "ok"))

        with engine.connect() as conn:
            count = int(conn.execute(
                text(f'SELECT count(*) FROM "{schema}"."{spec.name}"')).scalar_one())

            results.append(CheckResult(
                spec.name, "not_empty", count > 0, f"{count:,} rows"))

            if spec.expected_rows and strict:
                drift = abs(count - spec.expected_rows) / spec.expected_rows
                results.append(CheckResult(
                    spec.name, "row_count_vs_source", drift <= COUNT_TOLERANCE,
                    f"{count:,} vs expected {spec.expected_rows:,} ({drift:.1%} drift)",
                ))

            if spec.primary_key:
                pk = ", ".join(f'"{c}"' for c in spec.primary_key)
                duplicates = int(conn.execute(text(f"""
                    SELECT coalesce(sum(n - 1), 0) FROM (
                        SELECT count(*) AS n FROM "{schema}"."{spec.name}"
                        GROUP BY {pk} HAVING count(*) > 1
                    ) d
                """)).scalar_one())
                results.append(CheckResult(
                    spec.name, "primary_key_unique", duplicates == 0,
                    f"{duplicates:,} duplicate rows on ({', '.join(spec.primary_key)})",
                ))

    return results


def assert_valid(strict: bool | None = None) -> list[CheckResult]:
    results = run_checks(strict=strict)
    for result in results:
        (log.info if result.passed else log.error)("%s", result)

    failures = [r for r in results if not r.passed]
    if failures:
        raise ValidationError(
            f"{len(failures)} raw-zone check(s) failed:\n"
            + "\n".join(f"  - {f}" for f in failures)
        )
    log.info("All %d raw-zone checks passed.", len(results))
    return results
