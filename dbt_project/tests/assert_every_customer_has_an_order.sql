-- dim_customers is derived from the order history, so a customer with zero
-- orders means the dimension build has drifted from the fact.

select
    c.customer_key,
    c.lifetime_order_count,
    count(o.order_id) as actual_orders
from {{ ref('dim_customers') }} c
left join {{ ref('fact_orders') }} o
    on c.customer_key = o.customer_key
group by c.customer_key, c.lifetime_order_count
having count(o.order_id) = 0
    or count(o.order_id) <> c.lifetime_order_count
