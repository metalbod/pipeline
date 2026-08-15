-- Converges Xero's AgedPayablesByContact report and SG-SUB's ap_aging file upload -- same
-- pattern as stg_ar_aging.sql.
with ranked as (
    select
        *,
        row_number() over (
            partition by _source_system, entity_id, source_record_id
            order by _ingested_at desc
        ) as _dedup_rank
    from {{ ref('bronze_ap_aging') }}
)

select
    * exclude (_dedup_rank),
    (current_date - due_date) as days_overdue,
    case
        when current_date <= due_date then 'Not yet due'
        when current_date - due_date <= 30 then '1-30 days'
        when current_date - due_date <= 60 then '31-60 days'
        when current_date - due_date <= 90 then '61-90 days'
        else '90+ days'
    end as aging_bucket
from ranked
where _dedup_rank = 1
