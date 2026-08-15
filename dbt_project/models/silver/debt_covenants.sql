-- Governed debt-covenant terms (Finance-maintained), same passthrough pattern as
-- intercompany_accounts.sql. One row per entity's facility (Phase 5 demo data) --
-- terms only (threshold, effective dates), not a transaction-level facility ledger.
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
