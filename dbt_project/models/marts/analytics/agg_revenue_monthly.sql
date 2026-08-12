/*
    Business question: monthly revenue trend and growth rate.

    Reported on order_purchase_date rather than delivery date - that is when the
    marketplace recognises the sale, and it keeps the series comparable with the
    forecast, which is trained on the same basis.
*/

with orders as (

    select * from {{ ref('fact_orders') }}
    where {{ is_revenue_recognised() }}

),

monthly as (

    select
        date_trunc('month', order_purchase_date)::date        as month_start_date,
        to_char(order_purchase_date, 'YYYY-MM')               as year_month,
        extract(year from order_purchase_date)::int           as year_number,
        extract(quarter from order_purchase_date)::int        as quarter_number,

        count(*)                                             as order_count,
        count(distinct customer_key)                          as active_customers,
        sum(order_total)::numeric(14, 2)                      as revenue,
        sum(gross_merchandise_value)::numeric(14, 2)          as gmv,
        sum(freight_total)::numeric(14, 2)                    as freight_revenue,
        sum(item_count)                                       as items_sold,
        round(avg(order_total), 2)                            as avg_order_value,
        round(avg(review_score), 3)                           as avg_review_score,
        round(avg(delivery_days), 2)                          as avg_delivery_days

    from orders
    group by 1, 2, 3, 4

),

with_growth as (

    select
        *,
        lag(revenue)      over (order by month_start_date)     as prev_month_revenue,
        lag(revenue, 12)  over (order by month_start_date)     as same_month_last_year_revenue,
        sum(revenue)      over (order by month_start_date
                                rows between unbounded preceding and current row)
                                                               as cumulative_revenue,
        round(avg(revenue) over (order by month_start_date
                                 rows between 2 preceding and current row), 2)
                                                               as revenue_3m_moving_avg
    from monthly

)

select
    month_start_date,
    year_month,
    year_number,
    quarter_number,
    year_number::text || '-Q' || quarter_number::text          as year_quarter,

    order_count,
    active_customers,
    revenue,
    gmv,
    freight_revenue,
    items_sold,
    avg_order_value,
    avg_review_score,
    avg_delivery_days,

    prev_month_revenue,
    cumulative_revenue,
    revenue_3m_moving_avg,

    round(100 * {{ safe_divide('revenue - prev_month_revenue', 'prev_month_revenue') }}, 2)
        as mom_growth_pct,
    round(100 * {{ safe_divide('revenue - same_month_last_year_revenue',
                               'same_month_last_year_revenue') }}, 2)
        as yoy_growth_pct

from with_growth
order by month_start_date
