-- Override dbt default schema name generation.
-- Default: concatenates profile schema + model schema → "gold_silver", "gold_gold"
-- This macro: use model schema directly (ignore profile schema).
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
