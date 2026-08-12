/*
    Grain: one row per order.

    Every join here is deliberately many-to-one against a pre-aggregated CTE or
    a dimension, never against a finer grain. That is what keeps `order_total`
    additive - joining stg_order_items directly would fan the row out per item
    and inflate revenue by the average basket size.
*/

{{
    config(
        materialized='table',
        indexes=[
            {'columns': ['order_id'], 'unique': True},
            {'columns': ['customer_key']},
            {'columns': ['order_date_key']},
            {'columns': ['order_purchase_date']},
        ],
    )
}}

with orders as (

    select * from {{ ref('stg_orders') }}

),

customers as (

    select * from {{ ref('stg_customers') }}

),

financials as (

    select * from {{ ref('int_order_financials') }}

),

payments as (

    select * from {{ ref('int_order_payments_summary') }}

),

reviews as (

    select * from {{ ref('stg_order_reviews') }}

),

joined as (

    select
        o.order_id,

        -- Foreign keys
        c.customer_unique_id                                     as customer_key,
        c.customer_id                                            as source_customer_id,
        c.customer_zip_code_prefix                               as geography_key,
        (to_char(o.order_purchase_timestamp, 'YYYYMMDD'))::int   as order_date_key,
        (to_char(o.order_delivered_customer_date, 'YYYYMMDD'))::int
                                                                 as delivered_date_key,

        -- Degenerate attributes
        o.order_status,
        c.customer_state,
        c.customer_city,

        -- Event timestamps
        o.order_purchase_timestamp,
        o.order_purchase_timestamp::date                         as order_purchase_date,
        o.order_approved_at,
        o.order_delivered_carrier_date,
        o.order_delivered_customer_date,
        o.order_estimated_delivery_date,

        -- Financial measures
        coalesce(f.item_count, 0)                                as item_count,
        coalesce(f.distinct_product_count, 0)                    as distinct_product_count,
        coalesce(f.distinct_seller_count, 0)                     as distinct_seller_count,
        coalesce(f.gross_merchandise_value, 0)::numeric(12, 2)   as gross_merchandise_value,
        coalesce(f.freight_total, 0)::numeric(12, 2)             as freight_total,
        coalesce(f.order_total, 0)::numeric(12, 2)               as order_total,
        f.avg_item_price,
        p.paid_total,
        p.primary_payment_type,
        p.primary_payment_installments,
        coalesce(p.payment_count, 0)                             as payment_count,
        coalesce(p.is_split_payment, false)                      as is_split_payment,

        -- Review measures
        r.review_score,
        r.review_sentiment_label,
        coalesce(r.has_comment, false)                           as has_review_comment,

        -- Delivery measures. Nulls are intentional for undelivered orders -
        -- coalescing them to 0 would make on-time rate look better than it is.
        case
            when o.order_delivered_customer_date is null then null
            else (o.order_delivered_customer_date::date - o.order_purchase_timestamp::date)
        end                                                      as delivery_days,
        case
            when o.order_delivered_customer_date is null then null
            else (o.order_estimated_delivery_date::date - o.order_delivered_customer_date::date)
        end                                                      as days_early_vs_estimate,
        case
            when o.order_approved_at is null then null
            else round(extract(epoch from (o.order_approved_at - o.order_purchase_timestamp))
                       / 3600.0, 2)
        end                                                      as approval_hours,

        o.order_status = 'delivered'                             as is_delivered,
        o.order_status = 'canceled'                              as is_canceled

    from orders o
    inner join customers  c using (customer_id)
    left  join financials f using (order_id)
    left  join payments   p using (order_id)
    left  join reviews    r using (order_id)

)

select
    *,

    case
        when order_delivered_customer_date is null then null
        else order_delivered_customer_date > order_estimated_delivery_date
    end                                                          as is_late_delivery,

    case
        when delivery_days is null      then 'not_delivered'
        when delivery_days <= 3         then '0-3 days'
        when delivery_days <= 7         then '4-7 days'
        when delivery_days <= 14        then '8-14 days'
        when delivery_days <= 30        then '15-30 days'
        else                                 '30+ days'
    end                                                          as delivery_speed_bucket,

    -- Reconciliation flag: payments should cover the basket. Small mismatches
    -- exist in the source (vouchers, rounding), so this is surfaced as a column
    -- for the analyst rather than enforced as a hard test.
    case
        when paid_total is null or order_total = 0 then null
        else round(paid_total - order_total, 2)
    end                                                          as payment_variance

from joined
