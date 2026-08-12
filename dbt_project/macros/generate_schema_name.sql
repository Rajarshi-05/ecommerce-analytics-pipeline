{#
    dbt's default prefixes the target schema onto any custom schema, which would
    produce `public_marts`. The warehouse already has purpose-built schemas
    (staging / marts / analytics) created by the Postgres bootstrap, so use the
    custom name verbatim and fall back to the profile's schema when a model
    doesn't declare one.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema | trim }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
