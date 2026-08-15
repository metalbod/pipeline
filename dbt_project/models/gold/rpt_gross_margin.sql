-- (Revenue - COGS) / Revenue by entity/period. COGS is specifically account_subtype
-- 'Direct Costs' (GS-5100), not all EXPENSE accounts -- Office Expenses stays out of the
-- calculation, same distinction a real income statement makes between COGS and opex.
--
-- Reads 0% margin (COGS always 0) until Finance actually posts to a COGS-classified account in
-- Xero or SG-SUB -- neither source has one today (confirmed by inspecting both fixture chart of
-- accounts). This model is ready plumbing, not a claim that real COGS data exists yet.
select
    entity_id,
    entity_name,
    fiscal_year,
    fiscal_period,
    period_start,
    period_end,
    sum(case when account_type = 'REVENUE' then amount else 0 end) as revenue,
    sum(case when account_subtype = 'Direct Costs' then amount else 0 end) as cogs,
    round(
        (sum(case when account_type = 'REVENUE' then amount else 0 end)
            - sum(case when account_subtype = 'Direct Costs' then amount else 0 end))
        / nullif(sum(case when account_type = 'REVENUE' then amount else 0 end), 0) * 100,
        1
    ) as gross_margin_pct
from {{ ref('rpt_profit_and_loss') }}
group by 1, 2, 3, 4, 5, 6
