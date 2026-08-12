{#
    Custom generic tests. Written by hand rather than pulled from dbt_utils so
    the project builds with no package registry access (relevant for CI and for
    anyone cloning behind a proxy).
#}

{% test unique_combination_of_columns(model, combination_of_columns) %}
    {%- set columns = combination_of_columns | join(", ") -%}
    select {{ columns }}, count(*) as n_records
    from {{ model }}
    group by {{ columns }}
    having count(*) > 1
{% endtest %}


{% test expression_is_true(model, expression, where=none) %}
    select *
    from {{ model }}
    where not ({{ expression }})
    {%- if where %} and ({{ where }}){%- endif %}
{% endtest %}


{% test not_negative(model, column_name) %}
    select {{ column_name }}
    from {{ model }}
    where {{ column_name }} < 0
{% endtest %}


{#
    Row counts must line up between a fact and its source. Catches fan-out from
    a bad join - the failure mode that silently doubles revenue.
#}
{% test equal_rowcount(model, compare_model) %}
    with a as (select count(*) as n from {{ model }}),
         b as (select count(*) as n from {{ compare_model }})
    select a.n as model_rows, b.n as compare_rows
    from a cross join b
    where a.n != b.n
{% endtest %}


{#
    Guards an additive measure against drift between two models, allowing a
    small tolerance for rounding across currency columns.
#}
{% test sums_match(model, column_name, compare_model, compare_column, tolerance=0.01) %}
    with a as (select coalesce(sum({{ column_name }}), 0) as total from {{ model }}),
         b as (select coalesce(sum({{ compare_column }}), 0) as total from {{ compare_model }})
    select a.total as model_total, b.total as compare_total, a.total - b.total as difference
    from a cross join b
    where abs(a.total - b.total) > {{ tolerance }}
{% endtest %}
