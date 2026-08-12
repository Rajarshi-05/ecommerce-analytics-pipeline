/*
    Conformed date dimension, generated from the observed order history rather
    than hard-coded, padded a year past the last order so forecast rows join
    cleanly.

    Built with generate_series instead of a package macro to keep the project
    dependency-free.
*/

with bounds as (

    select
        date_trunc('year', min(order_purchase_timestamp))::date          as start_date,
        (date_trunc('year', max(order_purchase_timestamp))
            + interval '2 year' - interval '1 day')::date                as end_date
    from {{ ref('stg_orders') }}

),

spine as (

    select generate_series(start_date, end_date, interval '1 day')::date as date_day
    from bounds

)

select
    date_day,

    -- Integer surrogate (YYYYMMDD) - the conventional date-dimension key.
    (to_char(date_day, 'YYYYMMDD'))::int                          as date_key,

    extract(year    from date_day)::int                           as year_number,
    extract(quarter from date_day)::int                           as quarter_number,
    extract(month   from date_day)::int                           as month_number,
    extract(day     from date_day)::int                           as day_of_month,
    extract(week    from date_day)::int                           as iso_week_number,
    extract(isodow  from date_day)::int                           as day_of_week,

    to_char(date_day, 'YYYY-MM')                                  as year_month,
    to_char(date_day, 'Mon')                                      as month_name_short,
    to_char(date_day, 'Month')                                    as month_name,
    to_char(date_day, 'Dy')                                       as day_name_short,
    'Q' || extract(quarter from date_day)::text                   as quarter_name,
    extract(year from date_day)::text
        || '-Q' || extract(quarter from date_day)::text           as year_quarter,

    date_trunc('week',    date_day)::date                         as week_start_date,
    date_trunc('month',   date_day)::date                         as month_start_date,
    (date_trunc('month', date_day) + interval '1 month'
        - interval '1 day')::date                                 as month_end_date,
    date_trunc('quarter', date_day)::date                         as quarter_start_date,
    date_trunc('year',    date_day)::date                         as year_start_date,

    extract(isodow from date_day) in (6, 7)                       as is_weekend,
    date_day = (date_trunc('month', date_day)
        + interval '1 month' - interval '1 day')::date            as is_month_end

from spine
