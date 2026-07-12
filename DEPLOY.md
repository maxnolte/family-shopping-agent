# Deployment Proposal — OVHcloud VPS

Target: OVH VPS-1 (4 vCores / 8 GB / 75 GB), Debian 12 with Docker preinstalled.
Goal: same Compose stack as the laptop, deployed by `git pull` over SSH. No
CI/CD, no registry, no reverse proxy — nothing on this stack needs to be
reachable from the internet, so the simplest possible pipeline is also the
right one.

## Approach in one paragraph

Clone the private GitHub repo onto the VPS via a read-only deploy key, copy
`.env` over once with `scp`, and run the exact same `docker compose` stack with
a small `docker-compose.prod.yml` override (no published ports, `restart:
always`). Deploys are `git pull && docker compose up -d --build` — wrapped in a
5-line `deploy.sh` so it's one command. Re-pair WhatsApp once on the server
through an SSH tunnel. A nightly cron backs up the SQLite file and the
Evolution session volume off-server.

---

## 1. One-time server setup

### Harden SSH + firewall (15 min)

- Create a non-root user (`adduser max`, add to `sudo` and `docker` groups).
- Key-only SSH: put your public key in `~/.ssh/authorized_keys`, then in
  `/etc/ssh/sshd_config`: `PasswordAuthentication no`, `PermitRootLogin no`.
- Firewall: use the OVH Edge Network Firewall (in the OVH control panel) or
  `ufw` on the box — allow **22/tcp only**. Nothing else listens publicly:
  the prod override below removes all published ports.
- Enable `unattended-upgrades` for automatic Debian security patches
  (`apt install unattended-upgrades`).

### Get the code + secrets

- Generate a dedicated SSH keypair on the VPS, add the public half as a
  **read-only deploy key** on the GitHub repo (repo → Settings → Deploy keys).
  Better than your personal key on a server: leak-blast-radius is one repo,
  read-only.
- `git clone git@github.com:maxnolte/family-shopping-agent.git ~/shopping-agent`
- `scp .env vps:~/shopping-agent/.env` — the one artifact that never travels
  through git. (Optionally set new `POSTGRES_PASSWORD` / `WEBHOOK_TOKEN`
  values for prod while you're at it.)
- If you want to keep the current list: `scp app/data/shopping.db
  vps:~/shopping-agent/app/data/`.

### Prod compose override — ✅ implemented

[`docker-compose.prod.yml`](docker-compose.prod.yml):

- `restart: always` on all four services.
- Removes the `127.0.0.1:8000` and `127.0.0.1:8080` port publishes entirely
  (`ports: !override []`, needs Compose v2.24+ — fine on a fresh Debian 12).
  Evolution's outbound WebSocket to WhatsApp and the internal
  `evolution → app` webhook both work without any published port. When you
  need to hit the APIs (pairing, debugging), SSH-tunnel instead.

Run with:

```zsh
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

A `COMPOSE_FILE=docker-compose.yml:docker-compose.prod.yml` line in the
server's `.env` makes the plain `docker compose` commands pick both up
automatically, so the muscle memory from the laptop transfers 1:1.

### Pair WhatsApp on the server (one-time)

Don't copy the `evolution_instances` volume from the laptop — a stale/cloned
Baileys session is exactly the kind of thing that causes the mystery
disconnects we debugged. Fresh pair instead:

1. Temporarily publish Evolution to localhost (`docker compose up -d` with the
   port line commented back in, or a one-off `-f` override).
2. From the laptop: `ssh -L 8080:localhost:8080 vps`, then run the README's
   Step 1 + Step 2 against `localhost:8080` as usual and scan the QR.
3. In WhatsApp on the phone, remove the old laptop linked device.
4. Remove the port publish again, `docker compose up -d`.
5. Stop the laptop stack for good (`docker compose down`) so two bots don't
   answer.

## 2. Deploying changes — ✅ implemented

[`deploy.sh`](deploy.sh) in the repo root (bash, not zsh — a stock Debian VPS
has no zsh). Run on the VPS, or from the laptop as
`ssh vps 'cd shopping-agent && ./deploy.sh'`:

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
git pull --ff-only
docker compose up -d --build
docker compose ps
```

That's the whole pipeline. For a two-user household app, GitHub Actions /
registries / Watchtower add moving parts without adding value. If deploys ever
become frequent enough to be annoying, bolt on a GitHub Action that SSHes in
and runs this same script — the script is the stable interface.

## 3. Backups (nightly cron)

Two things hold state worth keeping:

| What | Where | Loss impact |
|---|---|---|
| Shopping list | `~/shopping-agent/app/data/shopping.db` | the actual data |
| WA session | `evolution_instances` volume (+ Postgres) | re-pair QR, 5 min |

Pragmatic tiering: the SQLite file gets a real off-server backup; the session
is cheap to recreate, so a local snapshot is enough (or skip it entirely).

Nightly cron on the VPS:

```
15 3 * * * ~/shopping-agent/backup.sh
```

[`backup.sh`](backup.sh) — ✅ implemented. It uses SQLite's online-backup API
(safe while the app runs) via the app container's Python, so the host needs no
sqlite3 install. If an rclone remote named `backup` is configured it also
copies off-server and prunes remote copies older than 14 days; without rclone
you still get local timestamped snapshots in `~/backups/shopping-agent/`
(14-day local retention either way). Any free/cheap S3-compatible bucket
works — OVH's own Object Storage keeps it on one bill.

## 4. Ongoing ops

- **OS patches**: unattended-upgrades (set up above). Reboot occasionally for
  kernel updates; `restart: always` brings the stack back untouched.
- **Image updates**: pinned versions in compose (`evolution-api:v2.3.7`,
  `postgres:16-alpine`); bump deliberately in git, deploy via `deploy.sh` —
  no auto-updaters in prod.
- **Logs**: `ssh vps 'cd shopping-agent && docker compose logs -f app'`. Add
  a `logging: options: max-size: 10m` block to the services so logs can't
  fill the disk over a year.
- **Health**: the bot going quiet is user-visible within hours in a household
  app; skip monitoring infra. If you want a safety net later, a free
  healthchecks.io ping in the backup cron covers "server silently died".

## 5. DevOps: linting, security scanning, packaging — ✅ implemented

Deploys stay manual (section 2), but quality checks belong in CI — they're
free (GitHub Actions private-repo free tier is ~2,000 min/month; this
pipeline uses ~2 min/push) and they catch problems before they reach the VPS.
One workflow, [`.github/workflows/ci.yml`](.github/workflows/ci.yml), on
every push/PR:

### Formatting + linting — ruff (black-compatible)

Black is a formatter only; you'd still need a separate linter next to it. The
pragmatic 2026 choice is **ruff**: its formatter is a drop-in black
equivalent (same style, ~100× faster) and it replaces flake8/isort in the
same tool. Config lives in `pyproject.toml` (~6 lines); run locally with
`uvx ruff format` / `uvx ruff check`, CI runs the same two commands with
`--check`. If you specifically want the black binary anyway, swap it in —
but one tool beats two.

### Security scanning — three cheap layers

| Layer | Tool | Catches |
|---|---|---|
| Dependencies | **Dependabot** (`.github/dependabot.yml`; alerts are a repo setting) + **`uvx pip-audit`** in CI | known CVEs in fastapi/httpx/etc.; Dependabot also opens bump PRs |
| Own code (SAST) | **`uvx bandit -r app/src`** in CI | hardcoded secrets, `eval`, injection patterns, bad TLS usage |
| Docker image | **trivy** on the built image in CI | CVEs in the `python:3.12-slim` OS layer that Python-level scanners never see |

All free, all read-only, none block deploys unless you make them. Policy:
fail CI on `HIGH`+ severity only — household project, not a bank.
`uv.lock` is committed and the Dockerfile syncs `--frozen`, so scans and
builds run against pinned, reproducible versions.

### Building a Python package

`pyproject.toml` is already hatchling-configured, so **`uv build`** produces
a versioned wheel + sdist in `dist/` today with zero changes. Honest note:
the Docker image is your real deployment artifact — the VPS never installs a
wheel. Where the package build earns its keep:

- **Versioned releases**: tag `v0.2.0` → CI runs `uv build` and attaches the
  wheel to a GitHub Release (`gh release create`). Gives you named,
  downloadable rollback points and a changelog rhythm.
- **CI smoke test**: `uv build` + `pip install dist/*.whl` in the workflow
  proves packaging metadata stays valid (catches missing files/imports).
- **Future reuse**: if a CLI or a second frontend ever wants to import
  `shopping_agent`, the package is the interface.

Suggested CI job order: `ruff → bandit → pip-audit → uv build → docker build
→ trivy`. Total ~2 min. Deploys remain `ssh + deploy.sh`, now with the
guarantee that `main` always passed the gates.

## 6. Pre-public checklist (code-review findings, 2026-07-12)

History audit came back clean: `.env` was never tracked, no keys or real phone
numbers anywhere in git history (the numbers in docs are the documented
placeholders). Findings and their status:

1. ✅ **LICENSE** — MIT, in the repo root.
2. ✅ **Evolution `LOG_LEVEL` reverted to `ERROR,WARN,INFO`** — the `DEBUG`
   entry (pairing-investigation leftover) could log message payloads,
   contradicting the "don't log message text" goal.
3. ✅ **Token no longer in access logs** — uvicorn runs with
   `--no-access-log`; the app logs its own structured lines
   (timestamp, sender, action) instead.
4. ✅ **`secrets.compare_digest`** for the webhook token check.
5. ✅ **Non-root `USER` in the app Dockerfile** (uid 1000, matching the
   host user so the `./app/data` bind mount stays writable; the dir is kept
   in git via `.gitkeep` so Docker never creates it root-owned).
6. ✅ **`uv.lock` committed**; Dockerfile syncs `--frozen`.

Remaining manual steps (GitHub UI / host-side, not repo files):

- Enable **Dependabot alerts** in repo Settings → Security when going public.
- One-time on any machine that ran the stack before the non-root change:
  `sudo chown -R "$USER:$USER" app/data` (Docker created it as root).

## Cost of this setup

Zero beyond the VPS you're already paying for (plus pennies for object
storage). Everything else is OVH panel config; the repo files
(`docker-compose.prod.yml`, `deploy.sh`, `backup.sh`, CI) are all in place.

## Suggested order of work

1. ✅ `docker-compose.prod.yml` + `deploy.sh` + `backup.sh` in the repo.
2. VPS arrives → user, SSH hardening, firewall, unattended-upgrades.
3. Deploy key, clone, `scp .env`, first `docker compose up -d --build`.
4. Pair WhatsApp via SSH tunnel; retire the laptop stack.
5. Wire up the backup cron; test a restore once (open the backup file with
   `sqlite3` or Python).
6. ✅ `uv.lock`, ruff config, CI workflow, Dependabot config — all in the
   repo. Still to click: Dependabot alerts in repo settings.
