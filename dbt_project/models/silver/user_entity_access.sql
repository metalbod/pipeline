-- Governed user->entity access table (Phase 3 RLS). Superset's Row Level Security filter on the
-- per-entity Gold datasets references this table directly by username -- see
-- ops/superset/setup_superset.py. GROUP_FINANCE_OWNER rows have a blank entity_id (unrestricted);
-- REGIONAL_CONTROLLER rows scope to exactly one entity_id.
select
    username,
    role,
    entity_id,
    effective_from,
    effective_to,
    approved_by,
    approved_at
from {{ ref('seed_user_entity_access') }}
