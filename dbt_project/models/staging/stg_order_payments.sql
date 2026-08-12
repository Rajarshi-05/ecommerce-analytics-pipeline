with source as (

    select * from {{ source('olist_raw', 'order_payments') }}

),

renamed as (

    select
        md5(order_id || '-' || payment_sequential::text)  as order_payment_key,

        order_id,
        payment_sequential,
        nullif(lower(trim(payment_type)), '')            as payment_type,

        -- 'not_defined' appears in the source for a handful of zero-value rows.
        case
            when lower(trim(payment_type)) = 'not_defined' then null
            else nullif(lower(trim(payment_type)), '')
        end                                              as payment_method,

        -- 0 installments is a source artefact meaning "paid in one go".
        greatest(coalesce(payment_installments, 1), 1)   as payment_installments,
        payment_value::numeric(12, 2)                    as payment_value,

        _loaded_at

    from source

)

select * from renamed
