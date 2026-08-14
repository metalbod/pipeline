-- Dedupes idempotent re-ingestion of the same batch/file (ARCHITECTURE.md §5). Row identity is
-- (source_system, entity_id, journal_id, line_no); source_updated_at picks the latest version
-- when the same line is legitimately re-ingested with a correction.
with ranked as (
    select
        *,
        row_number() over (
            partition by _source_system, entity_id, journal_id, line_no
            order by source_updated_at desc, _ingested_at desc
        ) as _dedup_rank
    from {{ ref('bronze_journal_lines') }}
)

select * exclude (_dedup_rank)
from ranked
where _dedup_rank = 1
