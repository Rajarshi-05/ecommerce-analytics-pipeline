/*
    Customer dimension at *person* grain.

    The source's `customer_id` is regenerated for every order, so a dimension
    built on it would have one row per order - degenerate, and it would make
    repeat-purchase and cohort analysis impossible. This model resolves to
    `customer_unique_id`, which is stable across orders, and carries the
    customer's most recent known location.

    Tenure columns (first/latest order date, lifetime order count) are
    denormalised rollups. They are strictly derivable from fact_orders, but
    keeping them on the dimension is what lets the dashboard filter cohorts
    without a second aggregate scan. They are rebuilt on every dbt run, so they
    cannot drift.
*/

with customers as (

    select * from {{ ref('stg_customers') }}

),

orders as (

    select * from {{ ref('stg_orders') }}

),

order_history as (

    select
        c.customer_unique_id,
        o.order_id,
        o.order_purchase_timestamp,
        o.order_status,
        c.customer_zip_code_prefix,
        c.customer_city,
        c.customer_state,
        row_number() over (
            partition by c.customer_unique_id
            order by o.order_purchase_timestamp desc
        ) as recency_rank
    from orders o
    inner join customers c using (customer_id)

),

rollup as (

    select
        customer_unique_id,
        count(*)                                        as lifetime_order_count,
        count(*) filter (where order_status = 'delivered') as delivered_order_count,
        min(order_purchase_timestamp)                   as first_order_at,
        max(order_purchase_timestamp)                   as latest_order_at,
        count(distinct customer_state)                  as distinct_states
    from order_history
    group by customer_unique_id

),

latest_location as (

    select
        customer_unique_id,
        customer_zip_code_prefix,
        customer_city,
        customer_state
    from order_history
    where recency_rank = 1

)

select
    r.customer_unique_id                       as customer_key,
    r.customer_unique_id,

    l.customer_zip_code_prefix                 as geography_key,
    l.customer_zip_code_prefix,
    l.customer_city,
    l.customer_state,

    r.first_order_at,
    r.latest_order_at,
    r.first_order_at::date                     as first_order_date,
    r.latest_order_at::date                    as latest_order_date,
    to_char(r.first_order_at, 'YYYY-MM')       as acquisition_cohort_month,

    r.lifetime_order_count,
    r.delivered_order_count,
    r.lifetime_order_count > 1                 as is_repeat_customer,
    r.distinct_states > 1                      as has_moved_state,

    -- Days between first and last purchase; 0 for one-time buyers.
    (r.latest_order_at::date - r.first_order_at::date) as customer_tenure_days

from rollup r
inner join latest_location l using (customer_unique_id)
