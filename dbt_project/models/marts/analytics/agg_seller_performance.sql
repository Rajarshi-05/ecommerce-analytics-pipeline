/*
    Business question: top sellers by revenue, and who is dragging on
    satisfaction.

    Combines commercial scale (revenue, orders) with operational quality
    (lateness, review score) so the "top seller" list can be read against
    whether that volume is actually healthy.
*/

with items as (

    select * from {{ ref('fact_order_items') }}
    where {{ is_revenue_recognised() }}

),

seller_orders as (

    select distinct i.seller_key, i.order_id
    from items i

),

commercial as (

    select
        seller_key,
        count(*)                                    as items_sold,
        count(distinct order_id)                    as order_count,
        count(distinct customer_key)                as customer_count,
        count(distinct product_key)                 as distinct_products,
        sum(item_total)::numeric(14, 2)             as revenue,
        sum(freight_value)::numeric(14, 2)          as freight_revenue,
        round(avg(item_price), 2)                   as avg_item_price,
        min(order_purchase_date)                    as first_sale_date,
        max(order_purchase_date)                    as last_sale_date
    from items
    group by seller_key

),

operational as (

    select
        so.seller_key,
        round(avg(o.review_score), 3)                                        as avg_review_score,
        round(100 * avg(case when o.is_late_delivery then 1.0 else 0.0 end), 2)
                                                                             as late_delivery_pct,
        round(avg(o.delivery_days), 2)                                       as avg_delivery_days,
        count(*) filter (where o.review_score <= 2)                          as poor_review_count
    from seller_orders so
    inner join {{ ref('fact_orders') }} o
        on so.order_id = o.order_id
    group by so.seller_key

)

select
    d.seller_key,
    d.seller_id,
    d.seller_city,
    d.seller_state,
    d.seller_region,

    c.items_sold,
    c.order_count,
    c.customer_count,
    c.distinct_products,
    c.revenue,
    c.freight_revenue,
    c.avg_item_price,

    o.avg_review_score,
    o.late_delivery_pct,
    o.avg_delivery_days,
    o.poor_review_count,

    c.first_sale_date,
    c.last_sale_date,
    (c.last_sale_date - c.first_sale_date)                          as active_days,

    round(100 * c.revenue / nullif(sum(c.revenue) over (), 0), 3)   as revenue_share_pct,
    rank() over (order by c.revenue desc)                           as revenue_rank,

    -- A seller is flagged when they carry real volume *and* underperform on
    -- delivery - that combination is what actually costs the marketplace.
    (c.order_count >= 20 and o.late_delivery_pct > 15)              as is_at_risk_seller

from commercial c
inner join {{ ref('dim_sellers') }} d using (seller_key)
left  join operational o using (seller_key)
order by c.revenue desc
