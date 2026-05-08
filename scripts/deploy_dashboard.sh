#!/bin/bash
# Deploy Dashboard PWA zu einem Remote-Server.
#
# Bestand-Verhalten (Phase 77.5): rsync ohne Source-Modifikation. Phase 78
# Etappe 3 hat das veraltet -- die index.html im Repo hat einen Platzhalter
# (<meta name="elderberry-server-host" content="example.com">), der
# server-spezifisch ersetzt werden muss, damit das ausgelieferte Dashboard
# weiss, dass es im Server-Modus laeuft (relative Backend-Calls statt
# LAN-IPs).
#
# Loesung: Build-Step in temporaerem Verzeichnis -- die Repo-Datei bleibt
# unveraendert (LAN-Default), das ausgelieferte index.html bekommt den
# echten Domain-Namen. Damit ueberlebt git-pull auf dem Server keine
# manuellen Edits zerstoeren -- es gibt keine.
#
# Nutzung (alle 4 Variablen sind PFLICHT, fail-closed wenn nicht gesetzt
# oder noch auf "example.com"):
#
#   ELDER_BERRY_DEPLOY_USER=lera \
#   ELDER_BERRY_DEPLOY_HOST=last-strawberry.com \
#   ELDER_BERRY_DEPLOY_PATH=/var/www/vhosts/last-strawberry.com/fern \
#   ELDER_BERRY_DASHBOARD_HOST=fern.last-strawberry.com \
#       bash scripts/deploy_dashboard.sh
#
# Hinweis:
# - DEPLOY_HOST ist das SSH-Ziel (was rsync ansprechen kann).
# - DASHBOARD_HOST ist die Domain unter der die PWA aufgerufen wird --
#   kann abweichen (Subdomain, Bastion-Host, ...). Wird in das
#   <meta name="elderberry-server-host">-Attribut substituiert. Die
#   PWA matcht location.hostname.includes(DASHBOARD_HOST), um den
#   Server-Modus zu erkennen.
#
# Voraussetzungen: SSH-Key fuer DEPLOY_USER@DEPLOY_HOST, rsync installiert.

set -euo pipefail

# ---------------------------------------------------------------------------
# Variablen einlesen + validieren
# ---------------------------------------------------------------------------

DEPLOY_USER="${ELDER_BERRY_DEPLOY_USER:-}"
DEPLOY_HOST="${ELDER_BERRY_DEPLOY_HOST:-}"
DEPLOY_PATH="${ELDER_BERRY_DEPLOY_PATH:-}"
DASHBOARD_HOST="${ELDER_BERRY_DASHBOARD_HOST:-}"

require_var() {
    local name="$1"
    local value="$2"
    if [ -z "$value" ]; then
        echo "FEHLER: ${name} ist nicht gesetzt." >&2
        echo "Bitte alle 4 Deploy-Variablen explizit als ENV setzen --" >&2
        echo "siehe Header dieses Skripts." >&2
        exit 1
    fi
    if [ "$value" = "example.com" ]; then
        echo "FEHLER: ${name} ist auf 'example.com' -- das ist der Default-" >&2
        echo "Platzhalter, kein echter Wert. Bitte explizit setzen." >&2
        exit 1
    fi
}

require_var ELDER_BERRY_DEPLOY_USER "$DEPLOY_USER"
require_var ELDER_BERRY_DEPLOY_HOST "$DEPLOY_HOST"
require_var ELDER_BERRY_DEPLOY_PATH "$DEPLOY_PATH"
require_var ELDER_BERRY_DASHBOARD_HOST "$DASHBOARD_HOST"

# ---------------------------------------------------------------------------
# Build-Step: Quelle in temporaeres Dir kopieren + Platzhalter ersetzen
# ---------------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SRC="$SCRIPT_DIR/../src/elder_berry/webapp/dashboard"

if [ ! -d "$SRC" ]; then
    echo "FEHLER: Source-Verzeichnis nicht gefunden: $SRC" >&2
    exit 1
fi

BUILD_DIR="$(mktemp -d -t elder-berry-deploy-XXXXXX)"
trap 'rm -rf "$BUILD_DIR"' EXIT

echo "[1/3] Build-Verzeichnis: $BUILD_DIR"
cp -R "$SRC"/* "$BUILD_DIR/"

INDEX="$BUILD_DIR/index.html"
if [ ! -f "$INDEX" ]; then
    echo "FEHLER: $INDEX fehlt -- Source-Verzeichnis defekt?" >&2
    exit 1
fi

# BSD-/GNU-sed-portabel via Output-Redirect (kein -i mit Backup-Suffix-
# Inkonsistenz zwischen Plattformen). Der Platzhalter-String steht im
# Repo bewusst genau so -- Aenderungen an index.html muessen den
# Substitutions-Pattern hier mitziehen.
sed -e "s|content=\"example.com\"|content=\"${DASHBOARD_HOST}\"|" \
    "$INDEX" > "$INDEX.tmp"
mv "$INDEX.tmp" "$INDEX"

# Verifikation: Substitution ist passiert. Ohne diesen Check koennte ein
# umbenanntes Attribut o.ae. einen No-Op-Build erzeugen -- der waere dann
# auf dem Server unbrauchbar (LAN-Modus mit hardcoded IP).
if grep -q 'content="example.com"' "$INDEX"; then
    echo "FEHLER: Substitution fehlgeschlagen -- Build-Index enthaelt" >&2
    echo "noch 'example.com'. Wurde der meta-Tag in index.html umbenannt?" >&2
    exit 1
fi
if ! grep -q "content=\"${DASHBOARD_HOST}\"" "$INDEX"; then
    echo "FEHLER: Dashboard-Host '${DASHBOARD_HOST}' fehlt im Build-Index." >&2
    exit 1
fi
echo "[2/3] meta-Tag substituiert: example.com -> ${DASHBOARD_HOST}"

# ---------------------------------------------------------------------------
# rsync zum Remote
# ---------------------------------------------------------------------------

# Trailing-Slash am DEPLOY_PATH normalisieren -- rsync-Semantik haengt davon
# ab, ob das Ziel-Verzeichnis selbst angelegt oder nur der Inhalt
# synchronisiert wird. Wir wollen den Inhalt von BUILD_DIR/ in DEPLOY_PATH/
# spiegeln, daher: beide mit trailing-Slash.
DEST="${DEPLOY_USER}@${DEPLOY_HOST}:${DEPLOY_PATH%/}/"
echo "[3/3] Deploy: ${BUILD_DIR}/ -> ${DEST}"

rsync -avz \
    --exclude='*.md' \
    --exclude='.php-ini' \
    --exclude='.php-version' \
    --exclude='.venv' \
    --exclude='elder-berry' \
    "$BUILD_DIR/" "$DEST"

echo
echo "Done. Dashboard erreichbar unter: https://${DASHBOARD_HOST}/"
