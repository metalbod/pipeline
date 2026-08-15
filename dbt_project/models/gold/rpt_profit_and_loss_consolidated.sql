-- Consolidated P&L, group level. Uses consolidated_period_movement, not consolidated_balance --
-- revenue/expense are period-flow accounts, same distinction the per-entity report draws
-- between period_movement and closing_balance. Naturalized: REVENUE negated (credit-normal),
-- EXPENSE unchanged (debit-normal).
select
    p.fiscal_year,
    p.fiscal_period,
    p.period_start,
    p.period_end,
    a.group_standard_code,
    a.account_name,
    a.account_type,
    a.account_subtype,
    case
        when a.account_type = 'REVENUE' then -c.consolidated_period_movement
        else c.consolidated_period_movement
    end as amount
from {{ ref('fct_balance_consolidated') }} c
inner join {{ ref('dim_account_group_standard') }} a on c.group_standard_code = a.group_standard_code
inner join {{ ref('dim_period') }} p on c.period_key = p.period_key
where a.account_type in ('REVENUE', 'EXPENSE')
