#!/usr/bin/env bash
# Run the full pipeline with only Postgres running.
#
# The Airflow scheduler, webserver, dashboard and API together hold well over a
# gigabyte of RAM doing nothing useful while the pipeline executes. On a small
# host that is the difference between the ML step finishing and the OOM killer
# taking it. This script stops those services, runs the same steps the DAG runs
# in the same order, and brings the serving layer back at the end.
#
# The DAG remains the real orchestrator - this is the low-memory path for
# development on a constrained machine, and for anyone who wants to run the
# pipeline once without Airflow.
#
#   ./scripts/run_pipeline_lite.sh            # keep existing raw data
#   ./scripts/run_pipeline_lite.sh --reset    # truncate raw and reload
#   ./scripts/run_pipeline_lite.sh --skip-ml  # ingestion + dbt only

set -euo pipefail

cd "$(dirname "$0")/.."

RESET_FLAG=""
SKIP_ML=false
for arg in "$@"; do
  case "$arg" in
    --reset)   RESET_FLAG="--reset" ;;
    --skip-ml) SKIP_ML=true ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

PY=/home/airflow/venvs/pipeline/bin/python
DBT=/home/airflow/venvs/dbt/bin/dbt
PROJECT=/opt/airflow/project

step() { printf '\n\033[1;34m==> %s\033[0m\n' "$1"; }

step "Stopping the memory-hungry services (Postgres stays up)"
docker compose stop airflow-scheduler airflow-webserver dashboard api 2>&1 | tail -4 || true

step "Ensuring Postgres is up"
docker compose up -d postgres 2>&1 | tail -2
until docker compose exec -T postgres pg_isready -U "${POSTGRES_USER:-analytics}" >/dev/null 2>&1; do
  sleep 2
done
echo "Postgres ready."

run() {
  docker compose run --rm --no-deps --entrypoint bash airflow-scheduler -c "$1"
}

step "Source data"
run "cd $PROJECT && ($PY -m ingestion.cli download || $PY -m ingestion.cli seed --synthetic --orders 20000)" \
  2>&1 | tail -3

step "Load into the raw zone"
run "cd $PROJECT && $PY -m ingestion.cli load $RESET_FLAG" 2>&1 | grep -E "Truncated|Loaded|rows_read" | tail -3

step "Validate the raw zone"
run "cd $PROJECT && $PY -m ingestion.cli validate" 2>&1 | tail -2

step "dbt build (models + tests)"
run "cd $PROJECT/dbt_project && $DBT build --profiles-dir . --no-use-colors" 2>&1 | tail -3

if [ "$SKIP_ML" = false ]; then
  step "Customer segmentation"
  run "cd $PROJECT && $PY -m ml.segmentation" 2>&1 | tail -3

  step "Revenue forecast"
  run "cd $PROJECT && $PY -m ml.forecasting" 2>&1 | grep -E "MAPE|Forecast for" | tail -3

  step "Review sentiment"
  run "cd $PROJECT && $PY -m ml.sentiment" 2>&1 | grep -E "Holdout:" | tail -2
fi

step "Export the dashboard snapshot"
run "cd $PROJECT && $PY -m scripts.export_snapshot" 2>&1 | tail -2

step "Bringing the serving layer back"
docker compose up -d dashboard api 2>&1 | tail -3

printf '\n\033[1;32mPipeline complete.\033[0m Dashboard: http://localhost:%s  API: http://localhost:%s/docs\n' \
  "${DASHBOARD_PORT:-8501}" "${API_PORT:-8000}"
echo "Airflow is still stopped - start it with: docker compose up -d airflow-scheduler airflow-webserver"
