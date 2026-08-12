SHELL := /bin/bash
.DEFAULT_GOAL := help

COMPOSE       := docker compose
AIRFLOW       := $(COMPOSE) exec -T airflow-scheduler
RUN           := $(COMPOSE) run --rm --no-deps --entrypoint bash airflow-scheduler -c
PIPELINE_PY   := /home/airflow/venvs/pipeline/bin/python
DBT           := /home/airflow/venvs/dbt/bin/dbt
PROJECT       := /opt/airflow/project
DBT_DIR       := $(PROJECT)/dbt_project

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

# ------------------------------------------------------------------ setup --
.PHONY: env
env: ## Create .env from the example if it does not exist
	@test -f .env || (cp .env.example .env && echo "Created .env")

.PHONY: build
build: env ## Build the Docker images
	$(COMPOSE) build

.PHONY: up
up: env ## Start every service
	$(COMPOSE) up -d
	@echo ""
	@echo "  Dashboard  http://localhost:$${DASHBOARD_PORT:-8501}"
	@echo "  Airflow    http://localhost:$${AIRFLOW_WEB_PORT:-8080}  (admin / admin)"
	@echo "  API docs   http://localhost:$${API_PORT:-8000}/docs"

.PHONY: down
down: ## Stop every service (data is preserved)
	$(COMPOSE) down

.PHONY: clean
clean: ## Stop everything and DELETE the warehouse volume
	$(COMPOSE) down -v

.PHONY: logs
logs: ## Tail logs from all services
	$(COMPOSE) logs -f --tail=100

.PHONY: ps
ps: ## Show service status
	$(COMPOSE) ps

# -------------------------------------------------------------- ingestion --
.PHONY: download
download: ## Download the Olist dataset from Kaggle (needs credentials)
	$(RUN) 'cd $(PROJECT) && $(PIPELINE_PY) -m ingestion.cli download'

.PHONY: seed
seed: ## Generate a synthetic stand-in dataset (no Kaggle needed)
	$(RUN) 'cd $(PROJECT) && $(PIPELINE_PY) -m ingestion.cli seed --synthetic --orders 20000'

.PHONY: load
load: ## Load data/raw CSVs into the raw schema
	$(RUN) 'cd $(PROJECT) && $(PIPELINE_PY) -m ingestion.cli load'

.PHONY: reload
reload: ## Truncate raw and reload (use when switching datasets)
	$(RUN) 'cd $(PROJECT) && $(PIPELINE_PY) -m ingestion.cli load --reset'

.PHONY: validate
validate: ## Run raw-zone data checks
	$(RUN) 'cd $(PROJECT) && $(PIPELINE_PY) -m ingestion.cli validate'

.PHONY: info
info: ## Show what is currently loaded
	$(RUN) 'cd $(PROJECT) && $(PIPELINE_PY) -m ingestion.cli info'

# --------------------------------------------------------------------- dbt --
.PHONY: dbt-build
dbt-build: ## Run dbt models and tests
	$(RUN) 'cd $(DBT_DIR) && $(DBT) build --profiles-dir .'

.PHONY: dbt-run
dbt-run: ## Run dbt models only
	$(RUN) 'cd $(DBT_DIR) && $(DBT) run --profiles-dir .'

.PHONY: dbt-test
dbt-test: ## Run dbt tests only
	$(RUN) 'cd $(DBT_DIR) && $(DBT) test --profiles-dir .'

.PHONY: dbt-docs
dbt-docs: ## Generate dbt docs, then serve them on :8081
	$(RUN) 'cd $(DBT_DIR) && $(DBT) docs generate --profiles-dir .'
	@echo "Serving dbt docs at http://localhost:8081 (Ctrl-C to stop)"
	@cd dbt_project/target && python -m http.server 8081

# ---------------------------------------------------------------------- ml --
.PHONY: ml
ml: ## Train every model (segmentation, forecast, sentiment)
	$(RUN) 'cd $(PROJECT) && $(PIPELINE_PY) -m ml.segmentation \
	  && $(PIPELINE_PY) -m ml.forecasting \
	  && $(PIPELINE_PY) -m ml.sentiment'

.PHONY: snapshot
snapshot: ## Export the Parquet snapshot the deployed dashboard reads
	$(RUN) 'cd $(PROJECT) && $(PIPELINE_PY) -m scripts.export_snapshot'

# --------------------------------------------------------------- pipeline --
.PHONY: pipeline
pipeline: ## Run the whole pipeline once, without Airflow
	$(RUN) 'set -e; cd $(PROJECT); \
	  ($(PIPELINE_PY) -m ingestion.cli download || \
	   $(PIPELINE_PY) -m ingestion.cli seed --synthetic --orders 20000); \
	  $(PIPELINE_PY) -m ingestion.cli load; \
	  $(PIPELINE_PY) -m ingestion.cli validate; \
	  cd $(DBT_DIR) && $(DBT) build --profiles-dir .; \
	  cd $(PROJECT); \
	  $(PIPELINE_PY) -m ml.segmentation; \
	  $(PIPELINE_PY) -m ml.forecasting; \
	  $(PIPELINE_PY) -m ml.sentiment; \
	  $(PIPELINE_PY) -m scripts.export_snapshot'

.PHONY: trigger
trigger: ## Trigger the Airflow DAG
	$(AIRFLOW) airflow dags trigger ecommerce_analytics_pipeline

.PHONY: dag-status
dag-status: ## Show the most recent DAG runs
	$(AIRFLOW) airflow dags list-runs -d ecommerce_analytics_pipeline

# ------------------------------------------------------------------- tests --
# -p no:cacheprovider: the project root inside the container is not writable by
# the airflow user, and a pytest cache there is worthless anyway.
.PHONY: test
test: ## Run the unit test suite
	$(RUN) 'cd $(PROJECT) && $(PIPELINE_PY) -m pytest -m "not integration" -p no:cacheprovider'

.PHONY: test-integration
test-integration: ## Run integration tests against the running warehouse
	$(COMPOSE) run --rm --entrypoint bash airflow-scheduler -c \
	  'cd $(PROJECT) && $(PIPELINE_PY) -m pytest -m integration -v -p no:cacheprovider'

.PHONY: lint
lint: ## Lint with ruff
	ruff check .

.PHONY: psql
psql: ## Open a psql shell on the warehouse
	$(COMPOSE) exec postgres psql -U $${POSTGRES_USER:-analytics} -d $${POSTGRES_DB:-ecommerce}
