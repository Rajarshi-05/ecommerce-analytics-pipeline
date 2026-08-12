-- Every item must belong to an order that exists in the order fact.
-- A relationships test covers the forward direction; this catches the reverse
-- case where fact_orders was rebuilt but fact_order_items was not.

select
    i.order_id,
    count(*) as orphan_items
from {{ ref('fact_order_items') }} i
left join {{ ref('fact_orders') }} o
    on i.order_id = o.order_id
where o.order_id is null
group by i.order_id
