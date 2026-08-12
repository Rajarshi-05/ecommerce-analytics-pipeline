/*
    Conformed geography dimension at zip-prefix grain, shared by customers and
    sellers. Region mapping follows the IBGE's five macro-regions.
*/

with geo as (

    select * from {{ ref('stg_geolocation') }}

),

-- Zip prefixes that appear on a customer or seller but are absent from the
-- geolocation file still need a dimension row, or the fact join would drop them.
referenced_prefixes as (

    select distinct customer_zip_code_prefix as zip_code_prefix,
                    customer_city           as city,
                    customer_state          as state
    from {{ ref('stg_customers') }}

    union

    select distinct seller_zip_code_prefix, seller_city, seller_state
    from {{ ref('stg_sellers') }}

),

combined as (

    select
        r.zip_code_prefix,
        coalesce(g.city, r.city)     as city,
        coalesce(g.state, r.state)   as state,
        g.latitude,
        g.longitude,
        coalesce(g.coordinate_count, 0) as coordinate_count
    from referenced_prefixes r
    left join geo g using (zip_code_prefix)

),

deduplicated as (

    select
        zip_code_prefix,
        mode() within group (order by city)  as city,
        mode() within group (order by state) as state,
        avg(latitude)::numeric(10, 6)        as latitude,
        avg(longitude)::numeric(10, 6)       as longitude,
        max(coordinate_count)                as coordinate_count
    from combined
    group by zip_code_prefix

)

select
    zip_code_prefix                          as geography_key,
    zip_code_prefix,
    city,
    state,
    latitude,
    longitude,
    coordinate_count,
    latitude is not null                     as has_coordinates,

    case state
        when 'AC' then 'North'     when 'AP' then 'North'
        when 'AM' then 'North'     when 'PA' then 'North'
        when 'RO' then 'North'     when 'RR' then 'North'
        when 'TO' then 'North'
        when 'AL' then 'Northeast' when 'BA' then 'Northeast'
        when 'CE' then 'Northeast' when 'MA' then 'Northeast'
        when 'PB' then 'Northeast' when 'PE' then 'Northeast'
        when 'PI' then 'Northeast' when 'RN' then 'Northeast'
        when 'SE' then 'Northeast'
        when 'DF' then 'Central-West' when 'GO' then 'Central-West'
        when 'MT' then 'Central-West' when 'MS' then 'Central-West'
        when 'ES' then 'Southeast' when 'MG' then 'Southeast'
        when 'RJ' then 'Southeast' when 'SP' then 'Southeast'
        when 'PR' then 'South'     when 'RS' then 'South'
        when 'SC' then 'South'
        else 'Unknown'
    end                                      as region

from deduplicated
