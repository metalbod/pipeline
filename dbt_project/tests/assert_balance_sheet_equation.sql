-- Assets = Liabilities + Equity -- hard invariant, never relaxed or skipped (CLAUDE.md).
--
-- Phase 1 has no period-close journal entry, so this can't be checked by literally summing
-- ASSET/LIABILITY/EQUITY account balances (unclosed revenue/expense would make it look
-- unbalanced even though the books are fine). Instead this uses the sign-translated form of the
-- accounting equation, algebraically equivalent to "total debits = total credits", which holds
-- at any point without requiring a closing entry:
--
--   Assets(natural) = Liabilities(natural) + Equity(natural) + NetIncome(natural)
--   sum(ASSET) = -sum(LIABILITY) - sum(EQUITY) - sum(REVENUE) - sum(EXPENSE)
--
-- (signed sums are debit-minus-credit; liability/equity/revenue are credit-normal so their
-- natural/normal-balance value is the negation of the signed sum). Every entity, every period.
with by_type as (
    select
        b.entity_id,
        b.period_key,
        a.account_type,
        sum(b.closing_balance) as total
    from {{ ref('fct_balance') }} b
    inner join {{ ref('dim_account_group_standard') }} a on b.account_key = a.account_key
    group by b.entity_id, b.period_key, a.account_type
),

pivoted as (
    select
        entity_id,
        period_key,
        sum(case when account_type = 'ASSET' then total else 0 end) as total_assets,
        sum(case when account_type = 'LIABILITY' then total else 0 end) as total_liabilities,
        sum(case when account_type = 'EQUITY' then total else 0 end) as total_equity,
        sum(case when account_type = 'REVENUE' then total else 0 end) as total_revenue,
        sum(case when account_type = 'EXPENSE' then total else 0 end) as total_expense
    from by_type
    group by entity_id, period_key
)

select *
from pivoted
where abs(
    total_assets - (-total_liabilities - total_equity - total_revenue - total_expense)
) > 0.01
