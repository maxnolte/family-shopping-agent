-- Worked example: a staging model.
-- One per source table. Only rename, cast and derive simple columns here;
-- no joins, no aggregation. Everything downstream selects from this, never
-- from the source directly.

with source as (

    select * from {{ source('app', 'messages') }}

),

renamed as (

    select
        id                          as message_id,
        received_at,
        cast(received_at as date)   as received_date,
        sender                      as sender_number,
        text                        as message_text,
        status                      as message_status,
        reply                       as reply_text,
        ops_json,
        -- DuckDB's JSON functions work directly on the text column.
        json_array_length(ops_json) as op_count,
        status in ('fallback', 'no_match', 'error') as is_unhandled

    from source

)

select * from renamed
