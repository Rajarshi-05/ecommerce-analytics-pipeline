-- Order lifecycle timestamps must move forward: purchase -> approved ->
-- handed to carrier -> delivered. A violation means either bad source data or a
-- broken cast in staging, and it would silently corrupt every delivery metric.

select
    order_id,
    order_purchase_timestamp,
    order_approved_at,
    order_delivered_carrier_date,
    order_delivered_customer_date
from {{ ref('fact_orders') }}
where
    (order_approved_at is not null
        and order_approved_at < order_purchase_timestamp)
    or (order_delivered_carrier_date is not null
        and order_delivered_carrier_date < order_purchase_timestamp)
    or (order_delivered_customer_date is not null
        and order_delivered_carrier_date is not null
        and order_delivered_customer_date < order_delivered_carrier_date)
