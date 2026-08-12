-- The two facts must agree on revenue per order. If a join in either model
-- fans out, this is the test that catches it - and it catches it per-order,
-- so the failing rows in dbt_test_failures point straight at the cause.

with order_level as (

    select order_id, order_total
    from {{ ref('fact_orders') }}

),

item_level as (

    select
        order_id,
        sum(item_total)::numeric(12, 2) as item_total_sum
    from {{ ref('fact_order_items') }}
    group by order_id

)

select
    o.order_id,
    o.order_total,
    i.item_total_sum,
    round(o.order_total - i.item_total_sum, 2) as difference
from order_level o
inner join item_level i
    on o.order_id = i.order_id
where abs(o.order_total - i.item_total_sum) > 0.01
