-- Derived, faster-to-query summary per entity/account/period (ARCHITECTURE.md §6.2) -- avoids
-- re-aggregating fct_journal_line on every dashboard load. Computed uniformly for every
-- account_type (not just balance-sheet accounts): closing_balance is the cumulative net balance
-- since inception through that period, which is what makes the balance-sheet-equation test in
-- tests/assert_balance_sheet_equation.sql exact without needing period-close journal entries.
with movements as (
    select
        f.entity_id,
        f.account_key,
        f.period_key,
        p.period_start,
        sum(f.functional_currency_amount) as period_movement
    from {{ ref('fct_journal_line') }} f
    inner join {{ ref('dim_period') }} p on f.period_key = p.period_key
    group by f.entity_id, f.account_key, f.period_key, p.period_start
),

with_opening as (
    select
        *,
        coalesce(
            sum(period_movement) over (
                partition by entity_id, account_key
                order by period_start
                rows between unbounded preceding and 1 preceding
            ),
            0
        ) as opening_balance
    from movements
)

select
    entity_id,
    account_key,
    period_key,
    opening_balance,
    period_movement,
    opening_balance + period_movement as closing_balance,
    cast(null as double) as group_currency_amount
from with_opening
