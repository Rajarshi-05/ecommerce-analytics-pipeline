/*
    Business question: repeat purchase rate and cohort retention.

    Grain: one row per (acquisition cohort month, months since acquisition).

    A caveat worth stating out loud when presenting this: Olist is a
    marketplace with a very low repeat rate (~3% of customers order more than
    once), so the retention curve is near-flat. That is a real finding about the
    business, not a bug in the model - and it is why the headline
    recommendation from this project is acquisition-cost driven rather than
    retention driven.
*/

with orders as (

    select * from {{ ref('fact_orders') }}
    where {{ is_revenue_recognised() }}

),

customer_first_order as (

    select
        customer_key,
        min(date_trunc('month', order_purchase_date))::date as cohort_month
    from orders
    group by customer_key

),

order_activity as (

    select
        o.customer_key,
        f.cohort_month,
        date_trunc('month', o.order_purchase_date)::date     as activity_month,
        o.order_total
    from orders o
    inner join customer_first_order f using (customer_key)

),

cohort_sizes as (

    select cohort_month, count(*) as cohort_size
    from customer_first_order
    group by cohort_month

),

cohort_activity as (

    select
        cohort_month,
        activity_month,
        (extract(year from age(activity_month, cohort_month)) * 12
            + extract(month from age(activity_month, cohort_month)))::int
                                                              as months_since_acquisition,
        count(distinct customer_key)                          as active_customers,
        count(*)                                              as order_count,
        sum(order_total)::numeric(14, 2)                       as revenue
    from order_activity
    group by 1, 2, 3

)

select
    a.cohort_month,
    to_char(a.cohort_month, 'YYYY-MM')                        as cohort_label,
    a.activity_month,
    a.months_since_acquisition,

    s.cohort_size,
    a.active_customers,
    a.order_count,
    a.revenue,

    round(100.0 * a.active_customers / nullif(s.cohort_size, 0), 2)   as retention_pct,
    round(a.revenue / nullif(s.cohort_size, 0), 2)                    as revenue_per_cohort_customer

from cohort_activity a
inner join cohort_sizes s using (cohort_month)
order by a.cohort_month, a.months_since_acquisition
