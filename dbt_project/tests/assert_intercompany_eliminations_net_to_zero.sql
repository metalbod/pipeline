-- Real correctness check, not just structural presence: for each approved (entity_id,
-- counterparty_entity_id) pair, both sides' eliminated amounts (in group currency) must net to
-- ~0. If this fails, the FX rate or the intercompany transaction amounts were chosen (or
-- recorded) inconsistently between the two entities' books.
with pair_totals as (
    select
        least(entity_id, counterparty_entity_id) as entity_a,
        greatest(entity_id, counterparty_entity_id) as entity_b,
        sum(eliminated_amount) as net_amount
    from {{ ref('fact_intercompany_elimination') }}
    group by least(entity_id, counterparty_entity_id), greatest(entity_id, counterparty_entity_id)
)

select *
from pair_totals
where abs(net_amount) > 0.01
