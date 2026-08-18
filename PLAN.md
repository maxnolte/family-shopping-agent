# WhatsApp Shopping List Agent — Design & Architecture

> The original design document, kept up to date as decisions land. Setup,
> usage and deployment live in [README.md](README.md).

## Overview

A WhatsApp-based shopping list agent for a small household. Messages sent to a
dedicated WhatsApp number are parsed by an AI model to add or remove items from a
shared shopping list. The system runs fully in Docker, first on a local machine,
later on a small VPS.

---

## Goals

- Send natural-language messages to a WhatsApp number to manage a shared shopping list
- AI parses messages: extract items to add or remove, quantities, and units
- Hard monthly AI API cost cap of ~5 CHF
- Simple and portable: Docker Compose locally → same stack deployed to a VPS
- Python 3 + uv for package management
- Extensible: text messages first, images (receipt scanning) later

---

## Tech Stack

| Layer            | Technology                          |
|------------------|-------------------------------------|
| WhatsApp bridge  | Evolution API (Docker)              |
| App runtime      | Python 3.12                         |
| Package manager  | uv                                  |
| Web framework    | FastAPI (webhook receiver)          |
| Database         | SQLite (local file, via SQLModel)   |
| AI parsing       | Google Gemini Flash (see below)     |
| Containerisation | Docker + Docker Compose             |
| Hosting (prod)   | Any small VPS (see [README.md](README.md)) |

---

## Decision record: AI provider

**Decision:** Google Gemini Flash (`gemini-2.5-flash` via the official
`google-genai` SDK, structured JSON output).

**Considered:** Mistral (mistral-small / mistral-nemo); Claude Haiku via the
Anthropic API.

**Rationale:**

- Free tier of 1,500 requests/day and 1M tokens/day — orders of magnitude
  above household volume (realistic: < 100 messages/day)
- Cost beyond the free tier is negligible: ~$0.075 / 1M input tokens → 3,000
  messages/month at ~200 tokens each ≈ $0.05/month, well inside the 5 CHF cap
- Google Cloud supports a **hard billing budget cap**: set it to 5 CHF and the
  project's API calls stop rather than overspend. Of the candidates, only
  Google offered a true hard stop (Mistral: dashboard spending limits; Claude:
  console usage limits, no built-in hard cap)

**Revisit if:** free-tier terms change, or Phase 4 (image parsing) calls for a
different vision model.

The provider is isolated behind `ai_parser.py`, so swapping is a one-module
change — the rest of the app sees only a list of typed operations.

---

## Architecture

```
  [Household members]
       │
       │  WhatsApp messages
       ▼
┌─────────────────────┐
│   Evolution API     │  ← Docker container, manages the dedicated WA account
│   (WA bridge)       │     bound to 127.0.0.1 in prod (never publicly exposed)
└──────────┬──────────┘
           │ HTTP webhook → POST /webhook/<secret-token>
           ▼
┌─────────────────────┐
│   Python App        │  ← FastAPI, Docker container
│                     │
│  1. Webhook auth    │  verify shared-secret token in URL path
│  2. Sender auth     │  only process messages from allowed numbers
│  3. Rate limit      │  per-sender (e.g. 30 msg/min)
│  4. AI Parser       │  → Gemini Flash: (message + current list) → JSON intent
│  5. DB handler      │  → SQLite: apply add / remove / list / clear
│  6. Reply builder   │  → call Evolution API to send confirmation message
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│   SQLite DB         │  ← single file, mounted as Docker volume
│   shopping.db       │
└─────────────────────┘
```

### Message flow (example: add)

1. A user sends: `"add 2 kg potatoes and some milk"` to the WA number
2. Evolution API POSTs to `https://<host>/webhook/<secret-token>`
3. App verifies the path token, then verifies the sender is whitelisted
4. App reads the current list from SQLite and calls Gemini Flash with:
   ```
   You manage a shared shopping list. Given the current list and a new message,
   return a JSON list of operations.
   Each op: {"action": "add"|"remove"|"clear", "item_id": int|null,
             "name": str|null, "quantity": float|null, "unit": str|null}
   - "add": name required, item_id null
   - "remove": item_id required (pick from current list)
   - "clear": no fields needed
   If the message is unclear, return [].

   Current list:
   [{"id": 1, "name": "bread", "quantity": null, "unit": null}, ...]

   Message: "add 2 kg potatoes and some milk"
   ```
5. Gemini returns:
   ```json
   [
     {"action": "add", "name": "potatoes", "quantity": 2.0, "unit": "kg"},
     {"action": "add", "name": "milk", "quantity": null, "unit": null}
   ]
   ```
6. App applies ops to SQLite
7. App replies: `"✓ Added: potatoes (2 kg), milk"`

### Clearing the list (two-step confirmation)

The list persists indefinitely — items can sit on it for weeks. The only way to wipe
it is an explicit two-step flow per sender:

1. User sends `"clear the list"` (or similar)
2. AI returns `[{"action": "clear"}]`
3. App stores a pending-confirmation flag for that sender (in-memory, 2-minute TTL)
4. App replies:
   `"⚠ This will remove all 14 items. Reply 'yes' within 2 minutes to confirm."`
5. If the same sender replies `"yes"` (or `"confirm"`) within the window, app deletes
   all rows and replies `"✓ List cleared (14 items removed)."`
6. Any other message in between cancels the pending clear

In-memory state is fine: on restart, a pending clear is forgotten and the user simply
asks again — no data loss risk.

---

## Data Model (SQLite)

### `shopping_items` table

| Column       | Type     | Notes                              |
|--------------|----------|------------------------------------|
| id           | INTEGER  | Primary key                        |
| name         | TEXT     | Item name (normalised, lowercase)  |
| quantity     | REAL     | Nullable                           |
| unit         | TEXT     | Nullable (kg, L, pcs, …)           |
| added_by     | TEXT     | Sender phone number                |
| added_at     | DATETIME | UTC                                |

Items persist until explicitly removed (single item) or the list is cleared (all
items, requires confirmation). No auto-expiry — something added today and something
added two months ago are treated the same.

Hard delete on remove: simpler than soft-delete, and history isn't a requirement.

---

## Project Layout

```
shopping-agent/
├── PLAN.md                      ← this file
├── README.md                    ← setup, pairing, usage, VPS deployment
├── docs/                        ← demo screenshot, architecture diagram (draw.io SVG)
├── LICENSE                      ← MIT
├── .pre-commit-config.yaml      ← ruff format + lint on every commit
├── .env.example                 ← template for secrets
├── docker-compose.yml           ← full local stack (4 services)
├── docker-compose.prod.yml      ← production overrides (see README.md)
├── deploy.sh                    ← git pull + compose up (run on the VPS)
├── backup.sh                    ← nightly SQLite backup (cron on the VPS)
├── .github/
│   ├── workflows/ci.yml         ← ruff, bandit, pip-audit, build, trivy
│   └── dependabot.yml           ← weekly dependency-bump PRs
│
└── app/
    ├── Dockerfile               ← multi-stage uv build, non-root runtime
    ├── pyproject.toml           ← uv-managed deps + ruff config
    ├── uv.lock                  ← committed; Docker builds use --frozen
    ├── data/                    ← SQLite volume (gitignored except .gitkeep)
    └── src/
        └── shopping_agent/
            ├── main.py          ← FastAPI app setup, lifespan (init_db), /health
            ├── webhook.py       ← /webhook/<token>: token, whitelist, rate limit
            ├── ratelimit.py     ← per-sender token bucket (in-memory)
            ├── ai_parser.py     ← Gemini structured-output intent parser
            ├── db.py            ← SQLModel engine, init_db, sessions
            ├── models.py        ← SQLModel table definitions
            ├── shopping.py      ← add/remove/list/clear business logic
            ├── pending.py       ← in-memory pending-confirmation store (TTL)
            └── whatsapp.py      ← Evolution API client (send messages)
```

---

## Docker Compose

Four services on a private Docker network. Nothing outside the host ever needs
to reach any container — the only external traffic is Evolution API ↔ WhatsApp
servers, which is initiated *outbound* from inside Evolution.

1. **`postgres`** + **`redis`** — storage and cache backing Evolution API
   (the shopping list itself lives in the app's SQLite, not here). No host
   ports.

2. **`evolution`** — the `evoapicloud/evolution-api` image (version-pinned).
   Published to `127.0.0.1:8080` for the initial QR-code pairing only.

3. **`app`** — Python FastAPI container. Published to `127.0.0.1:8000`
   locally for easy debugging; on prod, no port mapping at all. Mounts
   `./app/data/` for the SQLite file.

Evolution API's webhook target is the internal hostname
`http://app:8000/webhook/<token>` — this call stays inside the Docker bridge network.

Local and prod use the same `docker-compose.yml`. A small `docker-compose.prod.yml`
override adds `restart: always` and removes all published ports — specified in
[README.md](README.md).

---

## Configuration & Secrets

All sensitive values live in a `.env` file. `.gitignore` excludes `.env` and
`app/data/`. Only `.env.example` is committed.

```
# Evolution API
EVOLUTION_API_KEY=...                 # admin key, generated at first start
EVOLUTION_BASE_URL=http://evolution:8080
EVOLUTION_INSTANCE_NAME=shopping

# Allowed WhatsApp numbers (digits only, no '+', comma-separated)
ALLOWED_NUMBERS=41791234567,41797654321

# AI
GEMINI_API_KEY=...

# App
WEBHOOK_TOKEN=...                     # required; long random string, used as URL path
                                      # segment for Evolution → app webhook auth
```

The webhook URL Evolution is configured with is `http://app:8000/webhook/${WEBHOOK_TOKEN}`.
The app rejects any request whose path token doesn't match.

---

## Local → Production Migration

Covered by [README.md](README.md) (§ Deploying to a VPS): server hardening,
git-pull deploys over a read-only deploy key, one-time QR pairing on the
server, and nightly backups.

The invariant stands: **no application code changes between environments** —
prod is the same compose stack plus a small override file (`restart: always`,
no published ports).

---

## Phased Roadmap

### Phase 1 — Core (text only)
- [x] Set up Evolution API in Docker, connect dedicated WA account
- [x] FastAPI app with `/webhook/<token>` endpoint (token check + sender whitelist)
- [x] Per-sender rate limiter
- [x] Gemini Flash integration: pass current list + message, parse JSON ops
- [x] SQLite DB with `shopping_items` table
- [x] Add / remove operations, plus "what's on the list" reply
- [x] Clear-list with two-step confirmation (in-memory pending state, 2-min TTL)
- [x] Confirmation message back to sender
- [x] `docker-compose.yml` for full local stack

> Note: uses the current `google-genai` SDK (the `google-generativeai`
> package referenced above is now deprecated). Default model
> `gemini-2.5-flash`, overridable via `GEMINI_MODEL`.

### Phase 2 — Polish
- [x] Deduplication: if item already on list, update quantity instead of duplicating
- [x] Error handling: unrecognised message → friendly reply, no DB change
- [x] Simple logging (timestamps, sender, action — not full message text)

### Phase 3 — Production
- [x] `docker-compose.prod.yml` (no host ports on any container, `restart: always`)
- [x] Deploy to a small VPS (~6 CHF/month), firewall = SSH only (see README.md)
- [x] Initial WA pairing on the server (terminal QR via `qrencode`)
- [ ] Set Google Cloud billing budget alert + hard cap at 5 CHF
- [ ] Nightly `rclone` backup of `shopping.db` to off-server storage
      *(`backup.sh` ready; verify the cron entry and configure an rclone
      remote named `backup` — until then, backups live on the same disk as
      the data)*
- [ ] Test a restore once: open a snapshot with `sqlite3`, check row counts

### Phase 4 — Image support (future)
- [ ] Receive image messages from Evolution API
- [ ] Send image to Gemini Vision: extract item names from receipts or handwritten lists
- [ ] Same add/remove pipeline as text
- [ ] Note: images are sent to Google — fine for shopping lists but worth being aware of

---

## Quality Backlog

From a review pass (2026-08), ordered by impact. Accepted trade-offs that
came out of the same review (blocking calls in async handlers, in-memory
state, no monitoring stack) are documented in the README's
[Design decisions](README.md#design-decisions) rather than listed here — they
are decisions, not debt.

### Evaluation harness (highest impact)

The intent parser — the system prompt plus the Gemini call — has no tests and
no evaluation today: the test suite stubs the model entirely. A prompt change
that breaks `remove milk` would go unnoticed until a user hits it.

- [ ] Golden set: ~30 messages with expected operations — multilingual,
      ambiguous, small talk, multi-op, quantity updates, remove-by-meaning
- [ ] Eval script (e.g. `app/evals/`): runs the golden set against the live
      model, reports per-case pass/fail and overall accuracy
- [ ] CI integration: manual-trigger (`workflow_dispatch`) job, free at
      Gemini free-tier volumes; run before merging prompt changes
- [ ] Token/cost logging: record usage metadata per request for a measured
      monthly cost figure

### Engineering polish

- [ ] Type checking in CI: the code is fully annotated but nothing enforces
      it — add `pyright` (or `mypy --strict`); optionally a coverage report
- [ ] Real `/health`: currently returns `{"ok": true}` unconditionally; make
      it touch the DB (optionally Evolution's API) and wire it into a compose
      `healthcheck` for the app service
- [ ] Distinguish LLM outage from unparseable input: `parse_message` returns
      `[]` on any exception, so a Gemini outage replies "I didn't understand
      that" — surface an explicit error state, reply differently, and
      consider one retry with backoff
- [ ] Direct unit tests for the components the e2e suite skips: rate limiter
      (token refill math), pending-clear TTL expiry (monkeypatch
      `time.monotonic`), webhook rejection paths (bad token, non-whitelisted
      sender, group chat, `fromMe`)
- [ ] Releases: CI builds a wheel that goes nowhere — tag `v0.1.0` and attach
      the wheel to a GitHub Release with a short changelog, or drop the build
      step

---

## Cost Estimate (monthly, steady state)

| Item                              | Cost          |
|-----------------------------------|---------------|
| Small VPS (1-year prepaid)        | ~6 CHF        |
| Google Gemini Flash API (est.)    | ~0 CHF (free tier) |
| Domain (optional, amortised)      | ~1 CHF        |
| **Total**                         | **~7 CHF**    |

AI costs are essentially zero at household message volumes on Gemini's free tier.
The hard billing cap in Google Cloud provides the safety net if volume spikes.
