#!/bin/bash
# Deploy Dashboard PWA zu einem Remote-Server.
#
# Nutzung:
#   ELDER_BERRY_DEPLOY_USER=user \
#   ELDER_BERRY_DEPLOY_HOST=example.com \
#   ELDER_BERRY_DEPLOY_PATH=/var/www/example.com/dashboard/ \
#       bash scripts/deploy_dashboard.sh
#
# Voraussetzungen: SSH-Key fuer ${USER}@${HOST}, rsync installiert.

set -euo pipefail

DEPLOY_USER="${ELDER_BERRY_DEPLOY_USER:-user}"
DEPLOY_HOST="${ELDER_BERRY_DEPLOY_HOST:-example.com}"
DEPLOY_PATH="${ELDER_BERRY_DEPLOY_PATH:-/var/www/example.com/dashboard/}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SRC="$SCRIPT_DIR/../src/elder_berry/webapp/dashboard/"
DEST="${DEPLOY_USER}@${DEPLOY_HOST}:${DEPLOY_PATH}"

echo "Deploying Dashboard to ${DEPLOY_HOST}:${DEPLOY_PATH} ..."
rsync -avz \
    --exclude='*.md' \
    --exclude='.php-ini' \
    --exclude='.php-version' \
    --exclude='.venv' \
    --exclude='elder-berry' \
    "$SRC" "$DEST"

echo "Done."
