-- Consolidated balance sheet, group level (ARCHITECTURE.md §3/§6.3). Asset/Liability rows stay
-- itemized per governed account, same as the per-entity report. Equity is presented as a
-- two-line split -- "Equity Attributable to Parent" and "Non-Controlling Interest" -- rather
-- than itemized per account, since NCI is a split of the *equity section total*, not something
-- that can be prorated onto individual equity accounts without fabricating detail that doesn't
-- exist in the ledger. Both computed lines are presentation only, same pattern as Phase 1's
-- "Current Period Earnings" row -- not written back to any governed table.
--
-- NCI = each subsidiary's own total equity (real equity accounts + its unclosed current
-- earnings, naturalized) x (1 - ownership_pct/100), from dim_entity. Full consolidation method:
-- 100% of every subsidiary's balances are already in fct_balance_consolidated regardless of
-- ownership -- NCI only splits how the resulting equity total is *presented*, it does not change
-- consolidated Assets or Liabilities.
with asset_liability_rows as (
    select
        c.period_key,
        a.group_standard_code,
        a.account_name,
        a.account_type,
        a.account_subtype,
        case when a.account_type = 'ASSET' then c.consolidated_balance else -c.consolidated_balance end as amount
    from {{ ref('fct_balance_consolidated') }} c
    inner join {{ ref('dim_account_group_standard') }} a on c.group_standard_code = a.group_standard_code
    where a.account_type in ('ASSET', 'LIABILITY')
),

total_equity as (
    -- Naturalized: real EQUITY accounts (negate, credit-normal) + current-period REVENUE/EXPENSE
    -- folded in unclosed (same "Current Period Earnings" logic as the per-entity report).
    select
        c.period_key,
        -sum(c.consolidated_balance) as total_equity_amount
    from {{ ref('fct_balance_consolidated') }} c
    inner join {{ ref('dim_account_group_standard') }} a on c.group_standard_code = a.group_standard_code
    where a.account_type in ('EQUITY', 'REVENUE', 'EXPENSE')
    group by c.period_key
),

subsidiary_equity as (
    -- Per-entity (pre-consolidation) equity, for entities with a parent (i.e. actual
    -- subsidiaries -- excludes the top-level parent, which is never subject to NCI).
    select
        b.entity_id,
        b.period_key,
        -sum(b.group_currency_amount) as subsidiary_equity_amount
    from {{ ref('fct_balance') }} b
    inner join {{ ref('dim_account_group_standard') }} a on b.account_key = a.account_key
    inner join {{ ref('dim_entity') }} e on b.entity_id = e.entity_id
    where a.account_type in ('EQUITY', 'REVENUE', 'EXPENSE')
    and e.parent_entity_id is not null
    group by b.entity_id, b.period_key
),

nci as (
    select
        se.period_key,
        sum(se.subsidiary_equity_amount * (1 - e.ownership_pct / 100.0)) as nci_amount
    from subsidiary_equity se
    inner join {{ ref('dim_entity') }} e on se.entity_id = e.entity_id
    group by se.period_key
),

equity_rows as (
    select
        te.period_key,
        cast(null as varchar) as group_standard_code,
        'Equity Attributable to Parent' as account_name,
        'EQUITY' as account_type,
        'Consolidated Equity' as account_subtype,
        te.total_equity_amount - coalesce(n.nci_amount, 0) as amount
    from total_equity te
    left join nci n on te.period_key = n.period_key

    union all

    select
        te.period_key,
        cast(null as varchar) as group_standard_code,
        'Non-Controlling Interest' as account_name,
        'EQUITY' as account_type,
        'Consolidated Equity' as account_subtype,
        coalesce(n.nci_amount, 0) as amount
    from total_equity te
    left join nci n on te.period_key = n.period_key
)

select
    p.fiscal_year,
    p.fiscal_period,
    p.period_start,
    p.period_end,
    r.group_standard_code,
    r.account_name,
    r.account_type,
    r.account_subtype,
    r.amount
from (
    select * from asset_liability_rows
    union all
    select * from equity_rows
) r
inner join {{ ref('dim_period') }} p on r.period_key = p.period_key
