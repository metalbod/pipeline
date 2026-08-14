select * from {{ source('bronze', 'journal_lines') }}
