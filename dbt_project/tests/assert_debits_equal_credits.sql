-- Double-entry gate (ARCHITECTURE.md §7): every journal batch must balance. Enforced as a hard
-- gate, not a warning -- CLAUDE.md: never relax or skip to make a build pass. Returns offending
-- rows (a dbt singular test fails if it returns any rows).
select
    entity_id,
    journal_id,
    sum(debit_amount) as total_debit,
    sum(credit_amount) as total_credit
from {{ ref('stg_journal_lines') }}
group by entity_id, journal_id
having abs(sum(debit_amount) - sum(credit_amount)) > 0.01
