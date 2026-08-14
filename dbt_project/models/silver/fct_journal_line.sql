-- Atomic, auditable grain (ARCHITECTURE.md §6.2) -- every consolidated number traces back to a
-- SUM() over rows here. group_currency_amount/fx_rate_used/is_intercompany/counterparty_entity_id
-- are genuinely Phase 2 columns (FX translation, consolidation) -- left null/false, not fabricated.
--
-- coa_mapping/dim_account_group_standard are INNER joins on purpose: a local account with no
-- approved mapping must not silently appear in the fact table (ARCHITECTURE.md §6.1's "fail
-- loudly, not silently dropped"). tests/assert_no_unmapped_accounts.sql is the loud failure --
-- if this join drops rows, that test catches it and fails the build.
select
    {{ dbt_utils.generate_surrogate_key(['s._source_system', 's.entity_id', 's.journal_id', 's.line_no']) }} as journal_line_key,
    s.entity_id,
    a.account_key,
    p.period_key,
    s.journal_id,
    s.line_no,
    s.debit_amount,
    s.credit_amount,
    coalesce(s.currency, e.functional_currency) as transaction_currency,
    (s.debit_amount - s.credit_amount) as functional_currency_amount,
    cast(null as double) as group_currency_amount,
    cast(null as double) as fx_rate_used,
    s._source_system as source_system,
    s.posted_at,
    false as is_intercompany,
    cast(null as varchar) as counterparty_entity_id
from {{ ref('stg_journal_lines') }} s
inner join {{ ref('dim_entity') }} e
    on s.entity_id = e.entity_id
inner join {{ ref('coa_mapping') }} m
    on s.entity_id = m.entity_id
    and s.account_code = m.local_account_code
    and m.is_active
inner join {{ ref('dim_account_group_standard') }} a
    on m.group_standard_account_code = a.group_standard_code
inner join {{ ref('dim_period') }} p
    on s.posted_at >= p.period_start
    and s.posted_at <= p.period_end
