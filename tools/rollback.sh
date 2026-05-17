#!/usr/bin/env bash
# tools/rollback.sh — Redeploy a previous Ariadne image tag on a Droplet.
#
# Usage:
#   DROPLET_IP=x.x.x.x ./tools/rollback.sh <tag>
#   DROPLET_IP=x.x.x.x ./tools/rollback.sh v20260517-143022
#
# Optional overrides:
#   DROPLET_USER=root          SSH user (default: root)
#   IMAGE=ravisankarmbp/ariadne:latest  Docker Hub image (repo portion used)
#
# Lists recent deployments if no tag is given.

set -euo pipefail

DROPLET_IP="${DROPLET_IP:?Usage: DROPLET_IP=x.x.x.x ./tools/rollback.sh <tag>}"
DROPLET_USER="${DROPLET_USER:-root}"
IMAGE="${IMAGE:-ravisankarmbp/ariadne:latest}"
IMAGE_REPO="${IMAGE%:*}"

LOCAL_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HISTORY_FILE="$LOCAL_ROOT/tools/.deploy-history"

TAG="${1:-}"

if [[ -z "$TAG" ]]; then
  echo "Usage: DROPLET_IP=x.x.x.x ./tools/rollback.sh <tag>"
  echo ""
  if [[ -f "$HISTORY_FILE" ]]; then
    echo "Recent deployments (newest first):"
    tac "$HISTORY_FILE" | head -10
  else
    echo "(No local deploy history found. Check tools/.deploy-history)"
  fi
  exit 1
fi

REMOTE_PROJECT_DIR="/root/ariadne"

echo "==> Rolling back to $IMAGE_REPO:$TAG on $DROPLET_IP..."
echo ""

ssh "$DROPLET_USER@$DROPLET_IP" bash <<REMOTE
set -euo pipefail

echo "  Pulling $IMAGE_REPO:$TAG..."
docker pull "$IMAGE_REPO:$TAG"

echo "  Retagging as latest..."
docker tag "$IMAGE_REPO:$TAG" "$IMAGE_REPO:latest"

echo "  Restarting container..."
cd "$REMOTE_PROJECT_DIR"
docker compose up -d

echo "$TAG" > "$REMOTE_PROJECT_DIR/.ariadne-version"
echo "  Rolled back to: $TAG"

echo ""
echo "  Container status:"
docker compose ps
REMOTE

echo ""
echo "==> Rollback complete: $TAG"
