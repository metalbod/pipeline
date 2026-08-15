select * from {{ source('bronze', 'ar_aging') }}
