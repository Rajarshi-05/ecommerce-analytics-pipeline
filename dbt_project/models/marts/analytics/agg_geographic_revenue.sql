/*
    Business question: revenue by state and region, using the geolocation data.

    Includes the freight burden per state, which is where the geolocation join
    earns its place: the long-haul North/Northeast states carry a materially
    higher freight-to-price ratio and slower delivery, and that shows up in
    their review scores.
*/

with orders as (

    select * from {{ ref('fact_orders') }}
    where {{ is_revenue_recognised() }}

),

by_state as (

    select
        o.customer_state                                     as state,
        g.region,

        count(*)                                             as order_count,
        count(distinct o.customer_key)                       as customer_count,
        sum(o.order_total)::numeric(14, 2)                    as revenue,
        sum(o.gross_merchandise_value)::numeric(14, 2)        as gmv,
        sum(o.freight_total)::numeric(14, 2)                  as freight_revenue,
        round(avg(o.order_total), 2)                          as avg_order_value,
        round(avg(o.freight_total), 2)                        as avg_freight,
        round(avg(o.delivery_days), 2)                        as avg_delivery_days,
        round(avg(o.review_score), 3)                         as avg_review_score,
        round(100 * avg(case when o.is_late_delivery then 1.0 else 0.0 end), 2)
                                                              as late_delivery_pct,
        round(avg(g.latitude), 4)                             as latitude,
        round(avg(g.longitude), 4)                            as longitude

    from orders o
    inner join {{ ref('dim_geography') }} g
        on o.geography_key = g.geography_key
    group by o.customer_state, g.region

)

select
    state,
    region,

    order_count,
    customer_count,
    revenue,
    gmv,
    freight_revenue,
    avg_order_value,
    avg_freight,
    avg_delivery_days,
    avg_review_score,
    late_delivery_pct,
    latitude,
    longitude,

    round(100 * freight_revenue / nullif(gmv, 0), 2)               as freight_to_gmv_pct,
    round(100 * revenue / nullif(sum(revenue) over (), 0), 2)       as revenue_share_pct,
    round(revenue / nullif(customer_count, 0), 2)                   as revenue_per_customer,
    rank() over (order by revenue desc)                             as revenue_rank

from by_state
order by revenue desc
