-- Worked example: an intermediate model.
-- Adds per-member ordering with window functions. Not meant to be queried
-- directly; it's a building block for marts (and for your sessions exercise).

with messages as (

    select * from {{ ref('stg_app__messages') }}

),

sequenced as (

    select
        message_id,
        sender_number,
        received_at,
        message_status,
        is_unhandled,

        row_number() over (
            partition by sender_number order by received_at, message_id
        ) as member_message_seq,

        lag(received_at) over (
            partition by sender_number order by received_at, message_id
        ) as previous_received_at

    from messages

)

select
    *,
    date_diff('minute', previous_received_at, received_at) as minutes_since_previous
from sequenced
