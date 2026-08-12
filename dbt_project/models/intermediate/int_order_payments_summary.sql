/*
    One row per order from the payments table, with the split-payment case
    resolved: `primary_payment_type` is whichever method covered the largest
    share of the order, so payment-mix reporting stays at order grain.
*/

with payments as (

    select * from {{ ref('stg_order_payments') }}

),

ranked as (

    select
        *,
        row_number() over (
            partition by order_id
            order by payment_value desc, payment_sequential
        ) as payment_rank
    from payments

),

aggregated as (

    select
        order_id,
        count(*)                                 as payment_count,
        sum(payment_value)::numeric(12, 2)       as paid_total,
        max(payment_installments)                as max_installments,
        bool_or(payment_type = 'voucher')        as used_voucher,
        bool_or(payment_type = 'credit_card')    as used_credit_card
    from payments
    group by order_id

)

select
    a.order_id,
    a.payment_count,
    a.paid_total,
    a.max_installments,
    a.used_voucher,
    a.used_credit_card,
    r.payment_type            as primary_payment_type,
    r.payment_installments    as primary_payment_installments,
    a.payment_count > 1       as is_split_payment
from aggregated a
left join ranked r
    on a.order_id = r.order_id
   and r.payment_rank = 1
