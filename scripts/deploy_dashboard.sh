#!/bin/bash
# Deploy Dashboard PWA zu fern.last-strawberry.com
# Voraussetzung: SSH-Key für lera@last-strawberry.com konfiguriert
#
# Zielverzeichnis: /var/www/vhosts/last-strawberry.com/fern/
# (Plesk-Subdomain, Document Root)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SRC="$SCRIPT_DIR/../src/elder_berry/webapp/dashboard/"
DEST="lera@last-strawberry.com:/var/www/vhosts/last-strawberry.com/fern/"

echo "Deploying Dashboard to fern.last-strawberry.com ..."
rsync -avz \
    --exclude='*.md' \
    --exclude='.php-ini' \
    --exclude='.php-version' \
    --exclude='.venv' \
    --exclude='elder-berry' \
    "$SRC" "$DEST"

echo "Done."
