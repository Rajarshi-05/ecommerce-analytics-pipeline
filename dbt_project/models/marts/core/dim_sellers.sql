with sellers as (

    select * from {{ ref('stg_sellers') }}

),

geography as (

    select * from {{ ref('dim_geography') }}

)

select
    s.seller_id                     as seller_key,
    s.seller_id,

    s.seller_zip_code_prefix        as geography_key,
    s.seller_zip_code_prefix,
    s.seller_city,
    s.seller_state,
    g.region                        as seller_region,
    g.latitude                      as seller_latitude,
    g.longitude                     as seller_longitude

from sellers s
left join geography g
    on s.seller_zip_code_prefix = g.geography_key
