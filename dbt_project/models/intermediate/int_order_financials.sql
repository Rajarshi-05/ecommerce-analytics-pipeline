/*
    Collapses line items to one row per order.

    This exists so fact_orders can join a pre-aggregated financial summary
    instead of joining order_items directly - joining the item grain to the
    order grain is the classic fan-out that silently multiplies revenue.
*/

with items as (

    select * from {{ ref('stg_order_items') }}

),

aggregated as (

    select
        order_id,

        count(*)                                     as item_count,
        count(distinct product_id)                   as distinct_product_count,
        count(distinct seller_id)                    as distinct_seller_count,

        sum(item_price)::numeric(12, 2)              as gross_merchandise_value,
        sum(freight_value)::numeric(12, 2)           as freight_total,
        sum(item_total)::numeric(12, 2)              as order_total,
        avg(item_price)::numeric(12, 2)              as avg_item_price,
        max(item_price)::numeric(12, 2)              as max_item_price,

        min(shipping_limit_date)                     as earliest_shipping_limit

    from items
    group by order_id

)

select * from aggregated
