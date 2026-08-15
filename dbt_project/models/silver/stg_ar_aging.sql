-- Converges Xero's AgedReceivablesByContact report and SG-SUB's ar_aging file upload into one
-- open-item grain, same "both paths converge into the same Bronze schema-per-domain" principle
-- as stg_journal_lines. days_overdue/aging_bucket are computed relative to the current run date
-- -- an aging report is inherently point-in-time, recomputed fresh each run, not a static fact.
with ranked as (
    select
        *,
        row_number() over (
            partition by _source_system, entity_id, source_record_id
            order by _ingested_at desc
        ) as _dedup_rank
    from {{ ref('bronze_ar_aging') }}
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
