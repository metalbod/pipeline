with spine as (
    {{ dbt_utils.date_spine(
        datepart="month",
        start_date="cast('2015-01-01' as date)",
        end_date="cast('2035-01-01' as date)"
    ) }}
)

select
    {{ dbt_utils.generate_surrogate_key(['date_month']) }} as period_key,
    extract(year from date_month)::integer as fiscal_year,
    extract(month from date_month)::integer as fiscal_period,
    date_month as period_start,
    (date_month + interval '1 month' - interval '1 day')::date as period_end,
    false as is_closed
from spine
