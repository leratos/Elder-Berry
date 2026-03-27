"""RestartManager – Restart-Logik für den Elder-Berry Prozess.

Verwaltet:
- Restart-Flag (room_id + server_timestamp) für saubere Übergabe
- Instanz-Lock Freigabe vor Restart
- Prozess ersetzen (Windows: Popen + _exit, Linux: execv)
- Restart-Benachrichtigung nach erfolgreichem Neustart
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from elder_berry.comms.message_channel import MessageChannel
    from elder_berry.comms.scheduler_manager import SchedulerManager

logger = logging.getLogger(__name__)

# Restart-Flag: wird vor os.execv geschrieben, beim Start geprüft
RESTART_FLAG_FILE = Path(tempfile.gettempdir()) / "elder_berry_restart.flag"


def read_restart_timestamp() -> float:
    """Liest den Server-Timestamp aus dem Restart-Flag (Zeile 2).

    Flag-Format Zeile 2: Integer-Millisekunden (identisch mit
    event.server_timestamp aus matrix-nio → keine Float-Rundungsfehler).

    Returns:
        Server-Timestamp in Sekunden (float) oder 0.0 wenn nicht vorhanden.
    """
    if not RESTART_FLAG_FILE.exists():
        return 0.0
    try:
        lines = RESTART_FLAG_FILE.read_text(encoding="utf-8").strip().splitlines()
        if len(lines) >= 2:
            return int(lines[1]) / 1000.0
    except (ValueError, OSError) as e:
        logger.debug("Restart-Timestamp lesen fehlgeschlagen: %s", e)
    return 0.0


async def send_restart_notification(channel: MessageChannel) -> None:
    """Prüft ob ein Restart-Flag existiert und sendet Begrüßung.

    Wird beim Start aufgerufen (vor sync_loop). Löscht das Flag nach dem Senden.
    Flag-Format: Zeile 1 = room_id, Zeile 2 = server_timestamp (optional).
    """
    if not RESTART_FLAG_FILE.exists():
        return

    try:
        lines = RESTART_FLAG_FILE.read_text(encoding="utf-8").strip().splitlines()
        RESTART_FLAG_FILE.unlink(missing_ok=True)

        room_id = lines[0].strip() if lines else ""
        if room_id:
            await channel.send_text(
                room_id,
                "Bin wieder da! Neustart erfolgreich. ✅",
            )
            logger.info("Restart-Benachrichtigung gesendet an %s", room_id)
    except Exception as e:
        logger.error("Restart-Benachrichtigung fehlgeschlagen: %s", e)
        RESTART_FLAG_FILE.unlink(missing_ok=True)


def release_instance_lock() -> None:
    """Gibt den Singleton-Lock frei (für Restart).

    Sucht die Lock-Freigabe-Funktion aus start_saleria.py und ruft sie auf.
    Fallback: Lock-Datei direkt schließen/löschen.
    """
    main_module = sys.modules.get("__main__")
    release_fn = getattr(main_module, "_release_instance_lock", None)
    if callable(release_fn):
        try:
            release_fn()
            logger.debug("Instanz-Lock über __main__ freigegeben")
            return
        except Exception as e:
            logger.debug("Lock-Freigabe über __main__ fehlgeschlagen: %s", e)

    # Fallback: Lock-Datei direkt löschen
    lock_path = Path(sys.argv[0]).parent.parent / ".saleria.lock"
    try:
        lock_path.unlink(missing_ok=True)
        logger.debug("Lock-Datei direkt gelöscht: %s", lock_path)
    except Exception as e:
        logger.debug("Lock-Datei löschen fehlgeschlagen: %s", e)


async def perform_restart(
    channel: MessageChannel,
    scheduler_mgr: SchedulerManager | None,
    room_id: str,
    *,
    msg_server_ts: float = 0.0,
) -> None:
    """Schreibt Restart-Flag und startet den Prozess neu.

    Args:
        channel: MessageChannel zum Disconnecten.
        scheduler_mgr: SchedulerManager zum Stoppen.
        room_id: Room-ID für die Rückmeldung nach dem Restart.
        msg_server_ts: Server-Timestamp der auslösenden Nachricht.
    """
    logger.info("Restart angefordert, starte Prozess neu...")

    # Flag-Datei schreiben: room_id + Server-Timestamp als ms-Integer
    flag_content = room_id
    if msg_server_ts > 0:
        flag_content += f"\n{int(msg_server_ts * 1000)}"
    try:
        RESTART_FLAG_FILE.write_text(flag_content, encoding="utf-8")
    except Exception as e:
        logger.error("Restart-Flag schreiben fehlgeschlagen: %s", e)

    # Alle Scheduler stoppen
    if scheduler_mgr:
        scheduler_mgr.stop_all()

    try:
        await channel.disconnect()
    except Exception as e:
        logger.debug("Disconnect bei Restart (ignoriert): %s", e)

    # Instanz-Lock freigeben BEVOR der neue Prozess startet
    release_instance_lock()

    # Prozess ersetzen: gleiche Python-Exe + gleiche Argumente
    python = sys.executable
    args = sys.argv[:]

    logger.info("Restart: %s %s", python, args)
    try:
        if sys.platform == "win32":
            subprocess.Popen([python, *args])
            logger.info("Neuer Prozess gestartet, beende aktuellen...")
            os._exit(0)
        else:
            os.execv(python, [python, *args])
    except Exception as e:
        logger.error("Restart fehlgeschlagen: %s", e)
        RESTART_FLAG_FILE.unlink(missing_ok=True)
