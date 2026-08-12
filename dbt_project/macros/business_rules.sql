{#
    Business rules that more than one model depends on. Defining them once here
    rather than repeating the predicate in every analytics model means a change
    to what counts as revenue is a one-line change, and the dbt docs DAG shows
    exactly which models it affects.
#}

{#
    Revenue recognition: an order counts once the marketplace has committed to
    it. Cancelled and unavailable orders never ship and never bill, so including
    them would overstate every revenue figure in the project.
#}
{% macro is_revenue_recognised(relation_alias=none) %}
    {%- set prefix = (relation_alias ~ '.') if relation_alias else '' -%}
    {{ prefix }}order_status not in ('canceled', 'unavailable')
{% endmacro %}


{#
    RFM scoring uses the latest purchase in the dataset as "today". The Olist
    extract ends in 2018, so scoring against the real current date would put
    every customer in the "lost" bucket and make the segmentation meaningless.
#}
{% macro rfm_reference_date() %}
    (select max(order_purchase_date) from {{ ref('fact_orders') }})
{% endmacro %}


{#
    Safe division that returns NULL instead of raising on a zero denominator.
    Used wherever a rate is computed over a filtered subset that can be empty.
#}
{% macro safe_divide(numerator, denominator) %}
    case when ({{ denominator }}) = 0 then null
         else ({{ numerator }})::numeric / ({{ denominator }})
    end
{% endmacro %}
