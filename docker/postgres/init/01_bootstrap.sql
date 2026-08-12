-- Runs once, on first initialisation of the Postgres data volume.
-- Creates the Airflow metadata database alongside the analytics warehouse,
-- and lays out the medallion-style schemas the pipeline writes into.

CREATE DATABASE airflow;

CREATE SCHEMA IF NOT EXISTS raw;        -- 1:1 landing copy of the source CSVs
CREATE SCHEMA IF NOT EXISTS staging;    -- dbt staging models (typed, renamed)
CREATE SCHEMA IF NOT EXISTS marts;      -- star schema: facts + dimensions
CREATE SCHEMA IF NOT EXISTS analytics;  -- business-question views
CREATE SCHEMA IF NOT EXISTS ml;         -- model outputs (segments, forecasts)
CREATE SCHEMA IF NOT EXISTS meta;       -- ingestion audit log

-- Audit table written by the ingestion layer on every load. Gives the DAG a
-- cheap way to answer "what landed, when, and how many rows" without scanning
-- the raw tables.
CREATE TABLE IF NOT EXISTS meta.ingestion_audit (
    audit_id        BIGSERIAL PRIMARY KEY,
    table_name      TEXT        NOT NULL,
    source_file     TEXT        NOT NULL,
    rows_in_source  BIGINT      NOT NULL,
    rows_loaded     BIGINT      NOT NULL,
    load_strategy   TEXT        NOT NULL,
    started_at      TIMESTAMPTZ NOT NULL,
    finished_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    run_id          TEXT
);

CREATE INDEX IF NOT EXISTS ix_ingestion_audit_table
    ON meta.ingestion_audit (table_name, finished_at DESC);
