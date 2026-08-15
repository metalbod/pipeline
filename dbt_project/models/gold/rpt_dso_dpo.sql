-- Two DSO/DPO figures side by side, both labeled, per your explicit ask in this session's
-- research: dso_days_approx/dpo_days_approx is the balance-based approximation (AR or AP
-- balance / revenue or expense * days in period) used before invoice-level data existed;
-- dso_days_true/dpo_days_true is the invoice-weighted average days outstanding computed from
-- stg_ar_aging/stg_ap_aging -- the rigorous number, now that it's available.
--
-- dso_days_true/dpo_days_true are point-in-time snapshots ("as of today"), not a historical
-- time series -- an aging report only ever reflects currently-open invoices, it has no memory
-- of what was open in a past period. Attached only to the current period's row (NULL
-- elsewhere) rather than broadcast across every historical period, which would otherwise show
-- today's snapshot value next to a March balance sheet as if it were March's true DSO -- caught
-- in finance-reviewer pass.
with balances as (
    select
        bs.entity_id,
        bs.entity_name,
        bs.fiscal_year,
        bs.fiscal_period,
        bs.period_end,
        max(case when bs.account_name = 'Accounts Receivable' then bs.amount end) as ar_balance,
        max(case when bs.account_name = 'Accounts Payable' then bs.amount end) as ap_balance
    from {{ ref('rpt_balance_sheet') }} bs
    group by 1, 2, 3, 4, 5
),

pl_totals as (
    select
        entity_id,
        fiscal_year,
        fiscal_period,
        sum(case when account_type = 'REVENUE' then amount else 0 end) as revenue,
        sum(case when account_type = 'EXPENSE' then amount else 0 end) as expense
    from {{ ref('rpt_profit_and_loss') }}
    group by 1, 2, 3
),

approx as (
    select
        b.entity_id,
        b.entity_name,
        b.fiscal_year,
        b.fiscal_period,
        b.period_end,
        round(b.ar_balance / nullif(p.revenue, 0) * extract(day from last_day(b.period_end)), 1) as dso_days_approx,
        round(b.ap_balance / nullif(p.expense, 0) * extract(day from last_day(b.period_end)), 1) as dpo_days_approx
    from balances b
    inner join pl_totals p
        on b.entity_id = p.entity_id
        and b.fiscal_year = p.fiscal_year
        and b.fiscal_period = p.fiscal_period
),

ar_weighted as (
    select entity_id, sum(amount_outstanding * days_overdue) / nullif(sum(amount_outstanding), 0) as dso_days_true
    from {{ ref('stg_ar_aging') }}
    group by 1
),

ap_weighted as (
    select entity_id, sum(amount_outstanding * days_overdue) / nullif(sum(amount_outstanding), 0) as dpo_days_true
    from {{ ref('stg_ap_aging') }}
    group by 1
)

select
    a.*,
    case
        when a.fiscal_year = extract(year from current_date) and a.fiscal_period = extract(month from current_date)
        then ar.dso_days_true
    end as dso_days_true,
    case
        when a.fiscal_year = extract(year from current_date) and a.fiscal_period = extract(month from current_date)
        then ap.dpo_days_true
    end as dpo_days_true
from approx a
left join ar_weighted ar on a.entity_id = ar.entity_id
left join ap_weighted ap on a.entity_id = ap.entity_id
