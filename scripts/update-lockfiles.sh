#!/usr/bin/env bash
# Phase 65 (M-3): Regeneriert Dependency-Lockfiles via pip-compile.
#
# Nutzung:
#   bash scripts/update-lockfiles.sh dev    # Dev/CI-Lockfile (cross-platform Core)
#   bash scripts/update-lockfiles.sh rpi5   # RPi5-Lockfile (muss AUF dem RPi5 laufen)
#   bash scripts/update-lockfiles.sh all    # dev + rpi5 (Tower-Lockfile separat via .ps1)
#
# Das Tower-Lockfile (Windows + pyautogui/pycaw) muss auf Windows
# generiert werden: siehe scripts/update-lockfiles.ps1.

set -euo pipefail

TARGET="${1:-all}"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

compile_lockfile() {
    local out="$1"
    local desc="$2"
    shift 2
    local extras=("$@")

    echo ""
    echo "=== $desc ==="
    echo "Output: $out"
    echo "Extras: ${extras[*]}"

    local extras_args=()
    for e in "${extras[@]}"; do
        extras_args+=("--extra=$e")
    done

    python -m piptools compile pyproject.toml \
        "${extras_args[@]}" \
        --output-file="$out" \
        --resolver=backtracking \
        --strip-extras \
        --quiet
    echo "OK: $out"
}

case "$TARGET" in
    dev)
        compile_lockfile "requirements-dev.lock" \
            "Dev/CI-Lockfile (cross-platform Core)" \
            "robot" "agent" "dev"
        ;;
    rpi5)
        compile_lockfile "requirements-rpi5.lock" \
            "RPi5-Lockfile (Linux ARM)" \
            "robot" "agent" "matrix" "memory" "nextcloud" "harmony" "avatar"
        ;;
    all)
        compile_lockfile "requirements-dev.lock" \
            "Dev/CI-Lockfile (cross-platform Core)" \
            "robot" "agent" "dev"
        compile_lockfile "requirements-rpi5.lock" \
            "RPi5-Lockfile (Linux ARM)" \
            "robot" "agent" "matrix" "memory" "nextcloud" "harmony" "avatar"
        ;;
    *)
        echo "Unbekanntes Target: $TARGET"
        echo "Verwende: dev | rpi5 | all"
        exit 1
        ;;
esac
