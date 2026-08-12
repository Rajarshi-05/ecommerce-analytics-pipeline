/*
    Grain: one row per item within an order.

    The second fact in the star. fact_orders answers "how many orders, how much
    per order"; this one answers anything that needs product or seller on the
    row - category revenue, seller league tables, basket composition. Keeping
    them separate rather than forcing one wide table is what stops order-level
    measures from being double counted across a multi-item basket.
*/

{{
    config(
        materialized='table',
        indexes=[
            {'columns': ['order_item_key'], 'unique': True},
            {'columns': ['order_id']},
            {'columns': ['product_key']},
            {'columns': ['seller_key']},
            {'columns': ['order_date_key']},
        ],
    )
}}

with items as (

    select * from {{ ref('stg_order_items') }}

),

orders as (

    select * from {{ ref('stg_orders') }}

),

customers as (

    select * from {{ ref('stg_customers') }}

),

sellers as (

    select * from {{ ref('stg_sellers') }}

),

order_item_counts as (

    select order_id, count(*) as items_in_order
    from items
    group by order_id

)

select
    i.order_item_key,
    i.order_id,
    i.order_item_id,

    -- Foreign keys
    i.product_id                                             as product_key,
    i.seller_id                                              as seller_key,
    c.customer_unique_id                                     as customer_key,
    c.customer_zip_code_prefix                               as customer_geography_key,
    s.seller_zip_code_prefix                                 as seller_geography_key,
    (to_char(o.order_purchase_timestamp, 'YYYYMMDD'))::int   as order_date_key,

    -- Degenerate attributes
    o.order_status,
    c.customer_state,
    s.seller_state,
    c.customer_state = s.seller_state                        as is_intrastate_shipment,

    o.order_purchase_timestamp,
    o.order_purchase_timestamp::date                         as order_purchase_date,
    o.order_delivered_customer_date,
    i.shipping_limit_date,

    -- Measures
    i.item_price,
    i.freight_value,
    i.item_total,
    n.items_in_order,

    -- Freight as a share of item value: the margin lever on low-priced items.
    case
        when i.item_price = 0 then null
        else round(i.freight_value / i.item_price, 4)
    end                                                      as freight_ratio,

    o.order_status = 'delivered'                             as is_delivered

from items i
inner join orders            o using (order_id)
inner join customers         c using (customer_id)
inner join sellers           s using (seller_id)
inner join order_item_counts n using (order_id)
