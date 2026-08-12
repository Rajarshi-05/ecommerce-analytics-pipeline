"""End-to-end analytics pipeline: ingest -> transform -> test -> model -> publish.

Idempotency
-----------
The whole DAG is safe to re-run for any logical date without duplicating data:

* **Ingestion** loads via COPY into a staging table, then either upserts on the
  natural key or swaps the table in one transaction (see `ingestion/load.py`).
  Running it twice lands the same rows.
* **dbt** models are `table` and `view` materialisations rebuilt from source on
  every run, so they are functions of the raw zone rather than accumulations.
* **ML** outputs are replaced, not appended - each run is a full recomputation.

Nothing here uses the execution date to partition writes, which is the honest
design for a static historical snapshot. The note in `README.md` covers what
would change for genuinely incremental data.

Failure handling
----------------
Tasks retry twice with exponential backoff. `dbt test` runs as a separate task
from `dbt run` so a data-quality failure is distinguishable from a build
failure in the UI, and it gates the ML tasks: models never train on data that
failed its tests.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta

from airflow.models.dag import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.empty import EmptyOperator
from airflow.utils.task_group import TaskGroup
from airflow.utils.trigger_rule import TriggerRule

ML_POOL = "ml_pool"

PROJECT_ROOT = os.getenv("PROJECT_ROOT", "/opt/airflow/project")
DBT_DIR = f"{PROJECT_ROOT}/dbt_project"
DBT_BIN = "/home/airflow/venvs/dbt/bin/dbt"
PIPELINE_PYTHON = "/home/airflow/venvs/pipeline/bin/python"

# Both venvs need the warehouse connection details; dbt reads them through
# env_var() in profiles.yml, the Python tasks through ingestion/ml config.
SHARED_ENV = {
    "POSTGRES_HOST": os.getenv("POSTGRES_HOST", "postgres"),
    "POSTGRES_PORT": os.getenv("POSTGRES_PORT", "5432"),
    "POSTGRES_USER": os.getenv("POSTGRES_USER", "analytics"),
    "POSTGRES_PASSWORD": os.getenv("POSTGRES_PASSWORD", "analytics"),
    "POSTGRES_DB": os.getenv("POSTGRES_DB", "ecommerce"),
    "DATABASE_URL": os.getenv("DATABASE_URL", ""),
    "PROJECT_ROOT": PROJECT_ROOT,
    "PYTHONPATH": PROJECT_ROOT,
    "DBT_PROFILES_DIR": DBT_DIR,
    "INGEST_SAMPLE_MODE": os.getenv("INGEST_SAMPLE_MODE", "false"),
    "INGEST_SAMPLE_ROWS": os.getenv("INGEST_SAMPLE_ROWS", "5000"),
    "KAGGLE_USERNAME": os.getenv("KAGGLE_USERNAME", ""),
    "KAGGLE_KEY": os.getenv("KAGGLE_KEY", ""),
}

DEFAULT_ARGS = {
    "owner": "analytics",
    "depends_on_past": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=2),
    "retry_exponential_backoff": True,
    "max_retry_delay": timedelta(minutes=10),
    "execution_timeout": timedelta(minutes=45),
    "email_on_failure": False,
}


def dbt(command: str) -> str:
    return f"cd {DBT_DIR} && {DBT_BIN} {command} --profiles-dir {DBT_DIR} --no-use-colors"


def pipeline(module: str, args: str = "") -> str:
    return f"cd {PROJECT_ROOT} && {PIPELINE_PYTHON} -m {module} {args}".strip()


with DAG(
    dag_id="ecommerce_analytics_pipeline",
    description="Olist raw CSVs to a tested star schema, ML outputs and a dashboard snapshot.",
    default_args=DEFAULT_ARGS,
    start_date=datetime(2024, 1, 1),
    schedule="0 4 * * *",
    catchup=False,
    max_active_runs=1,
    tags=["ecommerce", "dbt", "elt", "ml"],
    doc_md=__doc__,
) as dag:

    start = EmptyOperator(task_id="start")

    # ------------------------------------------------------------- ingest --
    with TaskGroup(group_id="ingest", tooltip="Kaggle CSVs into the raw schema") as ingest:
        acquire_source = BashOperator(
            task_id="acquire_source_data",
            # Falls back to the synthetic generator when Kaggle credentials are
            # absent, so a fresh clone produces a working pipeline rather than a
            # red DAG. The provenance marker records which path was taken.
            bash_command=(
                f"{pipeline('ingestion.cli', 'download')} "
                f"|| {pipeline('ingestion.cli', 'seed --synthetic --orders 20000')}"
            ),
            env=SHARED_ENV,
            append_env=True,
            doc_md=("Download from Kaggle; generate a synthetic stand-in "
                    "if credentials are missing."),
        )

        load_raw = BashOperator(
            task_id="load_raw_tables",
            bash_command=pipeline("ingestion.cli", "load --run-id {{ run_id }}"),
            env=SHARED_ENV,
            append_env=True,
            doc_md="Idempotent COPY + upsert/swap into `raw`. Safe to re-run.",
        )

        validate_raw = BashOperator(
            task_id="validate_raw_zone",
            bash_command=pipeline("ingestion.cli", "validate"),
            env=SHARED_ENV,
            append_env=True,
            doc_md="Row counts, emptiness and natural-key uniqueness in the raw zone.",
        )

        acquire_source >> load_raw >> validate_raw

    # ---------------------------------------------------------- transform --
    with TaskGroup(group_id="transform", tooltip="dbt build of staging and marts") as transform:
        dbt_deps = BashOperator(
            task_id="dbt_deps",
            bash_command=dbt("deps"),
            env=SHARED_ENV,
            append_env=True,
        )

        dbt_run = BashOperator(
            task_id="dbt_run",
            bash_command=dbt("run"),
            env=SHARED_ENV,
            append_env=True,
            doc_md="Builds staging views, the star schema and the analytics views.",
        )

        dbt_test = BashOperator(
            task_id="dbt_test",
            bash_command=dbt("test"),
            env=SHARED_ENV,
            append_env=True,
            doc_md=(
                "Separate from dbt_run so a data-quality failure is visually "
                "distinct from a build failure. Gates the ML tasks."
            ),
        )

        dbt_docs = BashOperator(
            task_id="dbt_docs_generate",
            bash_command=dbt("docs generate"),
            env=SHARED_ENV,
            append_env=True,
            # Documentation is not worth failing a data pipeline over.
            trigger_rule=TriggerRule.ALL_DONE,
        )

        dbt_deps >> dbt_run >> dbt_test >> dbt_docs

    # ----------------------------------------------------------------- ml --
    # These three have no data dependency on each other, but each holds the
    # full customer or review corpus in memory while it fits. Letting Airflow
    # fan them out killed the scheduler with an OOM on a laptop-sized host, so
    # they share a one-slot pool: still declared as independent tasks, executed
    # one at a time. Raise ML_POOL_SLOTS on a bigger box to get the parallelism
    # back without touching the DAG.
    with TaskGroup(group_id="models", tooltip="Segmentation, forecasting, sentiment") as models:
        BashOperator(
            task_id="customer_segmentation",
            bash_command=pipeline("ml.segmentation", "--run-id {{ run_id }}"),
            env=SHARED_ENV,
            append_env=True,
            pool=ML_POOL,
            doc_md="KMeans over log-scaled RFM features; k chosen by silhouette.",
        )
        BashOperator(
            task_id="revenue_forecast",
            bash_command=pipeline("ml.forecasting", "--run-id {{ run_id }} --horizon-days 90"),
            env=SHARED_ENV,
            append_env=True,
            pool=ML_POOL,
            doc_md="Prophet with a held-out backtest against a seasonal-naive baseline.",
        )
        BashOperator(
            task_id="review_sentiment",
            bash_command=pipeline("ml.sentiment", "--run-id {{ run_id }}"),
            env=SHARED_ENV,
            append_env=True,
            pool=ML_POOL,
            doc_md="TF-IDF + logistic regression on Portuguese review text.",
        )

    # ------------------------------------------------------------ publish --
    export_snapshot = BashOperator(
        task_id="export_dashboard_snapshot",
        bash_command=pipeline("scripts.export_snapshot"),
        env=SHARED_ENV,
        append_env=True,
        doc_md=(
            "Writes the mart and ML tables to Parquet so the Streamlit app can "
            "be deployed to Community Cloud without exposing the warehouse."
        ),
    )

    finish = EmptyOperator(task_id="finish", trigger_rule=TriggerRule.ALL_SUCCESS)

    start >> ingest >> transform >> models >> export_snapshot >> finish
