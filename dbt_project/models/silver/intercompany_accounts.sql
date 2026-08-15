select
    entity_id,
    local_account_code,
    counterparty_entity_id,
    effective_from,
    effective_to,
    approved_by,
    approved_at
from {{ ref('seed_intercompany_accounts') }}
