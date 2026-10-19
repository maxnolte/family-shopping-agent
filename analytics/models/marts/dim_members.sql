-- Worked example: a mart (dimension).
-- One row per household member. Names come from the `members` seed
-- (gitignored, see analytics/README.md); unknown numbers get a masked label
-- so phone numbers don't leak into dashboards.

with messages as (

    select * from {{ ref('int_messages_sequenced') }}

),

names as (

    select * from {{ ref('members') }}

),

activity as (

    select
        sender_number,
        min(received_at)                            as first_message_at,
        max(received_at)                            as last_message_at,
        count(*)                                    as message_count,
        avg(case when is_unhandled then 1.0 else 0.0 end) as unhandled_rate,
        median(minutes_since_previous)              as median_minutes_between_messages

    from messages
    group by sender_number

)

select
    md5(activity.sender_number)                     as member_key,
    coalesce(
        names.display_name,
        'member …' || right(activity.sender_number, 3)
    )                                               as display_name,
    activity.* exclude (sender_number)

from activity
left join names using (sender_number)
