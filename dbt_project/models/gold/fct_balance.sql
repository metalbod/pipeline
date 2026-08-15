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
--
-- Forward-fills zero-movement periods (Phase 5 fix): a naive group-by on fct_journal_line only
-- produces a row for (entity, account, period) combinations with actual activity that period,
-- so an account touched once (e.g. a term loan drawn down in month 1 and never touched again)
-- would silently have no row -- and therefore no balance -- in every later period, vanishing
-- from the balance-sheet-equation check even though the loan obviously still exists. Every
-- account instance that has *ever* had activity now gets a row for every period from its first
-- activity onward, with period_movement=0 where nothing happened -- a real account's balance
-- doesn't disappear from the books just because nothing happened to it that month.
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

account_instances as (
    select distinct entity_id, account_key, counterparty_entity_id
    from movements
),

first_activity as (
    select entity_id, account_key, counterparty_entity_id, min(period_start) as first_period_start
    from movements
    group by 1, 2, 3
),

-- Periods where *something* happened somewhere -- the group's actual operational window,
-- not dim_period's full 2015-2035 date-spine range.
active_periods as (
    select distinct period_key, period_start from movements
),

account_period_grid as (
    select
        ai.entity_id,
        ai.account_key,
        ai.counterparty_entity_id,
        ap.period_key,
        ap.period_start
    from account_instances ai
    inner join first_activity fa
        on ai.entity_id = fa.entity_id
        and ai.account_key = fa.account_key
        and ai.counterparty_entity_id is not distinct from fa.counterparty_entity_id
    inner join active_periods ap on ap.period_start >= fa.first_period_start
),

movements_filled as (
    select
        g.entity_id,
        g.account_key,
        g.period_key,
        g.counterparty_entity_id,
        g.period_start,
        coalesce(m.period_movement, 0) as period_movement,
        coalesce(m.group_currency_period_movement, 0) as group_currency_period_movement
    from account_period_grid g
    left join movements m
        on g.entity_id = m.entity_id
        and g.account_key = m.account_key
        and g.period_key = m.period_key
        and g.counterparty_entity_id is not distinct from m.counterparty_entity_id
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
    from movements_filled
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
