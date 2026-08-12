with source as (

    select * from {{ source('olist_raw', 'orders') }}

),

renamed as (

    select
        order_id,
        customer_id,
        nullif(lower(trim(order_status)), '')       as order_status,

        order_purchase_timestamp,
        order_approved_at,
        order_delivered_carrier_date,
        order_delivered_customer_date,
        order_estimated_delivery_date,

        _loaded_at

    from source

)

select * from renamed
