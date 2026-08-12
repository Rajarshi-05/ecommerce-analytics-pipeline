/*
    Business question: top categories by revenue.

    Built on fact_order_items because category lives on the product, and a
    multi-item order can span categories. Order counts here are DISTINCT orders
    touching the category, so they will not sum to total orders across rows -
    that is correct, and is called out in the model description.
*/

with items as (

    select
        i.*,
        p.product_category,
        p.weight_class
    from {{ ref('fact_order_items') }} i
    inner join {{ ref('dim_products') }} p
        on i.product_key = p.product_key
    where {{ is_revenue_recognised('i') }}

),

by_category as (

    select
        product_category,

        count(*)                                     as items_sold,
        count(distinct order_id)                     as order_count,
        count(distinct customer_key)                 as customer_count,
        count(distinct product_key)                  as distinct_products,
        count(distinct seller_key)                   as distinct_sellers,

        sum(item_total)::numeric(14, 2)              as revenue,
        sum(item_price)::numeric(14, 2)              as product_revenue,
        sum(freight_value)::numeric(14, 2)           as freight_revenue,
        round(avg(item_price), 2)                    as avg_item_price,
        round(avg(freight_ratio), 4)                 as avg_freight_ratio,

        min(order_purchase_date)                     as first_sale_date,
        max(order_purchase_date)                     as last_sale_date

    from items
    group by product_category

),

category_reviews as (

    select
        p.product_category,
        round(avg(o.review_score), 3)                                       as avg_review_score,
        round(100 * avg(case when o.is_late_delivery then 1.0 else 0.0 end), 2)
                                                                            as late_delivery_pct
    from {{ ref('fact_order_items') }} i
    inner join {{ ref('dim_products') }} p on i.product_key = p.product_key
    inner join {{ ref('fact_orders') }}  o on i.order_id  = o.order_id
    where {{ is_revenue_recognised('o') }}
    group by p.product_category

)

select
    c.product_category,

    c.items_sold,
    c.order_count,
    c.customer_count,
    c.distinct_products,
    c.distinct_sellers,

    c.revenue,
    c.product_revenue,
    c.freight_revenue,
    c.avg_item_price,
    c.avg_freight_ratio,

    r.avg_review_score,
    r.late_delivery_pct,

    c.first_sale_date,
    c.last_sale_date,

    round(100 * c.revenue / nullif(sum(c.revenue) over (), 0), 2)  as revenue_share_pct,
    rank() over (order by c.revenue desc)                          as revenue_rank,
    round(100 * sum(c.revenue) over (order by c.revenue desc
                                     rows between unbounded preceding and current row)
          / nullif(sum(c.revenue) over (), 0), 2)                  as cumulative_revenue_share_pct

from by_category c
left join category_reviews r using (product_category)
order by c.revenue desc
