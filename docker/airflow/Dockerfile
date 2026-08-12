FROM apache/airflow:2.10.5-python3.11

# Build toolchain is needed for Prophet's cmdstan/pystan wheels on some arches.
USER root
RUN apt-get update \
    && apt-get install --no-install-recommends -y build-essential git curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*
USER airflow

# Two isolated virtualenvs. Airflow's scheduler runs on the image's own Python;
# dbt and the ML/ingestion code each get their own interpreter so a pin bump in
# one can never take down the orchestrator. The DAG shells into these.
COPY requirements-dbt.txt requirements-pipeline.txt requirements-test.txt /tmp/

RUN python -m venv /home/airflow/venvs/dbt \
    && /home/airflow/venvs/dbt/bin/pip install --no-cache-dir -U pip \
    && /home/airflow/venvs/dbt/bin/pip install --no-cache-dir -r /tmp/requirements-dbt.txt

RUN python -m venv /home/airflow/venvs/pipeline \
    && /home/airflow/venvs/pipeline/bin/pip install --no-cache-dir -U pip \
    && /home/airflow/venvs/pipeline/bin/pip install --no-cache-dir -r /tmp/requirements-pipeline.txt

# Separate layer: Prophet takes minutes to install, so a test-dependency bump
# must not invalidate it.
RUN /home/airflow/venvs/pipeline/bin/pip install --no-cache-dir -r /tmp/requirements-test.txt

ENV DBT_PYTHON=/home/airflow/venvs/dbt/bin/python \
    DBT_BIN=/home/airflow/venvs/dbt/bin/dbt \
    PIPELINE_PYTHON=/home/airflow/venvs/pipeline/bin/python \
    PYTHONPATH=/opt/airflow/project \
    DBT_PROFILES_DIR=/opt/airflow/project/dbt_project \
    DBT_PROJECT_DIR=/opt/airflow/project/dbt_project
