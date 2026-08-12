/*
    Single-row headline KPIs for the dashboard's top tiles.

    Exists so the dashboard makes one cheap query for the header instead of
    seven aggregate scans, and so "total revenue" has exactly one definition in
    the project rather than being recomputed per page.
*/

with orders as (

    select * from {{ ref('fact_orders') }}
    where {{ is_revenue_recognised() }}

),

customers as (

    select * from {{ ref('dim_customers') }}

),

delivered as (

    select * from orders
    where is_delivered and order_delivered_customer_date is not null

)

select
    (select count(*)                             from orders)      as total_orders,
    (select count(distinct customer_key)         from orders)      as total_customers,
    (select sum(order_total)::numeric(16, 2)     from orders)      as total_revenue,
    (select sum(gross_merchandise_value)::numeric(16, 2) from orders) as total_gmv,
    (select sum(freight_total)::numeric(16, 2)   from orders)      as total_freight,
    (select sum(item_count)                      from orders)      as total_items,
    (select round(avg(order_total), 2)           from orders)      as avg_order_value,

    (select min(order_purchase_date)             from orders)      as first_order_date,
    (select max(order_purchase_date)             from orders)      as last_order_date,

    (select count(*)                             from customers
      where is_repeat_customer)                                    as repeat_customers,
    (select round(100.0 * count(*) filter (where is_repeat_customer)
                  / nullif(count(*), 0), 2)      from customers)   as repeat_customer_pct,

    (select round(avg(review_score), 3)          from orders
      where review_score is not null)                              as avg_review_score,
    (select round(100.0 * count(*) filter (where review_score >= 4)
                  / nullif(count(*), 0), 2)      from orders
      where review_score is not null)                              as satisfied_pct,

    (select round(avg(delivery_days), 2)         from delivered)   as avg_delivery_days,
    (select round(100.0 * count(*) filter (where is_late_delivery)
                  / nullif(count(*), 0), 2)      from delivered)   as late_delivery_pct,
    (select round(100.0 * count(*) filter (where not is_late_delivery)
                  / nullif(count(*), 0), 2)      from delivered)   as on_time_delivery_pct,

    (select count(distinct product_key)          from {{ ref('fact_order_items') }}) as total_products,
    (select count(distinct seller_key)           from {{ ref('fact_order_items') }}) as total_sellers,

    (select count(*) from {{ ref('fact_orders') }} where is_canceled) as canceled_orders
