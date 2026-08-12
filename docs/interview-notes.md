# Interview preparation

Answers to the questions this project invites. Every claim here is backed by
something in the repository — the point is to be able to walk from the answer
to the code.

---

### Why a star schema, and what's the trade-off against a snowflake?

A star keeps analytical SQL flat: one join from a fact to any dimension, no
chains. Snowflaking would normalise `dim_products` into product → category →
category-translation, which saves storage this project does not need and adds a
join to every category query.

The trade-off is duplication. `product_category` is repeated across 30k+ product
rows instead of being stored once. At this scale that costs kilobytes and buys
readability. On a warehouse where a dimension is huge and volatile, the
calculation changes.

One thing I deliberately did *not* flatten: `dim_geography`. Customers and
sellers genuinely share it — the same zip prefix means the same place regardless
of who is standing there. That is a **conformed dimension**, not a snowflake, and
collapsing it into both `dim_customers` and `dim_sellers` would mean two copies
of the region mapping that could drift apart.

**Code:** `dbt_project/models/marts/core/`

---

### How does the DAG handle failure, and why is the pipeline idempotent?

**Failure.** Two retries with exponential backoff (2 → 10 min cap) and a 45-minute
execution timeout per task. `dbt test` is a *separate task* from `dbt run`, which
matters for two reasons: a red test is visually distinguishable from a broken
build in the UI, and because the model tasks sit downstream of it, models can
never train on data that failed its tests. `dbt docs generate` uses `ALL_DONE`
because documentation is not worth failing a data pipeline over.

**Idempotency**, layer by layer:

- **Ingestion** — data is `COPY`'d into a staging table, then either upserted on
  the natural key (`INSERT … ON CONFLICT DO UPDATE`) or swapped in atomically.
  A `DISTINCT ON` guards the upsert, because `ON CONFLICT` cannot touch the same
  target row twice in one statement and the source file itself can contain
  duplicate keys.
- **dbt** — models are `table`/`view` materialisations rebuilt from source, so
  they are *functions of* the raw zone rather than accumulations of it.
- **ML** — outputs are replaced, not appended. Each run is a full recomputation,
  so appending would just pile up stale generations of the same prediction.

CI proves this rather than asserting it: it runs the entire pipeline twice and
fails if `fact_orders` row count changes.

**The honest caveat.** Re-running the *same* extract is a no-op. Loading a
*different* extract brings new natural keys, so those rows are inserted alongside
the old ones — correct upsert behaviour, but it means swapping datasets needs an
explicit `--reset`. I hit this during development when the numbers doubled, and
adding the reset path was the fix.

**Code:** `dags/ecommerce_analytics_pipeline.py`, `ingestion/load.py`

---

### Why dbt instead of transformations in Python/pandas?

Three reasons, in order of how much they actually matter:

1. **Tests live with the model.** 204 of them, in the same files as the SQL they
   guard. In pandas, the transformation, its documentation and its tests are
   three separate artefacts that drift apart the moment someone is in a hurry.
2. **Lineage is free.** `dbt docs` generates the DAG from the `ref()` graph. I
   never maintain it. When I changed the revenue-recognition rule, the docs
   showed me every model affected.
3. **It runs in the warehouse.** Transformations scale with Postgres rather than
   with laptop memory. The geolocation table alone is ~1M rows; collapsing it to
   centroids in SQL is one `GROUP BY`, and pulling it into pandas to do the same
   thing would be strictly worse.

Where I *did* use Python: ingestion glue and the ML layer. Those are genuinely
imperative, and SQL would be the wrong tool.

---

### How did you validate data quality? What do the tests actually check?

Three layers, each catching a different class of problem.

**Load-time** (`ingestion/validate.py`) — row counts against published figures,
emptiness, natural-key uniqueness. These are about the *load*, not the model, so
they fail early and loudly before dbt ever runs.

**Schema tests** (dbt) — `not_null`, `unique`, `relationships`, `accepted_values`
on every key and enum. Ordinary, and the reason no fact row can point at a
dimension that isn't there.

**Business-logic tests** — the ones worth talking about:

- `fact_orders` must have exactly as many rows as `stg_orders` (`equal_rowcount`),
  and revenue must reconcile between the two facts **per order**. This is the
  fan-out guard. Joining item grain to order grain would silently multiply
  revenue by the average basket size, and nothing else would notice.
- Lifecycle timestamps must move forward: purchase → approved → carrier →
  delivered.
- `dim_customers.lifetime_order_count` must equal the actual count in
  `fact_orders`, so the denormalised rollup cannot drift from its source.
- `on_time_delivery_pct + late_delivery_pct` must equal 100.

Failing rows are persisted to a `dbt_test_failures` schema, so a red test points
at the offending records rather than just a count.

I also wrote the generic tests by hand (`macros/tests.sql`) rather than importing
`dbt_utils`, so the project builds with no package-registry access.

**Known source defects** are handled explicitly rather than papered over:
`review_id` is not unique, `geolocation` has no natural key, ~2% of products have
no category, and the source misspells `length` as `lenght`. Each is documented in
`schemas.py` and resolved in staging, with a test proving the resolution worked.

---

### Give me one real insight and what it implies.

**Missing the promised delivery date roughly doubles the 1-star rate.**

Orders arriving on or before the promise date average ~4.3/5 with a ~6% one-star
rate. Orders 1–3 days late average ~2.3/5 with a ~45% one-star rate. The
relationship is monotonic across every lateness bucket, and the Pearson
correlation between days-late and review score is about −0.19.

Two things make me believe it rather than just report it. First, monotonicity —
a spurious correlation rarely walks in order across seven buckets. Second,
independent corroboration from a different method: the sentiment classifier's
most negative learned terms are *delivery* words, not *product* words. Two
unrelated analyses pointing the same way.

**The business action is counter-intuitive.** The finding is not "deliver
faster" — it's that the *promise date* is the lever. The cliff is at the promise
date, not at any absolute number of days. Padding estimated delivery dates costs
nothing and moves orders from "late" into "early", where satisfaction is already
high. That is dramatically cheaper than accelerating logistics.

The second-order finding reinforces it: repeat purchase is ~3%, so there is no
retention flywheel to invest in. Almost all the value of a customer is realised
on their first order — which makes the first-order experience, i.e. delivery,
the thing that matters most.

---

### What would you change to handle streaming or real-time data?

The layering is designed so this is a swap, not a rewrite.

- **Ingestion** — orders land on Kafka; a consumer writes micro-batches to the
  raw zone. The upsert-on-natural-key logic works unchanged, which is exactly why
  it was written that way.
- **dbt** — staging and marts become `incremental` materialisations with a
  `unique_key` and a lookback window on `order_purchase_timestamp`, so late-arriving
  events are still captured. Currently they are full rebuilds, which is correct
  for a fixed snapshot and wrong for a live feed.
- **Partitioning** — monthly range partitions on `fact_orders`, so a backfill can
  drop and rebuild one partition instead of the whole table.
- **Airflow** — `catchup=True` with data-interval-scoped loads. The current DAG
  deliberately does not partition writes by execution date, which is honest for a
  static snapshot but would be wrong for streaming.
- **Slowly-changing dimensions** — product prices and seller details change.
  `dbt snapshot` would preserve history instead of overwriting it.
- **Monitoring** — `dbt source freshness` plus alerting on test failure, rather
  than relying on someone noticing a red square in the Airflow UI.

The star schema and the tests would not change at all. That is the point of the
layering.

---

### Things I'd expect to be pushed on

**"Your sentiment model gets 0.99 AUC — that's suspicious."** It is, and the
module says so: it logs a warning above 0.995 because real free-text sentiment
tops out around 0.90–0.95. The high score is an artefact of the synthetic
generator used when Kaggle credentials are absent. I hit exactly this during
development — the first version scored a perfect 1.000 because comments were
drawn verbatim from score-keyed templates — and fixed the *generator* to add
label noise and word-level variation rather than quietly reporting the number.

**"Why not VADER for sentiment?"** Because the reviews are in Portuguese and
VADER's lexicon is English. It would score most of the corpus neutral and look
completely plausible while being meaningless. I trained TF-IDF + logistic
regression on the corpus itself with star ratings as weak labels, using character
n-grams to handle Portuguese inflection.

**"Prophet is overkill / Prophet is a black box."** Which is why it is
backtested against a seasonal-naive baseline on a 90-day holdout and both scores
are stored. Prophet wins here by a wide margin on RMSE. If it hadn't, the honest
answer would have been to ship the baseline — and the code would have recorded
that rather than hidden it.

**"Your KMeans clusters look like the RFM segments."** Broadly, yes — and that
is the useful result, because it means the quintile cut-offs aren't arbitrary.
The clusters earn their place where the two disagree, at the boundary between
recent-low-value and dormant-high-value customers.

**"Why is repeat purchase so low? Is your model wrong?"** No — Olist regenerates
`customer_id` on every order, so anyone joining on it concludes there are no
repeat customers at all. Resolving to `customer_unique_id` is what makes the
analysis possible, and the real answer (~3%) is a genuine property of a
transactional marketplace.
