-- Intercompany elimination is modeled explicitly, not netted away silently (ARCHITECTURE.md §3):
-- business owners reviewing a consolidated balance sheet legitimately want to see what was
-- eliminated and why. eliminated_amount is the entity's own intercompany balance in group
-- currency, taken straight from fct_balance's counterparty-aware grain.
--
-- Inner join to seed_elimination_rules on purpose: this is the governance gate (ARCHITECTURE.md
-- §6.3 step 3, "via a rules table") -- an intercompany balance with no approved elimination rule
-- for that entity pair is deliberately excluded here and stays visible, un-netted, in the
-- consolidated marts, rather than being silently eliminated without approval.
select
    b.entity_id,
    b.counterparty_entity_id,
    b.account_key,
    b.period_key,
    b.group_currency_amount as eliminated_amount
from {{ ref('fct_balance') }} b
inner join {{ ref('elimination_rules') }} r
    on b.entity_id = r.entity_id
    and b.counterparty_entity_id = r.counterparty_entity_id
where b.counterparty_entity_id is not null
