select * from {{ source('bronze', 'pipeline_snapshot') }}
