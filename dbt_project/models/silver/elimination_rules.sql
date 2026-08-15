select
    entity_id,
    counterparty_entity_id,
    effective_from,
    effective_to,
    approved_by,
    approved_at
from {{ ref('seed_elimination_rules') }}
