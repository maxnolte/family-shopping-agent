# Shopping Agent

WhatsApp-based shopping list agent. See [PLAN.md](PLAN.md) for the full architecture.

Phase 1 (current): send natural-language messages to a dedicated WhatsApp
number to manage a shared shopping list. Messages from whitelisted senders are
parsed by Gemini Flash into add / remove / list / clear operations against a
SQLite database.

## Prerequisites

- Docker + Docker Compose
- A dedicated WhatsApp account on a phone you control (for the QR pairing)
- A Google AI Studio API key for Gemini (https://aistudio.google.com/apikey)

## First-time setup

1. Copy the env template and fill it in with strong random values:
   ```zsh
   cp .env.example .env
   # generate secrets
   openssl rand -hex 32   # use for EVOLUTION_API_KEY
   openssl rand -hex 32   # use for WEBHOOK_TOKEN
   ```
   Set `ALLOWED_NUMBERS` to the WhatsApp numbers of you + your wife (digits only,
   no `+`, comma-separated). E.g. `41791234567,41797654321`.

2. Bring up the stack:
   ```zsh
   docker compose up -d --build
   ```
   First build pulls Postgres, Redis, Evolution API and builds the Python app.

3. Wait ~20s for everything to come up, then check:
   ```zsh
   docker compose ps
   curl -s http://localhost:8000/health   # → {"ok":true}
   ```

## Pair the WhatsApp account (one-time)

> **Already paired?** Check first — if this prints `"state": "open"`, skip the
> steps below entirely (there's nothing to pair, and the QR call will return
> junk):
> ```zsh
> set -a && source .env && set +a
> curl -s http://localhost:8080/instance/connectionState/$EVOLUTION_INSTANCE_NAME \
>   -H "apikey: $EVOLUTION_API_KEY" | jq .
> ```

**Step 1** — Create the Evolution instance and register the webhook:

```zsh
set -a && source .env && set +a   # load env vars into the shell

curl -s -X POST http://localhost:8080/instance/create \
  -H "apikey: $EVOLUTION_API_KEY" \
  -H 'Content-Type: application/json' \
  -d "{
    \"instanceName\": \"$EVOLUTION_INSTANCE_NAME\",
    \"integration\": \"WHATSAPP-BAILEYS\",
    \"qrcode\": true,
    \"webhook\": {
      \"url\": \"http://app:8000/webhook/$WEBHOOK_TOKEN\",
      \"byEvents\": false,
      \"base64\": false,
      \"events\": [\"MESSAGES_UPSERT\"]
    }
  }" | tee /tmp/evo-create.json | jq .
```

**Step 2** — Fetch a fresh QR and open it immediately (expires in ~3 min):

```zsh
curl -s http://localhost:8080/instance/connect/$EVOLUTION_INSTANCE_NAME \
  -H "apikey: $EVOLUTION_API_KEY" \
  | jq -r '.base64' \
  | python3 -c "import sys,base64; d=sys.stdin.read().strip().split(',',1)[-1]; open('/tmp/qr.png','wb').write(base64.b64decode(d))"
explorer.exe "$(wslpath -w /tmp/qr.png)"
```

On the dedicated phone: WhatsApp → Settings → Linked Devices → Link a device →
scan `/tmp/qr.png`. The pairing completes in a few seconds.

If you miss the window, just repeat Step 2.

## Test it

From your own (whitelisted) WhatsApp account, send messages to the dedicated
number:

- `add milk and 2 kg potatoes` → **✓ Added: milk, potatoes (2 kg)**
- `add 3 kg potatoes` again → **✓ Updated: potatoes (3 kg)** (no duplicates)
- `what's on the list?` → the current list
- `remove milk` → **✓ Removed: milk**
- `clear the list` → asks you to reply `yes` within 2 minutes to confirm

The list lives in `app/data/shopping.db` (SQLite), persisted across restarts.

Watch logs to debug:
```zsh
docker compose logs -f app
docker compose logs -f evolution
```

## Stop / reset

```zsh
docker compose down              # stop, keep data
docker compose down -v           # stop and wipe Postgres + Evolution session
                                 # (you will need to re-pair the QR)
rm -f app/data/shopping.db       # wipe the shopping list only
```

## Development

Requires [uv](https://docs.astral.sh/uv/). From `app/`:

```zsh
uvx ruff format . && uvx ruff check .   # format + lint (CI enforces both)
uv run pytest tests/ -q                 # end-to-end tests (Gemini stubbed)
```

CI (`.github/workflows/ci.yml`) runs ruff, the tests, bandit, pip-audit, a
package build, a Docker build and a trivy image scan on every push.

## Production

See [DEPLOY.md](DEPLOY.md): OVHcloud VPS setup, `deploy.sh`, prod compose
override (no published ports), and nightly backups via `backup.sh`.
