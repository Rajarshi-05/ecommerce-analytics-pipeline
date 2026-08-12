/*
    Business question: does late delivery actually cause worse reviews, or is it
    just correlated with something else?

    Produces the single table the "one real insight" story is built on: average
    review score and 1-star rate for on-time versus late orders, sliced by how
    late, plus the Pearson correlation between days-late and review score.

    Grain: one row per lateness bucket, with an 'ALL' row carrying the
    correlation coefficient over the full delivered population.
*/

with delivered as (

    select
        order_id,
        review_score,
        delivery_days,
        is_late_delivery,
        order_total,
        -- Positive = delivered after the promise date.
        (order_delivered_customer_date::date - order_estimated_delivery_date::date)
            as days_late
    from {{ ref('fact_orders') }}
    where is_delivered
      and order_delivered_customer_date is not null
      and review_score is not null

),

bucketed as (

    select
        *,
        case
            when days_late <= -10 then '10+ days early'
            when days_late <   0  then '1-9 days early'
            when days_late =  0   then 'on the promise date'
            when days_late <=  3  then '1-3 days late'
            when days_late <=  7  then '4-7 days late'
            when days_late <= 14  then '8-14 days late'
            else                       '15+ days late'
        end as lateness_bucket,
        case
            when days_late <= -10 then 1 when days_late < 0 then 2
            when days_late = 0    then 3 when days_late <= 3 then 4
            when days_late <= 7   then 5 when days_late <= 14 then 6
            else 7
        end as bucket_order
    from delivered

),

by_bucket as (

    select
        lateness_bucket,
        bucket_order,
        count(*)                                                    as order_count,
        round(avg(review_score), 3)                                 as avg_review_score,
        round(100.0 * count(*) filter (where review_score = 1) / count(*), 2)
                                                                    as one_star_pct,
        round(100.0 * count(*) filter (where review_score >= 4) / count(*), 2)
                                                                    as four_plus_star_pct,
        round(avg(delivery_days), 2)                                as avg_delivery_days,
        sum(order_total)::numeric(14, 2)                             as revenue,
        null::numeric                                               as correlation_coefficient
    from bucketed
    group by lateness_bucket, bucket_order

),

overall as (

    select
        'ALL DELIVERED'                                             as lateness_bucket,
        99                                                          as bucket_order,
        count(*)                                                    as order_count,
        round(avg(review_score), 3)                                 as avg_review_score,
        round(100.0 * count(*) filter (where review_score = 1) / count(*), 2)
                                                                    as one_star_pct,
        round(100.0 * count(*) filter (where review_score >= 4) / count(*), 2)
                                                                    as four_plus_star_pct,
        round(avg(delivery_days), 2)                                as avg_delivery_days,
        sum(order_total)::numeric(14, 2)                             as revenue,
        round(corr(days_late, review_score)::numeric, 4)            as correlation_coefficient
    from bucketed

)

select
    lateness_bucket,
    order_count,
    avg_review_score,
    one_star_pct,
    four_plus_star_pct,
    avg_delivery_days,
    revenue,
    correlation_coefficient,
    round(100.0 * order_count / nullif(sum(order_count)
        filter (where bucket_order < 99) over (), 0), 2)            as share_of_delivered_pct
from (
    select * from by_bucket
    union all
    select * from overall
) combined
order by bucket_order
