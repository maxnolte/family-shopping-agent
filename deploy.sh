#!/usr/bin/env bash
# Deploy the latest main to this machine. See DEPLOY.md §2.
# Run on the VPS, or from the laptop: ssh vps 'cd shopping-agent && ./deploy.sh'
set -euo pipefail
cd "$(dirname "$0")"

git pull --ff-only
docker compose up -d --build
docker compose ps
