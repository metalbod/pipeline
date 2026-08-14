select * from {{ source('bronze', 'accounts') }}
