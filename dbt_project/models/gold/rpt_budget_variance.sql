-- Budgeted vs. actual by entity/account/period, joined via the same group_standard_code
-- actuals already use (rpt_profit_and_loss) -- not a separate budget-side COA. is_major_variance
-- flags anything more than 15% off budget, a reasonable default threshold for a first cut; there
-- was no existing convention for this in the codebase to match, so noting the choice here
-- explicitly rather than presenting it as an established rule.
select
    b.entity_id,
    b.period,
    b.group_standard_code,
    b.account_name,
    b.account_type,
    b.budgeted_amount,
    coalesce(a.amount, 0) as actual_amount,
    coalesce(a.amount, 0) - b.budgeted_amount as variance_amount,
    round((coalesce(a.amount, 0) - b.budgeted_amount) / nullif(b.budgeted_amount, 0) * 100, 1) as variance_pct,
    abs(coalesce(a.amount, 0) - b.budgeted_amount) > 0.15 * abs(b.budgeted_amount) as is_major_variance
from {{ ref('stg_budget') }} b
left join {{ ref('rpt_profit_and_loss') }} a
    on b.entity_id = a.entity_id
    and b.group_standard_code = a.group_standard_code
    and b.period = lpad(a.fiscal_year::varchar, 4, '0') || '-' || lpad(a.fiscal_period::varchar, 2, '0')
