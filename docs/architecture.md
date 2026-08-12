# Architecture

Diagrams are Mermaid rather than a checked-in PNG: GitHub renders them inline,
and a diagram that lives next to the code it describes stays correct when the
code changes. A PNG goes stale silently.

## System

```mermaid
flowchart LR
    subgraph source["Source"]
        A["Olist CSVs<br/>9 relational files<br/>~100k orders"]
    end

    subgraph warehouse["PostgreSQL"]
        C[("raw<br/>faithful copy")]
        D[("staging<br/>typed · cleaned")]
        E[("marts<br/>star schema")]
        F[("analytics<br/>business views")]
        M[("ml<br/>model outputs")]
        AUD[("meta<br/>ingestion audit")]
    end

    subgraph serving["Serving"]
        H["Streamlit<br/>6-page dashboard"]
        I["FastAPI<br/>read-only"]
        P["Parquet snapshot<br/>for public deploy"]
    end

    A -->|"Kaggle API"| B["ingestion<br/>COPY + upsert"]
    B --> C
    B -.->|"row counts, keys"| AUD
    C -->|"dbt"| D
    D -->|"dbt"| E
    E -->|"dbt"| F
    E -->|"scikit-learn · Prophet"| M
    F --> H
    M --> H
    F --> I
    M --> I
    F --> P
    M --> P
    P --> H

    AF["Airflow<br/>daily 04:00"] -. orchestrates .-> B
    AF -. orchestrates .-> D
    AF -. orchestrates .-> M
    AF -. orchestrates .-> P
```

## Star schema

```mermaid
erDiagram
    DIM_DATE ||--o{ FACT_ORDERS : "order_date_key"
    DIM_CUSTOMERS ||--o{ FACT_ORDERS : "customer_key"
    DIM_GEOGRAPHY ||--o{ FACT_ORDERS : "geography_key"
    DIM_GEOGRAPHY ||--o{ DIM_CUSTOMERS : "geography_key"
    DIM_GEOGRAPHY ||--o{ DIM_SELLERS : "geography_key"
    FACT_ORDERS ||--o{ FACT_ORDER_ITEMS : "order_id"
    DIM_PRODUCTS ||--o{ FACT_ORDER_ITEMS : "product_key"
    DIM_SELLERS ||--o{ FACT_ORDER_ITEMS : "seller_key"
    DIM_DATE ||--o{ FACT_ORDER_ITEMS : "order_date_key"

    FACT_ORDERS {
        text order_id PK
        text customer_key FK
        text geography_key FK
        int order_date_key FK
        numeric order_total
        numeric gross_merchandise_value
        numeric freight_total
        int review_score
        int delivery_days
        bool is_late_delivery
    }

    FACT_ORDER_ITEMS {
        text order_item_key PK
        text order_id FK
        text product_key FK
        text seller_key FK
        numeric item_price
        numeric freight_value
    }

    DIM_CUSTOMERS {
        text customer_key PK
        text customer_state
        date first_order_date
        int lifetime_order_count
        bool is_repeat_customer
    }

    DIM_PRODUCTS {
        text product_key PK
        text product_category
        text weight_class
    }

    DIM_SELLERS {
        text seller_key PK
        text seller_state
        text seller_region
    }

    DIM_GEOGRAPHY {
        text geography_key PK
        text state
        text region
        numeric latitude
        numeric longitude
    }

    DIM_DATE {
        int date_key PK
        date date_day
        text year_month
        bool is_weekend
    }
```

## Airflow DAG

```mermaid
flowchart TD
    start([start]) --> A1[acquire_source_data]
    A1 --> A2[load_raw_tables]
    A2 --> A3[validate_raw_zone]
    A3 --> T1[dbt_deps]
    T1 --> T2[dbt_run]
    T2 --> T3[dbt_test]
    T3 --> T4[dbt_docs_generate]
    T4 --> M1[customer_segmentation]
    T4 --> M2[revenue_forecast]
    T4 --> M3[review_sentiment]
    M1 --> X[export_dashboard_snapshot]
    M2 --> X
    M3 --> X
    X --> finish([finish])

    classDef pooled fill:#fdf1ea,stroke:#eb6834,stroke-width:1px
    class M1,M2,M3 pooled
```

The three highlighted tasks share a one-slot Airflow pool. They have no data
dependency on each other, but each holds a full corpus in memory while fitting,
and running them concurrently OOM-killed the scheduler on a laptop-sized host.

## Layer contract

| Layer | Written by | May be read by | Guarantee |
|---|---|---|---|
| `raw` | `ingestion/` | dbt staging only | Byte-faithful to the source; never cleaned |
| `staging` | dbt | dbt marts only | Typed, renamed, de-duplicated |
| `marts` | dbt | analytics, ML, API | Star schema; tested grain and referential integrity |
| `analytics` | dbt | dashboard, API, snapshot | One definition per business metric |
| `ml` | `ml/` | dashboard, API, snapshot | Fully replaced each run; stamped with `run_id` |
| `meta` | `ingestion/` | operators | Append-only ingestion audit trail |

The dashboard and API are only ever allowed to read `analytics` and `ml`. That
is what keeps a metric definition from being reimplemented — differently — in
the presentation layer.
