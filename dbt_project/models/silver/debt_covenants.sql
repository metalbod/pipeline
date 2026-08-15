-- Governed debt-covenant terms (Finance-maintained), same passthrough pattern as
-- intercompany_accounts.sql. Empty today -- no real debt facility exists yet (see
-- seed_debt_covenants.csv header comment context in the Phase 4 plan).
select
    entity_id,
    facility_name,
    covenant_type,
    threshold_value,
    currency,
    effective_from,
    effective_to,
    approved_by,
    approved_at
from {{ ref('seed_debt_covenants') }}
