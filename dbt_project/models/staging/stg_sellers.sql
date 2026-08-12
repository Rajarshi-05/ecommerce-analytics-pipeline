with source as (

    select * from {{ source('olist_raw', 'sellers') }}

),

renamed as (

    select
        seller_id,
        lpad(trim(seller_zip_code_prefix), 5, '0')  as seller_zip_code_prefix,
        nullif(lower(trim(seller_city)), '')        as seller_city,
        nullif(upper(trim(seller_state)), '')       as seller_state,
        _loaded_at
    from source

)

select * from renamed
