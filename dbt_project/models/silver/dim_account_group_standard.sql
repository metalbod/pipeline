select
    {{ dbt_utils.generate_surrogate_key(['group_standard_code', 'effective_from']) }} as account_key,
    group_standard_code,
    account_name,
    account_type,
    account_subtype,
    effective_from,
    effective_to
from {{ ref('seed_dim_account_group_standard') }}
