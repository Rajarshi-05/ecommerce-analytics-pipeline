/*
    The source has one row per captured coordinate - roughly a million points
    across ~19k zip prefixes. Collapsing to a single centroid per prefix here
    means every downstream geo join is 1:1 and cannot fan out a fact table.

    Coordinates outside Brazil's bounding box are dropped before averaging; the
    source contains a handful of clearly bad points that would otherwise drag
    a prefix's centroid into the ocean.
*/

with source as (

    select * from {{ source('olist_raw', 'geolocation') }}

),

bounded as (

    select
        lpad(trim(geolocation_zip_code_prefix), 5, '0')  as zip_code_prefix,
        geolocation_lat                                  as latitude,
        geolocation_lng                                  as longitude,
        nullif(lower(trim(geolocation_city)), '')        as city,
        nullif(upper(trim(geolocation_state)), '')       as state
    from source
    where geolocation_lat between -33.75 and 5.27
      and geolocation_lng between -73.99 and -34.79

),

centroids as (

    select
        zip_code_prefix,
        round(avg(latitude)::numeric, 6)   as latitude,
        round(avg(longitude)::numeric, 6)  as longitude,
        count(*)                           as coordinate_count,

        -- Most frequent city/state label wins where a prefix spans a boundary.
        mode() within group (order by city)   as city,
        mode() within group (order by state)  as state
    from bounded
    group by zip_code_prefix

)

select * from centroids
