with source as (

    select * from {{ source('olist_raw', 'products') }}

),

translation as (

    select * from {{ ref('stg_product_category_translation') }}

),

renamed as (

    select
        p.product_id,

        nullif(lower(trim(p.product_category_name)), '')        as product_category_name_pt,

        -- Fall back to the raw Portuguese name when the lookup has no entry, so
        -- revenue is never silently dropped from category reporting.
        coalesce(
            t.product_category_name_english,
            nullif(lower(trim(p.product_category_name)), ''),
            'unknown'
        )                                                       as product_category,

        -- Source column names are misspelled ('lenght'); corrected here.
        p.product_name_lenght                                   as product_name_length,
        p.product_description_lenght                            as product_description_length,
        p.product_photos_qty,

        p.product_weight_g,
        p.product_length_cm,
        p.product_height_cm,
        p.product_width_cm,

        (p.product_length_cm * p.product_height_cm * p.product_width_cm)
                                                                as product_volume_cm3,

        p._loaded_at

    from source p
    left join translation t
        on nullif(lower(trim(p.product_category_name)), '') = t.product_category_name

)

select * from renamed
