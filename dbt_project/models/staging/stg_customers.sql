with source as (

    select * from {{ source('olist_raw', 'customers') }}

),

renamed as (

    select
        customer_id,
        customer_unique_id,

        -- Source drops leading zeros on CEP prefixes; pad so joins to
        -- geolocation and sellers line up.
        lpad(trim(customer_zip_code_prefix), 5, '0')            as customer_zip_code_prefix,
        nullif(lower(trim(customer_city)), '')                  as customer_city,
        nullif(upper(trim(customer_state)), '')                 as customer_state,

        _loaded_at

    from source

)

select * from renamed
