#!/usr/bin/env bash
# tools/build-deploy.sh — Cross-build Ariadne for linux/amd64 and deploy to a Droplet.
#
# Usage:
#   DROPLET_IP=x.x.x.x ./tools/build-deploy.sh
#
# Optional overrides:
#   DROPLET_USER=root          SSH user (default: root)
#   REMOTE_REPO_DIR=<path>     Repo Ariadne should investigate on the server
#                              (default: the Ariadne project itself)
#   IMAGE=ravisankarmbp/ariadne:latest  Docker Hub image tag
#
# What this script does:
#   1. Cross-builds the image for linux/amd64 on your Mac and pushes to Docker Hub
#   2. SCPs docker-compose.yml, bot/.env, and ~/.codex/auth.json to the server
#   3. SSHs in and:
#        - Installs Docker if not present
#        - Stops any running container
#        - Writes the root .env for docker-compose variable substitution
#        - Patches bot/.env with server-side paths
#        - Pulls the pre-built image from Docker Hub
#        - Starts the container

set -euo pipefail

# ── Configuration ──────────────────────────────────────────────────────────────

DROPLET_IP="${DROPLET_IP:?Usage: DROPLET_IP=x.x.x.x ./tools/deploy.sh}"
DROPLET_USER="${DROPLET_USER:-root}"
IMAGE="${IMAGE:-ravisankarmbp/ariadne:latest}"

REMOTE_HOME="/root"
REMOTE_PROJECT_DIR="$REMOTE_HOME/ariadne"
REMOTE_LOGS_DIR="$REMOTE_HOME/ariadne-logs"
REMOTE_REPO_DIR="${REMOTE_REPO_DIR:-$REMOTE_PROJECT_DIR}"

LOCAL_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# ── 1. Cross-build and push ────────────────────────────────────────────────────

echo "==> Cross-building linux/amd64 image and pushing to Docker Hub..."
echo "    Image: $IMAGE"
echo "    (This takes ~15-20 min on first build; subsequent builds are faster)"
echo ""

# Ensure the cross-builder exists
if ! docker buildx inspect cross-builder &>/dev/null; then
  docker buildx create --name cross-builder --driver docker-container
fi

docker buildx build \
  --builder cross-builder \
  --platform linux/amd64 \
  -t "$IMAGE" \
  "$LOCAL_ROOT/bot" \
  --push

echo ""
echo "    Image pushed: $IMAGE"

# ── 2. Copy config files to server ────────────────────────────────────────────

echo "==> Copying config files to $DROPLET_USER@$DROPLET_IP..."

ssh "$DROPLET_USER@$DROPLET_IP" "mkdir -p $REMOTE_PROJECT_DIR/bot $REMOTE_HOME/.codex"

scp -q "$LOCAL_ROOT/docker-compose.yml"  "$DROPLET_USER@$DROPLET_IP:$REMOTE_PROJECT_DIR/docker-compose.yml"
scp -q "$LOCAL_ROOT/bot/.env"            "$DROPLET_USER@$DROPLET_IP:$REMOTE_PROJECT_DIR/bot/.env"
scp -q ~/.codex/auth.json                "$DROPLET_USER@$DROPLET_IP:$REMOTE_HOME/.codex/auth.json"

echo "    Done"

# ── 3. Remote setup ────────────────────────────────────────────────────────────

echo "==> Configuring server..."
ssh "$DROPLET_USER@$DROPLET_IP" bash <<REMOTE
set -euo pipefail

# ── Docker ─────────────────────────────────────────────────────────────────────
if ! command -v docker &>/dev/null; then
  echo "  Installing Docker..."
  apt-get update -q
  apt-get install -y -q ca-certificates curl gnupg
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=\$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu \$(. /etc/os-release && echo "\$VERSION_CODENAME") stable" \
    | tee /etc/apt/sources.list.d/docker.list > /dev/null
  apt-get update -q
  apt-get install -y -q docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
echo "  Docker: \$(docker --version)"

# ── Stop existing container ────────────────────────────────────────────────────
if [ -f "$REMOTE_PROJECT_DIR/docker-compose.yml" ]; then
  echo "  Stopping existing container..."
  cd "$REMOTE_PROJECT_DIR" && docker compose down 2>/dev/null || true
fi

# ── Directories ────────────────────────────────────────────────────────────────
mkdir -p "$REMOTE_LOGS_DIR"
mkdir -p "$REMOTE_REPO_DIR"
mkdir -p "$REMOTE_REPO_DIR/.ariadne"

# ── Root .env (compose variable substitution) ──────────────────────────────────
cat > "$REMOTE_PROJECT_DIR/.env" <<ENV
ARIADNE_REPO_HOST_PATH=$REMOTE_REPO_DIR
ARIADNE_BRIEFS_HOST_PATH=$REMOTE_REPO_DIR/.ariadne
LOGS_HOST_PATH=$REMOTE_LOGS_DIR
ENV
echo "  Root .env written"

# ── Patch bot/.env with server-side paths ─────────────────────────────────────
BOT_ENV="$REMOTE_PROJECT_DIR/bot/.env"
sed -i "s|ARIADNE_REPO_PATH=.*|ARIADNE_REPO_PATH=$REMOTE_REPO_DIR|" "\$BOT_ENV"
sed -i "s|LOGS_DIR=.*|LOGS_DIR=$REMOTE_LOGS_DIR|" "\$BOT_ENV"
sed -i "s|ARIADNE_PROJECT_BACKGROUND_PATH=.*|ARIADNE_PROJECT_BACKGROUND_PATH=$REMOTE_PROJECT_DIR/bot/ariadne/PROJECT_BACKGROUND.md|" "\$BOT_ENV"
echo "  bot/.env paths updated"

# ── Prune stale images ─────────────────────────────────────────────────────────
docker image prune -f

# ── Pull and start ─────────────────────────────────────────────────────────────
echo "  Pulling image $IMAGE..."
cd "$REMOTE_PROJECT_DIR"
docker compose pull
docker compose up -d

echo ""
echo "  Container status:"
docker compose ps
REMOTE

# ── Register Daily dial-in webhook ────────────────────────────────────────────

WEBHOOK_URL="http://$DROPLET_IP:7860/daily-dialin-webhook"
"$(dirname "$0")/register-dialin.sh" "$WEBHOOK_URL"

# ── Done ───────────────────────────────────────────────────────────────────────

echo ""
echo "==> Deployed successfully!"
echo ""
echo "    Dial-in number:   ${DAILY_DIALIN_PHONE_NUMBER:-<not set>}"
echo "    Pipecat webhook:  $WEBHOOK_URL"
echo "    Debug server:     http://$DROPLET_IP:8765/debug/sessions"
