-- Atomic, auditable grain (ARCHITECTURE.md §6.2) -- every consolidated number traces back to a
-- SUM() over rows here.
--
-- coa_mapping/dim_account_group_standard/dim_fx_rate are all INNER joins on purpose: a local
-- account with no approved mapping, or a currency/period with no approved FX rate, must not
-- silently appear (or silently go untranslated) in the fact table (ARCHITECTURE.md §6.1's "fail
-- loudly, not silently dropped"). tests/assert_no_dropped_journal_lines.sql is the loud failure --
-- if any of these joins drops rows, that test catches it and fails the build.
--
-- FX translation (ARCHITECTURE.md §3, §6.3 step 1): current-rate method -- balance-sheet
-- accounts (asset/liability/equity) translate at the period-end rate, P&L accounts
-- (revenue/expense) at the period-average rate.
--
-- is_intercompany/counterparty_entity_id come from a LEFT join to intercompany_accounts --
-- unlike the joins above, *not* being intercompany is the normal case for most accounts, not a
-- data-quality failure, so this one must not drop rows when there's no match.
select
    {{ dbt_utils.generate_surrogate_key(['s._source_system', 's.entity_id', 's.journal_id', 's.line_no']) }} as journal_line_key,
    s.entity_id,
    a.account_key,
    p.period_key,
    s.journal_id,
    s.line_no,
    s.debit_amount,
    s.credit_amount,
    coalesce(s.currency, e.functional_currency) as transaction_currency,
    (s.debit_amount - s.credit_amount) as functional_currency_amount,
    (s.debit_amount - s.credit_amount) * fx.rate_to_group_currency as group_currency_amount,
    fx.rate_to_group_currency as fx_rate_used,
    s._source_system as source_system,
    s.posted_at,
    (ic.local_account_code is not null) as is_intercompany,
    ic.counterparty_entity_id
from {{ ref('stg_journal_lines') }} s
inner join {{ ref('dim_entity') }} e
    on s.entity_id = e.entity_id
inner join {{ ref('coa_mapping') }} m
    on s.entity_id = m.entity_id
    and s.account_code = m.local_account_code
    and m.is_active
inner join {{ ref('dim_account_group_standard') }} a
    on m.group_standard_account_code = a.group_standard_code
inner join {{ ref('dim_period') }} p
    on s.posted_at >= p.period_start
    and s.posted_at <= p.period_end
inner join {{ ref('dim_fx_rate') }} fx
    on fx.currency_code = coalesce(s.currency, e.functional_currency)
    and fx.fiscal_year = p.fiscal_year
    and fx.fiscal_period = p.fiscal_period
    and fx.rate_type = case
        when a.account_type in ('ASSET', 'LIABILITY', 'EQUITY') then 'period_end'
        else 'period_average'
    end
left join {{ ref('intercompany_accounts') }} ic
    on s.entity_id = ic.entity_id
    and s.account_code = ic.local_account_code
