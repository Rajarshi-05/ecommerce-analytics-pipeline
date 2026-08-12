/*
    Business question: customer segments via RFM.

    This is the deterministic, rules-based segmentation - quintile scores on
    Recency, Frequency and Monetary value, mapped to named segments. It is the
    baseline the KMeans clustering in `ml/segmentation.py` is compared against;
    having both is deliberate, because a business stakeholder can act on
    "champions vs at-risk" immediately, while the unsupervised clusters are the
    thing that has to earn its keep.

    Frequency is low across the board in this dataset (most customers order
    once), so quintiles collapse. Frequency is therefore scored on a fixed
    ladder rather than ntile, which keeps the segment definitions meaningful.
*/

with orders as (

    select * from {{ ref('fact_orders') }}
    where {{ is_revenue_recognised() }}

),

reference as (

    select max(order_purchase_date) as as_of_date
    from orders

),

customer_metrics as (

    select
        o.customer_key,
        (r.as_of_date - max(o.order_purchase_date))     as recency_days,
        count(*)                                        as frequency,
        sum(o.order_total)::numeric(14, 2)              as monetary,
        round(avg(o.order_total), 2)                    as avg_order_value,
        min(o.order_purchase_date)                      as first_order_date,
        max(o.order_purchase_date)                      as last_order_date,
        round(avg(o.review_score), 2)                   as avg_review_score,
        sum(o.item_count)                               as total_items,
        r.as_of_date
    from orders o
    cross join reference r
    group by o.customer_key, r.as_of_date

),

scored as (

    select
        *,
        -- Lower recency is better, so the ntile is inverted.
        6 - ntile(5) over (order by recency_days)          as recency_score,
        ntile(5) over (order by monetary)                  as monetary_score,
        case
            when frequency >= 5 then 5
            when frequency = 4  then 4
            when frequency = 3  then 3
            when frequency = 2  then 2
            else 1
        end                                                as frequency_score
    from customer_metrics

)

select
    s.customer_key,
    c.customer_state,
    c.customer_city,
    c.geography_key,
    c.acquisition_cohort_month,

    s.as_of_date,
    s.recency_days,
    s.frequency,
    s.monetary,
    s.avg_order_value,
    s.total_items,
    s.avg_review_score,
    s.first_order_date,
    s.last_order_date,

    s.recency_score,
    s.frequency_score,
    s.monetary_score,
    (s.recency_score + s.frequency_score + s.monetary_score)   as rfm_score,
    s.recency_score::text || s.frequency_score::text
        || s.monetary_score::text                              as rfm_cell,

    case
        when s.recency_score >= 4 and s.frequency_score >= 4                       then 'Champions'
        when s.recency_score >= 3 and s.frequency_score >= 3 and s.monetary_score >= 4
                                                                                   then 'Loyal'
        when s.recency_score >= 4 and s.frequency_score <= 2 and s.monetary_score >= 4
                                                                                   then 'Big Spenders'
        when s.recency_score >= 4 and s.frequency_score <= 2                       then 'New / Promising'
        when s.recency_score = 3                                                   then 'Needs Attention'
        when s.recency_score = 2 and s.monetary_score >= 4                         then 'At Risk'
        when s.recency_score = 2                                                   then 'Hibernating'
        when s.monetary_score >= 4                                                 then 'Lost High Value'
        else                                                                            'Lost'
    end                                                        as rfm_segment,

    -- Coarse roll-up for the headline dashboard tile.
    case
        when s.recency_score >= 4 then 'Active'
        when s.recency_score >= 2 then 'Cooling'
        else                           'Lost'
    end                                                        as lifecycle_stage

from scored s
inner join {{ ref('dim_customers') }} c
    on s.customer_key = c.customer_key
