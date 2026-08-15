-- Actual debt-to-equity ratio vs. the seeded covenant threshold, headroom %, and a breach flag.
-- Empty today -- debt_covenants (Silver) has zero rows until a real facility exists, and
-- GS-2100 (External Bank Loans) has zero postings either way. This model assumes every covenant
-- row is a maximum-debt-to-equity-ratio constraint; there was no existing convention in the
-- codebase for modeling different covenant_type formulas, so that's a first-cut simplification
-- to revisit once a real facility (and its actual covenant terms) exists.
--
-- Effective-dated: a covenant only applies to periods within its [effective_from, effective_to)
-- window, same convention as coa_mapping/intercompany_accounts -- without this, a covenant
-- entered for a 2027 facility would otherwise retroactively flag 2026 periods as breached
-- against a threshold that wasn't in force yet (caught in finance-reviewer pass).
with debt as (
    select entity_id, fiscal_year, fiscal_period, period_end, sum(amount) as external_debt
    from {{ ref('rpt_balance_sheet') }}
    where group_standard_code = 'GS-2100'
    group by 1, 2, 3, 4
),

equity as (
    select entity_id, fiscal_year, fiscal_period, sum(amount) as total_equity
    from {{ ref('rpt_balance_sheet') }}
    where account_type = 'EQUITY'
    group by 1, 2, 3
)

select
    c.entity_id,
    c.facility_name,
    c.covenant_type,
    c.threshold_value,
    d.fiscal_year,
    d.fiscal_period,
    d.external_debt,
    e.total_equity,
    round(d.external_debt / nullif(e.total_equity, 0), 4) as actual_debt_to_equity_ratio,
    round(
        (c.threshold_value - d.external_debt / nullif(e.total_equity, 0)) / nullif(c.threshold_value, 0) * 100,
        1
    ) as headroom_pct,
    (d.external_debt / nullif(e.total_equity, 0)) > c.threshold_value as is_breached
from {{ ref('debt_covenants') }} c
inner join debt d
    on c.entity_id = d.entity_id
    and d.period_end >= c.effective_from
    and (c.effective_to is null or d.period_end < c.effective_to)
inner join equity e
    on c.entity_id = e.entity_id
    and d.fiscal_year = e.fiscal_year
    and d.fiscal_period = e.fiscal_period
