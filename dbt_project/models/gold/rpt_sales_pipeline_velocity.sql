-- Finance-entered pipeline estimate, not live CRM data (see stg_pipeline_snapshot.sql). TCV/deal
-- count by stage/period per entity, plus the prior-period delta so a slowdown in a given stage
-- is visible directly rather than requiring a manual period-over-period comparison.
with agg as (
    select
        s.entity_id,
        e.entity_name,
        p.fiscal_year,
        p.fiscal_period,
        p.period_start,
        p.period_end,
        s.pipeline_stage,
        sum(s.deal_count) as deal_count,
        sum(s.total_contract_value) as total_contract_value,
        s.currency
    from {{ ref('stg_pipeline_snapshot') }} s
    inner join {{ ref('dim_entity') }} e on s.entity_id = e.entity_id
    inner join {{ ref('dim_period') }} p
        on s.period_start >= p.period_start
        and s.period_start <= p.period_end
    group by 1, 2, 3, 4, 5, 6, 7, 10
)

select
    *,
    total_contract_value - lag(total_contract_value) over (
        partition by entity_id, pipeline_stage order by period_start
    ) as tcv_change_from_prior_period
from agg
