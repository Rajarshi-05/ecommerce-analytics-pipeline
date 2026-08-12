/*
    Business question: on-time versus delayed delivery, and how that correlates
    with review score.

    The grain is one row per (month, delivery bucket) so the dashboard can show
    both the distribution of delivery speed and the satisfaction gap between
    on-time and late orders over time.
*/

with delivered as (

    select * from {{ ref('fact_orders') }}
    where is_delivered
      and order_delivered_customer_date is not null

),

by_month_bucket as (

    select
        date_trunc('month', order_purchase_date)::date         as month_start_date,
        to_char(order_purchase_date, 'YYYY-MM')                as year_month,
        delivery_speed_bucket,
        is_late_delivery,

        count(*)                                               as order_count,
        sum(order_total)::numeric(14, 2)                        as revenue,
        round(avg(delivery_days), 2)                            as avg_delivery_days,
        round(avg(days_early_vs_estimate), 2)                   as avg_days_early_vs_estimate,
        round(avg(review_score), 3)                             as avg_review_score,
        count(*) filter (where review_score is not null)        as reviewed_orders,
        count(*) filter (where review_score <= 2)               as poor_reviews,
        count(*) filter (where review_score >= 4)               as good_reviews

    from delivered
    group by 1, 2, 3, 4

)

select
    month_start_date,
    year_month,
    delivery_speed_bucket,
    is_late_delivery,

    order_count,
    revenue,
    avg_delivery_days,
    avg_days_early_vs_estimate,
    avg_review_score,
    reviewed_orders,
    poor_reviews,
    good_reviews,

    round(100 * {{ safe_divide('poor_reviews', 'reviewed_orders') }}, 2)   as poor_review_pct,
    round(100 * {{ safe_divide('good_reviews', 'reviewed_orders') }}, 2)   as good_review_pct,

    round(100 * order_count
          / nullif(sum(order_count) over (partition by month_start_date), 0), 2)
                                                                            as share_of_month_pct

from by_month_bucket
order by month_start_date, delivery_speed_bucket
