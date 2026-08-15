select
    currency_code,
    fiscal_year,
    fiscal_period,
    rate_type,
    rate_to_group_currency,
    source,
    approved_by,
    approved_at
from {{ ref('seed_dim_fx_rate') }}
