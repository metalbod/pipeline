-- Assets = Liabilities + Equity at GROUP level -- CLAUDE.md's hard invariant applies "every
-- entity and at group level" (ARCHITECTURE.md §7). Phase 1 only covered the per-entity case
-- (tests/assert_balance_sheet_equation.sql); this is the group-level counterpart, same
-- sign-translated algebra (no period-close journal entry exists, so revenue/expense must be
-- folded in rather than assumed already-closed).
with by_type as (
    select
        c.period_key,
        a.account_type,
        sum(c.consolidated_balance) as total
    from {{ ref('fct_balance_consolidated') }} c
    inner join {{ ref('dim_account_group_standard') }} a on c.group_standard_code = a.group_standard_code
    group by c.period_key, a.account_type
),

pivoted as (
    select
        period_key,
        sum(case when account_type = 'ASSET' then total else 0 end) as total_assets,
        sum(case when account_type = 'LIABILITY' then total else 0 end) as total_liabilities,
        sum(case when account_type = 'EQUITY' then total else 0 end) as total_equity,
        sum(case when account_type = 'REVENUE' then total else 0 end) as total_revenue,
        sum(case when account_type = 'EXPENSE' then total else 0 end) as total_expense
    from by_type
    group by period_key
)

select *
from pivoted
where abs(
    total_assets - (-total_liabilities - total_equity - total_revenue - total_expense)
) > 0.01
