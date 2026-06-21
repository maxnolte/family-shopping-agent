# Shopping Agent

WhatsApp-based shopping list agent. See [PLAN.md](PLAN.md) for the full architecture.

This step (Phase 0): minimal echo bot — replies "Message received, thank you"
to any text from a whitelisted sender.

## Prerequisites

- Docker + Docker Compose
- A dedicated WhatsApp account on a phone you control (for the QR pairing)

## First-time setup

1. Copy the env template and fill it in with strong random values:
   ```bash
   cp .env.example .env
   # generate secrets
   openssl rand -hex 32   # use for EVOLUTION_API_KEY
   openssl rand -hex 32   # use for WEBHOOK_TOKEN
   ```
   Set `ALLOWED_NUMBERS` to the WhatsApp numbers of you + your wife (digits only,
   no `+`, comma-separated). E.g. `41791234567,41797654321`.

2. Bring up the stack:
   ```bash
   docker compose up -d --build
   ```
   First build pulls Postgres, Redis, Evolution API and builds the Python app.

3. Wait ~20s for everything to come up, then check:
   ```bash
   docker compose ps
   curl -s http://localhost:8000/health   # → {"ok":true}
   ```

## Pair the WhatsApp account (one-time)

Create the Evolution instance and register the webhook in a single call:

```bash
set -a; source .env; set +a   # load env vars into the shell

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
  }" | tee /tmp/evo-create.json | jq -r '.qrcode.base64' \
  | sed 's|^data:image/png;base64,||' | base64 -d > /tmp/qr.png

xdg-open /tmp/qr.png   # or: imv /tmp/qr.png, open /tmp/qr.png on macOS
```

On the dedicated phone: WhatsApp → Settings → Linked Devices → Link a device →
scan `/tmp/qr.png`. The pairing completes in a few seconds.

If you miss the window, fetch a fresh QR with:
```bash
curl -s http://localhost:8080/instance/connect/$EVOLUTION_INSTANCE_NAME \
  -H "apikey: $EVOLUTION_API_KEY" \
  | jq -r '.base64' | sed 's|^data:image/png;base64,||' | base64 -d > /tmp/qr.png
xdg-open /tmp/qr.png
```

## Test it

From your own (whitelisted) WhatsApp account, send any message to the
dedicated number. You should receive: **"Message received, thank you"**.

Watch logs to debug:
```bash
docker compose logs -f app
docker compose logs -f evolution
```

## Stop / reset

```bash
docker compose down              # stop, keep data
docker compose down -v           # stop and wipe Postgres + Evolution session
                                 # (you will need to re-pair the QR)
```
