#!/usr/bin/env bash
# MMSN Clipper — one-command setup for an Oracle Cloud Always Free VM.
#
# Run this ON the VM (Ubuntu 22.04/24.04, Ampere A1) — e.g. from Oracle
# Cloud Shell in your phone browser, or any terminal on the VM.
# It installs Docker, fetches this repo, creates your .env with random
# secrets, and starts the whole stack (backend + Postgres + Caddy/HTTPS).
#
# Before running it you must have, from DEPLOYMENT.md "Option A":
#   1. An Oracle Cloud account and a running Ampere A1 VM (Always Free).
#   2. A domain (or free subdomain/DDNS) name pointing at the VM's public IP.
#      Pass it like this:  DOMAIN=clipper.example.com bash scripts/oracle-setup.sh
#   3. Ports 80 and 443 open in the VM's security list / firewall.
#
# Nothing in this script costs money. It only installs free, open-source
# software. It never prints your secrets to the screen.
set -euo pipefail

REPO_URL="https://github.com/shauryasinghchauhanpw/Mmsn.git"
APP_DIR="${APP_DIR:-$HOME/mmsn}"
DOMAIN="${DOMAIN:-}"

if [ -z "$DOMAIN" ]; then
  echo "DOMAIN is not set. Pass your domain like this:"
  echo "  DOMAIN=clipper.example.com bash scripts/oracle-setup.sh"
  echo "(It must already point at this VM's public IP.)"
  exit 1
fi

# set_key KEY VALUE — replace the line in .env if the key exists,
# otherwise append it. (Appending a duplicate would NOT work: the
# backend reads the first occurrence of a key in .env.)
set_key() {
  local key="$1" value="$2"
  if grep -q "^${key}=" .env; then
    sed -i "s|^${key}=.*|${key}=${value}|" .env
  else
    printf '%s=%s\n' "$key" "$value" >> .env
  fi
}

echo "==> Installing Docker (Ubuntu)…"
sudo apt-get update -y
sudo apt-get install -y ca-certificates curl git docker.io docker-compose-plugin

echo "==> Starting Docker…"
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER" || true
# The group change only applies on next login; use sudo for docker
# in this session if plain `docker` does not work yet.
if docker info >/dev/null 2>&1; then DOCKER="docker"; else DOCKER="sudo docker"; fi

echo "==> Fetching the app code…"
if [ -d "$APP_DIR/.git" ]; then
  cd "$APP_DIR"
  git pull --ff-only || true
else
  git clone "$REPO_URL" "$APP_DIR"
  cd "$APP_DIR"
fi

echo "==> Creating .env (random secrets, never printed)…"
if [ ! -f .env ]; then
  cp .env.example .env
  set_key SECRET_KEY "$(python3 -c "import secrets; print(secrets.token_urlsafe(48))")"
  set_key POSTGRES_PASSWORD "$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")"
  set_key DOMAIN "$DOMAIN"
  # CORS must allow the Vercel frontend URL (the browser calls this
  # backend cross-origin from there). You do not know that URL yet, so
  # this is a placeholder — replace it after the Vercel deploy, then
  # restart the backend (see DEPLOYMENT.md, "After the Vercel deploy").
  set_key CORS_ORIGINS "https://YOUR-VERCEL-APP.vercel.app"
else
  echo ".env already exists — leaving it alone."
  echo "Check that DOMAIN=$DOMAIN and CORS_ORIGINS include your frontend URL."
fi

echo "==> Starting the stack (backend + Postgres + Caddy)…"
$DOCKER compose up -d --wait

echo ""
echo "Done. The backend should be live at: https://$DOMAIN"
echo "Check it with:  $DOCKER compose ps   and   $DOCKER compose logs -f backend"
echo "Frontend: deploy it free on Vercel (see DEPLOYMENT.md) with"
echo "NEXT_PUBLIC_API_URL=https://$DOMAIN"
echo "Then open https://$DOMAIN/health in your browser — it should show {\"status\":\"ok\",…}."
