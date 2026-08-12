# Resume bullets

Drafts for a CV entry. **The bracketed figures are the ones to re-check** — they
come from a run against the synthetic generator. Re-run with the real Kaggle
dataset before quoting them (`make download && make reload && make pipeline`),
then update.

Everything not bracketed is a structural fact about the repository and is true
as written.

---

## Standard three-bullet version

- Built an end-to-end e-commerce analytics pipeline over **[~100K]** orders using
  Python, Airflow, dbt and PostgreSQL — automating Kaggle ingestion through
  insight generation via an orchestrated, idempotent DAG that is safe to retry.
- Designed a star-schema warehouse (2 fact tables, 5 conformed dimensions) with
  **204 automated dbt data-quality tests**, including cross-model reconciliation
  checks that catch join fan-out before it silently inflates revenue.
- Built RFM + KMeans customer segmentation, a Prophet revenue forecast
  backtested against a seasonal-naive baseline (**[14% vs 50%]** holdout MAPE),
  and a Portuguese-language review sentiment classifier — surfaced through a
  deployed interactive dashboard.

## Longer version, if there is room for four or five

- Built an end-to-end analytics pipeline over **[~100K]** e-commerce orders
  (Python · Airflow · dbt · PostgreSQL · Docker), reproducible from a clean
  machine with a single `docker compose up`.
- Designed a star-schema warehouse resolving the source's per-order customer ID
  to a stable person-level key, which is what made repeat-purchase and cohort
  retention analysis possible at all.
- Wrote **204 dbt tests** across schema, custom generic and singular business
  assertions; added GitHub Actions CI that runs the full pipeline against a
  Postgres service and verifies idempotency by executing it twice.
- Trained and evaluated three models — KMeans segmentation with silhouette-based
  k selection, Prophet forecasting with a held-out backtest against a naive
  baseline, and a TF-IDF/logistic-regression sentiment classifier chosen over an
  off-the-shelf lexicon because the corpus is Portuguese.
- Surfaced results through a six-page Streamlit dashboard and a FastAPI service,
  with a Parquet snapshot mechanism that lets the dashboard deploy publicly
  without exposing the warehouse.

## One-liner, for a projects list

> **E-Commerce Analytics Pipeline** — Kaggle → PostgreSQL → dbt star schema →
> ML → Streamlit, orchestrated by Airflow. 204 data-quality tests, CI-verified
> idempotency, live dashboard. `[repo]` · `[demo]`

---

## What to actually say when asked about it

Lead with the **finding**, not the stack — the stack is on the page already:

> "The headline result was that missing the promised delivery date roughly
> doubles the one-star rate, and the effect is monotonic across every lateness
> bucket. The interesting part is that the lever isn't shipping faster — it's the
> promise date itself, which is free to change."

Then let them ask how you got there. That's when the pipeline comes up, and it
lands better as the answer to a question than as an opening claim.

## Things to be honest about

- The dataset is a well-known Kaggle set. The differentiation is in the build —
  orchestration, tests, a real warehouse model, a backtested forecast, live
  deployment — not in the data.
- The synthetic-data path exists so the repo runs without credentials. Say so if
  asked; it is a design decision worth defending, not something to hide.
- Repeat purchase is genuinely ~3%. If someone challenges the cohort chart as
  "broken", that's an opening to explain the `customer_unique_id` resolution.
