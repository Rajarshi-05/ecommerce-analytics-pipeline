{{
    config(
        materialized='view',
    )
}}

/*
    Resolves two known defects in the source reviews file:

      1. `review_id` is not unique (~800 rows in the Kaggle extract share an id
         with a different order).
      2. A small number of orders carry more than one review.

    fact_orders needs at most one review per order to stay at order grain, so
    the model de-duplicates on order_id and keeps the most recently answered
    review. Picking "latest" rather than "best" or "worst" is deliberate: it is
    the reviewer's final word, and it does not bias the delivery-vs-satisfaction
    analysis in either direction.
*/

with source as (

    select * from {{ source('olist_raw', 'order_reviews') }}

),

cleaned as (

    select
        review_id,
        order_id,
        review_score::int                                    as review_score,
        nullif(btrim(review_comment_title), '')              as review_comment_title,
        nullif(btrim(review_comment_message), '')            as review_comment_message,
        review_creation_date,
        review_answer_timestamp,
        _loaded_at
    from source
    where order_id is not null
      and review_score between 1 and 5

),

deduplicated as (

    select
        *,
        row_number() over (
            partition by order_id
            order by
                review_answer_timestamp desc nulls last,
                review_creation_date     desc nulls last,
                review_id
        ) as review_rank
    from cleaned

)

select
    review_id,
    order_id,
    review_score,
    review_comment_title,
    review_comment_message,
    review_creation_date,
    review_answer_timestamp,

    (review_comment_message is not null)                      as has_comment,
    coalesce(length(review_comment_message), 0)               as comment_length,
    case
        when review_score >= 4 then 'positive'
        when review_score = 3  then 'neutral'
        else 'negative'
    end                                                       as review_sentiment_label,

    _loaded_at

from deduplicated
where review_rank = 1
