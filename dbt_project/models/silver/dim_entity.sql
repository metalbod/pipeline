select
    entity_id,
    entity_name,
    parent_entity_id,
    ownership_pct,
    functional_currency,
    country,
    is_consolidated,
    effective_from,
    effective_to
from {{ ref('seed_dim_entity') }}
