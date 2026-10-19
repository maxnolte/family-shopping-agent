# Shopping analytics (dbt + DuckDB)

A layered dbt project on top of the shopping agent's history. The app on the
server writes the raw data continuously (`messages`, `item_events`); this
project runs **locally** on a pulled copy whenever you want fresh numbers.

```
server (always on)                     laptop (whenever)
app ──writes──▶ shopping.db ──pull.sh──▶ data/shopping.db ──dbt build──▶ target/shopping.duckdb
                (raw history)                (attached as `raw`)            (staging → marts)
```

DuckDB attaches the SQLite file directly (`profiles.yml`), so there is no load
step: sources read the app's tables in place.

> **dbt version:** this uses dbt Core 1.12 with `dbt-duckdb`. dbt v2 exists,
> but the DuckDB adapter doesn't support it yet (Oct 2026). Models, tests,
> sources and seeds work the same way in both.

## Setup

Requires [uv](https://docs.astral.sh/uv/). From `analytics/`:

```bash
uv sync
cp members.example.csv seeds/members.csv   # then put real numbers + names in it
```

`seeds/members.csv` maps phone numbers to display names. It is gitignored:
the repo is public and phone numbers are personal data.

**Real data** (needs SSH access to the server, alias `ovh` by default):

```bash
./pull.sh
```

**Synthetic data** (90 days, two members, deterministic; what CI uses):

```bash
(cd ../app && uv run python ../analytics/scripts/make_fixture.py ../analytics/data/shopping.db)
```

## Everyday commands

```bash
uv run dbt build                       # seeds, models and tests, in DAG order
uv run dbt build -s +dim_members       # one model and everything upstream
uv run dbt show -s dim_members         # preview a model
uv run dbt show --inline "select * from {{ ref('stg_app__messages') }}" --limit 5
uv run dbt source freshness            # warns if no messages for 7 days
uv run dbt docs generate && uv run dbt docs serve   # browse lineage + docs
```

Explore the result ad hoc with the DuckDB CLI or Python:

```bash
uv run python -c "import duckdb; print(duckdb.connect('target/shopping.duckdb').sql('from dim_members'))"
```

## Layers

| Layer | Folder | Prefix | Materialized | Rule of thumb |
|---|---|---|---|---|
| Raw | `_sources.yml` | – | (app tables) | Never edited; declared and tested as sources |
| Staging | `models/staging/` | `stg_app__` | view | 1:1 with a source; rename, cast, derive simple flags. No joins |
| Intermediate | `models/intermediate/` | `int_` | view | Joins, window functions, reusable logic. Not for end users |
| Marts | `models/marts/` | `fct_`, `dim_` | table | What you query: facts (events/measures) and dimensions (entities) |

One worked example per layer is in place. Read them in order:

1. `staging/stg_app__messages.sql`: the CTE pattern (`source` → `renamed`),
   renaming, JSON on a text column
2. `intermediate/int_messages_sequenced.sql`: `row_number` / `lag` per member
3. `marts/dim_members.sql`: aggregation, a seed join, masking personal data

Each folder has a `_*.yml` with descriptions and tests. Add yours there.

## Exercises

Roughly in order; each builds on the previous ones. Run `uv run dbt build`
after each and add at least a `unique` + `not_null` test on the grain.

**Staging**

1. `stg_app__item_events`: rename (`item_name` → keep, `sender` →
   `sender_number`, …), add `occurred_date`, and a boolean `is_removal`
   (`remove` or `clear`).
2. `stg_app__shopping_items`: the current list.
3. `stg_app__message_ops`: one row per *operation* inside `ops_json`.
   Hint: `unnest(cast(ops_json as json[]))` or
   `json_transform(ops_json, '[{"action":"VARCHAR","name":"VARCHAR"}]')`.
   What grain is this, and what's its unique key?

**Intermediate**

4. `int_item_lifecycles`: one row per time an item was on the list: added
   at, by whom, removed/cleared at, by whom, minutes on the list, and an
   `is_open` flag for items still on it. Hint: number the add events per
   item, then match each add to the next removal with `lead()` or a join.
   Watch out for `update` events in between.
5. `int_message_sessions`: group each member's messages into sessions (a
   new session starts after 30 minutes of silence). Build on
   `int_messages_sequenced`. Hint: running `sum()` of a "new session" flag.

**Marts**

6. `fct_item_lifecycles`: from #4, with `member_key` (see `dim_members`)
   instead of phone numbers.
7. `fct_daily_activity`: one row per member per day: messages, adds,
   removals, unhandled messages. Days with no activity: do you want rows for
   them? (Look up a date spine.)
8. `mart_top_items`: per item, times added, median time to buy, who adds it
   most, last bought.

**Stretch**

- Make `stg_app__message_ops` or `fct_daily_activity` **incremental**
  (`materialized='incremental'`, `is_incremental()`).
- A **custom generic test** in `tests/generic/` or `macros/`, e.g.
  "`minutes_on_list` is never negative".
- A **singular test** in `tests/`: every `remove` event has a matching
  earlier `add`.
- Add `dbt-utils` via `packages.yml` and use `generate_surrogate_key`,
  `date_spine`.
- A **snapshot** of `shopping_items` (SCD2), then compare it with what
  `item_events` already tells you.

## CI

`.github/workflows/ci.yml` builds the synthetic fixture with the app's own
models and runs `dbt build` on it. If the app's tables change in a way that
breaks a source or model, CI fails.
