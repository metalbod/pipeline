-- Derived, faster-to-query summary per entity/account/period (ARCHITECTURE.md §6.2) -- avoids
-- re-aggregating fct_journal_line on every dashboard load. Computed uniformly for every
-- account_type (not just balance-sheet accounts): closing_balance is the cumulative net balance
-- since inception through that period, which is what makes the balance-sheet-equation test in
-- tests/assert_balance_sheet_equation.sql exact without needing period-close journal entries.
--
-- Grain extended in Phase 2 to include counterparty_entity_id (null for ordinary accounts,
-- populated for intercompany ones) -- this is what lets fact_intercompany_elimination select
-- straight off this model instead of re-deriving intercompany balances from scratch.
--
-- group_currency_amount is the FX-translated closing balance (mirrors closing_balance, but in
-- group reporting currency) -- Phase 1 left this null; Phase 2's dim_fx_rate join in
-- fct_journal_line makes it computable the same way as the functional-currency balance.
with movements as (
    select
        f.entity_id,
        f.account_key,
        f.period_key,
        f.counterparty_entity_id,
        p.period_start,
        sum(f.functional_currency_amount) as period_movement,
        sum(f.group_currency_amount) as group_currency_period_movement
    from {{ ref('fct_journal_line') }} f
    inner join {{ ref('dim_period') }} p on f.period_key = p.period_key
    group by f.entity_id, f.account_key, f.period_key, f.counterparty_entity_id, p.period_start
),

with_opening as (
    select
        *,
        coalesce(
            sum(period_movement) over (
                partition by entity_id, account_key, counterparty_entity_id
                order by period_start
                rows between unbounded preceding and 1 preceding
            ),
            0
        ) as opening_balance,
        coalesce(
            sum(group_currency_period_movement) over (
                partition by entity_id, account_key, counterparty_entity_id
                order by period_start
                rows between unbounded preceding and 1 preceding
            ),
            0
        ) as group_currency_opening_balance
    from movements
)

select
    entity_id,
    account_key,
    period_key,
    counterparty_entity_id,
    opening_balance,
    period_movement,
    opening_balance + period_movement as closing_balance,
    group_currency_period_movement,
    group_currency_opening_balance + group_currency_period_movement as group_currency_amount
from with_opening
