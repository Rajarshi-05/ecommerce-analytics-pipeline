with products as (

    select * from {{ ref('stg_products') }}

)

select
    product_id                                  as product_key,
    product_id,

    product_category,
    product_category_name_pt,

    product_name_length,
    product_description_length,
    product_photos_qty,

    product_weight_g,
    product_length_cm,
    product_height_cm,
    product_width_cm,
    product_volume_cm3,

    -- Shipping-cost driver: volumetric weight at the 5000 cm3/kg divisor most
    -- Brazilian carriers use, versus actual weight.
    case
        when product_volume_cm3 is null then null
        else greatest(product_volume_cm3 / 5000.0, coalesce(product_weight_g, 0) / 1000.0)
    end::numeric(10, 3)                         as chargeable_weight_kg,

    case
        when product_weight_g is null            then 'unknown'
        when product_weight_g < 500              then 'light'
        when product_weight_g < 2000             then 'medium'
        when product_weight_g < 10000            then 'heavy'
        else                                          'oversized'
    end                                         as weight_class,

    product_category = 'unknown'                as is_uncategorised

from products
