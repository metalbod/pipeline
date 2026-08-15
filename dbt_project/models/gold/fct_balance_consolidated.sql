-- Group-level consolidation (ARCHITECTURE.md §6.3 steps 2-3): aggregate translated balances
-- across entities by group_standard_code/period, minus matched intercompany eliminations.
-- Full consolidation method: 100% of each entity's translated balance is included regardless of
-- ownership_pct -- the ownership adjustment (step 4, minority interest) is a presentation split
-- of the equity total, not a change to what gets aggregated here. See
-- rpt_balance_sheet_consolidated.sql for the NCI split.
--
-- Exposes both a closing-balance figure (consolidated_balance, cumulative -- for balance sheet
-- accounts) and a period-only figure (consolidated_period_movement -- for P&L accounts), same
-- distinction fct_balance draws between closing_balance and period_movement. Eliminations here
-- are closing-balance-based (matches the intercompany loan fixture, a balance-sheet item); a
-- future intercompany P&L transaction (e.g. an intercompany service fee) would need an
-- eliminated_period_movement column on fact_intercompany_elimination too -- not needed yet since
-- no such transaction exists in the data.
with gross as (
    select
        a.group_standard_code,
        b.period_key,
        sum(b.group_currency_amount) as gross_balance,
        sum(b.group_currency_period_movement) as gross_period_movement
    from {{ ref('fct_balance') }} b
    inner join {{ ref('dim_account_group_standard') }} a on b.account_key = a.account_key
    group by a.group_standard_code, b.period_key
),

eliminations as (
    select
        a.group_standard_code,
        e.period_key,
        sum(e.eliminated_amount) as total_eliminated
    from {{ ref('fact_intercompany_elimination') }} e
    inner join {{ ref('dim_account_group_standard') }} a on e.account_key = a.account_key
    group by a.group_standard_code, e.period_key
)

select
    g.group_standard_code,
    g.period_key,
    g.gross_balance - coalesce(el.total_eliminated, 0) as consolidated_balance,
    g.gross_period_movement as consolidated_period_movement
from gross g
left join eliminations el
    on g.group_standard_code = el.group_standard_code
    and g.period_key = el.period_key
