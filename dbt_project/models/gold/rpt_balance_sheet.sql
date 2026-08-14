-- Unconsolidated balance sheet per entity/period (ARCHITECTURE.md §3: what Streamlit queries
-- directly, no ad hoc SQL against Silver). Phase 1 has no period-close journal entries, so
-- current-period revenue/expense sits unclosed -- a computed (not governed-COA) "Current Period
-- Earnings" row folds it into equity for display, matching how any interim/unaudited balance
-- sheet is normally presented. This is a presentation convenience only: it is NOT written to
-- dim_account_group_standard/coa_mapping, and tests/assert_balance_sheet_equation.sql verifies
-- the equation independently of this report's presentation choice.
--
-- `amount` is naturalized (normal-balance-positive), not the raw debit-minus-credit signed
-- value: ASSET is debit-normal so it's unchanged, LIABILITY/EQUITY are credit-normal so their
-- signed closing_balance is negated. Without this, liabilities would display as negative
-- numbers and silently disagree in sign with the already-naturalized computed earnings row.
with balance_sheet_rows as (
    select
        b.entity_id,
        b.period_key,
        a.group_standard_code,
        a.account_name,
        a.account_type,
        a.account_subtype,
        case when a.account_type = 'ASSET' then b.closing_balance else -b.closing_balance end as amount
    from {{ ref('fct_balance') }} b
    inner join {{ ref('dim_account_group_standard') }} a on b.account_key = a.account_key
    where a.account_type in ('ASSET', 'LIABILITY', 'EQUITY')

    union all

    select
        b.entity_id,
        b.period_key,
        cast(null as varchar) as group_standard_code,
        'Current Period Earnings (unaudited)' as account_name,
        'EQUITY' as account_type,
        'Retained Earnings' as account_subtype,
        -sum(b.closing_balance) as amount
    from {{ ref('fct_balance') }} b
    inner join {{ ref('dim_account_group_standard') }} a on b.account_key = a.account_key
    where a.account_type in ('REVENUE', 'EXPENSE')
    group by b.entity_id, b.period_key
)

select
    r.entity_id,
    e.entity_name,
    p.fiscal_year,
    p.fiscal_period,
    p.period_start,
    p.period_end,
    r.group_standard_code,
    r.account_name,
    r.account_type,
    r.account_subtype,
    r.amount,
    e.functional_currency
from balance_sheet_rows r
inner join {{ ref('dim_entity') }} e on r.entity_id = e.entity_id
inner join {{ ref('dim_period') }} p on r.period_key = p.period_key
