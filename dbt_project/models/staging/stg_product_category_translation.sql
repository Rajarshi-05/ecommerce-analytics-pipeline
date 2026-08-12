with source as (

    select * from {{ source('olist_raw', 'product_category_translation') }}

),

renamed as (

    select
        nullif(lower(trim(product_category_name)), '')          as product_category_name,
        nullif(lower(trim(product_category_name_english)), '')  as product_category_name_english,
        _loaded_at
    from source
    where product_category_name is not null

)

select * from renamed
