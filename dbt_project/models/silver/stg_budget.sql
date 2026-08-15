-- Converges Xero's BudgetSummary report and SG-SUB's budget file upload, mapped through the
-- existing coa_mapping table (reused, not redesigned) so budgeted amounts land on the same
-- group_standard_code as actuals in rpt_budget_variance.sql. INNER join is deliberate, same
-- "fail loudly on an unmapped account" reasoning as fct_journal_line.sql -- a budget line for an
-- account with no approved mapping must not silently vanish from the variance report.
with ranked as (
    select
        *,
        row_number() over (
            partition by _source_system, entity_id, account_code, period
            order by _ingested_at desc
        ) as _dedup_rank
    from {{ ref('bronze_budget') }}
)

select
    b.entity_id,
    a.group_standard_code,
    a.account_name,
    a.account_type,
    b.period,
    b.budgeted_amount,
    b.currency
from ranked b
inner join {{ ref('coa_mapping') }} m
    on b.entity_id = m.entity_id
    and b.account_code = m.local_account_code
    and m.is_active
inner join {{ ref('dim_account_group_standard') }} a
    on m.group_standard_account_code = a.group_standard_code
where b._dedup_rank = 1
