# WhatsApp Shopping List Agent — Plan & Architecture

## Overview

A WhatsApp-based shopping list agent for two users (you + wife). Messages sent to a
dedicated WhatsApp number are parsed by an AI model to add or remove items from a
shared shopping list. The system runs fully in Docker, first on your laptop, later on a
Hetzner cloud server.

---

## Goals

- Send natural-language messages to a WhatsApp number to manage a shared shopping list
- AI parses messages: extract items to add or remove, quantities, and units
- Hard monthly AI API cost cap of ~5 CHF
- Simple and portable: Docker Compose on laptop → same stack deployed to Hetzner
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
| Hosting (prod)   | Hetzner Cloud VPS (CX11 or similar) |

---

## AI API Choice: Google Gemini Flash

**Why Gemini Flash:**

- Free tier: 1,500 requests/day and 1M tokens/day — almost certainly enough for a
  household shopping list (realistic: < 100 messages/day)
- If you exceed the free tier: ~$0.075 / 1M input tokens → for 3,000 messages/month
  at ~200 tokens each ≈ $0.05/month, well inside the 5 CHF cap
- Google Cloud has a **hard billing budget cap**: set it to 5 CHF and the project's
  API calls stop rather than overspend
- Simple REST API, official Python SDK (`google-generativeai`)

**Alternative if preferred:**

- **Mistral (mistral-small or mistral-nemo):** monthly spending limits in their dashboard;
  similar pricing. Good if you already have a Mistral account.
- **Claude Haiku via Anthropic API:** cheapest Anthropic model; no built-in hard cap but
  usage limits can be set in the Anthropic Console. About $0.08 / 1M input tokens.
- **Claude.ai Pro subscription:** does not grant API access — the API is billed separately
  via console.anthropic.com.

The AI call structure is abstracted behind an interface, so swapping providers is
straightforward.

---

## Architecture

```
  [You / Wife]
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

1. Wife sends: `"add 2 kg potatoes and some milk"` to the WA number
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
├── .env.example                 ← template for secrets
├── docker-compose.yml           ← local dev stack
├── docker-compose.prod.yml      ← production overrides (Hetzner)
│
├── evolution/                   ← Evolution API config (mounted into container)
│   └── ...
│
└── app/
    ├── Dockerfile
    ├── pyproject.toml           ← uv-managed, defines dependencies
    ├── uv.lock
    └── src/
        └── shopping_agent/
            ├── main.py          ← FastAPI app, startup
            ├── webhook.py       ← /webhook/<token> endpoint, token + sender check
            ├── ratelimit.py     ← per-sender token bucket (in-memory)
            ├── ai_parser.py     ← Gemini call, returns intent JSON
            ├── db.py            ← SQLModel setup, DB session
            ├── models.py        ← SQLModel table definitions
            ├── shopping.py      ← add/remove/list/clear business logic
            ├── pending.py       ← in-memory pending-confirmation store (TTL)
            └── whatsapp.py      ← Evolution API client (send messages)
```

---

## Docker Compose

Two services on a private Docker network. Nothing outside the host ever needs to
reach either container — the only inbound traffic is Evolution API ↔ WhatsApp servers,
which is initiated *outbound* from inside Evolution.

1. **`evolution`** — the official `atendai/evolution-api` image. Published to
   `127.0.0.1:8080` for the initial QR-code pairing (you scan the QR from the host
   browser). No public port mapping in either env.

2. **`app`** — Python FastAPI container. Published to `127.0.0.1:8000` on laptop for
   easy debugging; on prod, no port mapping at all. Mounts `./app/data/` for the SQLite
   file.

Evolution API's webhook target is the internal hostname
`http://app:8000/webhook/<token>` — this call stays inside the Docker bridge network.

Local and prod use the same `docker-compose.yml`. A small `docker-compose.prod.yml`
override adds `restart: always` and removes the `127.0.0.1:8000` mapping on `app`.

---

## Configuration & Secrets

All sensitive values live in a `.env` file. `.gitignore` excludes `.env` and
`app/data/`. Only `.env.example` is committed.

```
# Evolution API
EVOLUTION_API_KEY=...                 # admin key, generated at first start
EVOLUTION_BASE_URL=http://evolution:8080
EVOLUTION_INSTANCE_NAME=shopping

# Allowed WhatsApp numbers (E.164 format, comma-separated)
ALLOWED_NUMBERS=+41791234567,+41797654321

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

Differences for Hetzner:

1. `docker-compose.prod.yml` overrides:
   - `restart: always` on all services
   - Drops the `127.0.0.1:8000` mapping on `app` (no host port at all)
   - Evolution API has no host port either (after initial QR pairing is done)
2. Hetzner Firewall: only port 22 (SSH) open inbound. Nothing else is needed —
   neither container is reachable from the public internet, so there is no public
   attack surface beyond SSH.
3. Backups: nightly cron on the VPS uploads `shopping.db` to a Hetzner Storage Box
   (or any S3-compatible bucket) via `rclone`. Retain ~14 daily copies.

For the initial WA pairing on the VPS, temporarily publish the Evolution port to
`127.0.0.1:8080` and SSH-tunnel from your laptop (`ssh -L 8080:localhost:8080 ...`),
scan the QR in your local browser, then remove the publish.

No application code changes are needed between environments.

---

## Phased Roadmap

### Phase 1 — Core (text only)
- [ ] Set up Evolution API in Docker, connect dedicated WA account
- [ ] FastAPI app with `/webhook/<token>` endpoint (token check + sender whitelist)
- [ ] Per-sender rate limiter
- [ ] Gemini Flash integration: pass current list + message, parse JSON ops
- [ ] SQLite DB with `shopping_items` table
- [ ] Add / remove operations, plus "what's on the list" reply
- [ ] Clear-list with two-step confirmation (in-memory pending state, 2-min TTL)
- [ ] Confirmation message back to sender
- [ ] `docker-compose.yml` for full local stack

### Phase 2 — Polish
- [ ] Deduplication: if item already on list, update quantity instead of duplicating
- [ ] Error handling: unrecognised message → friendly reply, no DB change
- [ ] Simple logging (timestamps, sender, action — not full message text)

### Phase 3 — Production
- [ ] `docker-compose.prod.yml` (no host ports on either container, `restart: always`)
- [ ] Deploy to Hetzner CX11 (~4 CHF/month), firewall = SSH only
- [ ] Initial WA pairing via SSH local-forward of port 8080
- [ ] Set Google Cloud billing budget alert + hard cap at 5 CHF
- [ ] Nightly `rclone` backup of `shopping.db` to off-server storage

### Phase 4 — Image support (future)
- [ ] Receive image messages from Evolution API
- [ ] Send image to Gemini Vision: extract item names from receipts or handwritten lists
- [ ] Same add/remove pipeline as text
- [ ] Note: images are sent to Google — fine for shopping lists but worth being aware of

---

## Cost Estimate (monthly, steady state)

| Item                              | Cost          |
|-----------------------------------|---------------|
| Hetzner CX11 VPS                  | ~4 CHF        |
| Google Gemini Flash API (est.)    | ~0 CHF (free tier) |
| Domain (optional, amortised)      | ~1 CHF        |
| **Total**                         | **~5 CHF**    |

AI costs are essentially zero at household message volumes on Gemini's free tier.
The hard billing cap in Google Cloud provides the safety net if volume spikes.
