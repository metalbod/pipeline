-- Unconsolidated P&L per entity/period. Uses period_movement, not closing_balance -- revenue and
-- expense are period-flow accounts; a P&L reports this period's activity, not a cumulative
-- balance (ARCHITECTURE.md §3).
--
-- `amount` is naturalized (normal-balance-positive): REVENUE is credit-normal so its signed
-- period_movement is negated; EXPENSE is debit-normal so it's unchanged. Without this, revenue
-- would display as a negative number.
select
    b.entity_id,
    e.entity_name,
    p.fiscal_year,
    p.fiscal_period,
    p.period_start,
    p.period_end,
    a.group_standard_code,
    a.account_name,
    a.account_type,
    a.account_subtype,
    case when a.account_type = 'REVENUE' then -b.period_movement else b.period_movement end as amount,
    e.functional_currency
from {{ ref('fct_balance') }} b
inner join {{ ref('dim_entity') }} e on b.entity_id = e.entity_id
inner join {{ ref('dim_account_group_standard') }} a on b.account_key = a.account_key
inner join {{ ref('dim_period') }} p on b.period_key = p.period_key
where a.account_type in ('REVENUE', 'EXPENSE')
