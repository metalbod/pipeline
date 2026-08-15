-- Open AR invoices past due, ranked by amount outstanding -- the "high-level watchlist of large
-- corporate accounts that are past due" from the framework's Working Capital Status section.
select
    entity_id,
    source_record_id as invoice_id,
    contact_name,
    invoice_date,
    due_date,
    days_overdue,
    aging_bucket,
    amount_outstanding,
    currency,
    row_number() over (partition by entity_id order by amount_outstanding desc) as overdue_rank
from {{ ref('stg_ar_aging') }}
where days_overdue > 0
