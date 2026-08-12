with source as (

    select * from {{ source('olist_raw', 'order_items') }}

),

renamed as (

    select
        -- Composite natural key hashed into a single surrogate so downstream
        -- models have one column to join and test on.
        md5(order_id || '-' || order_item_id::text)   as order_item_key,

        order_id,
        order_item_id,
        product_id,
        seller_id,

        shipping_limit_date,
        price::numeric(12, 2)                         as item_price,
        freight_value::numeric(12, 2)                 as freight_value,
        (price + freight_value)::numeric(12, 2)       as item_total,

        _loaded_at

    from source

)

select * from renamed
