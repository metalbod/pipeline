-- Finance-entered pipeline estimate, not live CRM data. `period` arrives as 'YYYY-MM' (validated
-- by PipelineUploadSchema); period_key is derived the same way dim_period.sql generates its own
-- surrogate key, so this joins to dim_period without a separate mapping step.
with ranked as (
    select
        *,
        cast(period || '-01' as date) as period_start,
        row_number() over (
            partition by _source_system, entity_id, period, pipeline_stage
            order by _ingested_at desc
        ) as _dedup_rank
    from {{ ref('bronze_pipeline_snapshot') }}
)

select
    {{ dbt_utils.generate_surrogate_key(['period_start']) }} as period_key,
    * exclude (_dedup_rank)
from ranked
where _dedup_rank = 1
