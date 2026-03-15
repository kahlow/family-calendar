#!/usr/bin/env bash
set -euo pipefail

REMOTE="${1:?Usage: ./deploy.sh user@tnas-ip}"
REMOTE_DIR="/Volume1/docker/family-calendar-briefing"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
IMAGE="family-calendar-sync"
echo "==> Building Docker image..."
docker build -t "$IMAGE" "$SCRIPT_DIR"

echo "==> Creating directories on TNAS..."
ssh "$REMOTE" "mkdir -p ${REMOTE_DIR}/html ${REMOTE_DIR}/history"

echo "==> Copying docker-compose.yml..."
cat "$SCRIPT_DIR/docker-compose.yml" | ssh "$REMOTE" "cat > ${REMOTE_DIR}/docker-compose.yml"

echo "==> Copying index.html..."
cat "$SCRIPT_DIR/html/index.html" | ssh "$REMOTE" "cat > ${REMOTE_DIR}/html/index.html"

echo "==> Streaming image to TNAS (this may take a minute)..."
docker save "$IMAGE" | gzip | ssh "$REMOTE" "docker load"

echo "==> Starting services..."
ssh "$REMOTE" "cd ${REMOTE_DIR} && docker compose down && docker compose up -d"

echo ""
echo "Done! First-time setup reminder:"
echo "  If you haven't already, copy your secrets to the TNAS:"
echo "    cat .env | ssh ${REMOTE} 'cat > ${REMOTE_DIR}/.env'"
echo "    cat token.json | ssh ${REMOTE} 'cat > ${REMOTE_DIR}/token.json'"
echo ""
echo "  Then trigger a manual sync:"
echo "    ssh ${REMOTE} 'cd ${REMOTE_DIR} && docker compose exec calendar-sync python sync.py'"
