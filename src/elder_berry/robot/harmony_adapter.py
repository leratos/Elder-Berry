"""HarmonyAdapter -- Lokale Steuerung des Logitech Harmony Hub.

Kommuniziert ueber die lokale WebSocket-API auf Port 8088.
Kein Logitech-Account, kein Cloud-Zugriff erforderlich.

Wird in Phase 37.2 als SmartHomeInterface-Implementierung formalisiert.
Voraussetzung: Hub und RPi5 im selben Netzwerk.

Verwendung:
    adapter = HarmonyAdapter(hub_ip="192.168.50.133")
    await adapter.connect()
    await adapter.start_activity("Fernsehen")
    await adapter.send_command(device="Receiver", command="VolumeUp")
    activity = await adapter.get_current_activity()
    await adapter.disconnect()

Plattformhinweis: Laeuft auf RPi5 (Linux). aioharmony ist optional.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG_PATH = Path.home() / ".elder-berry" / "harmony_config.json"
_HUB_PORT = 8088
_POWER_OFF_ACTIVITY_ID = -1


class HarmonyAdapterError(Exception):
    """Fehler bei der Kommunikation mit dem Harmony Hub."""


class HarmonyAdapter:
    """Logitech Harmony Hub Steuerung via lokaler WebSocket-API."""

    def __init__(
        self,
        hub_ip: str,
        config_path: Path = _DEFAULT_CONFIG_PATH,
    ) -> None:
        self.hub_ip = hub_ip
        self.config_path = config_path
        self._client: Any = None  # aioharmony HarmonyAPI
        self._config: dict = {}
        self._connected = False

    # -- Verbindung -------------------------------------------------------- #

    async def connect(self) -> bool:
        """Verbindet mit Hub. Laedt Config live, Fallback: Backup-JSON.

        Returns:
            True wenn Verbindung erfolgreich (oder Backup geladen).
        """
        if self._connected:
            logger.warning("HarmonyAdapter: Bereits verbunden")
            return True

        try:
            from aioharmony.harmonyapi import HarmonyAPI, SendCommandDevice

            client = HarmonyAPI(self.hub_ip)
            connected = await client.connect()

            if not connected:
                logger.warning(
                    "Hub %s nicht erreichbar, versuche Backup-Config",
                    self.hub_ip,
                )
                self._config = self._load_backup_config()
                if self._config:
                    self._connected = True
                    logger.info(
                        "Backup-Config geladen (%d Aktivitaeten, %d Geraete)",
                        len(self._config.get("activity", [])),
                        len(self._config.get("device", [])),
                    )
                    return True
                return False

            self._client = client
            self._connected = True

            # Config vom Hub laden
            if client.config:
                self._config = client.config
                logger.info(
                    "HarmonyAdapter verbunden mit %s (Config geladen)",
                    self.hub_ip,
                )
            else:
                # Fallback auf Backup
                self._config = self._load_backup_config()
                logger.info(
                    "HarmonyAdapter verbunden, Config aus Backup geladen",
                )

            return True

        except ImportError:
            logger.error(
                "aioharmony nicht installiert -- "
                "pip install aioharmony>=0.5.0"
            )
            return False
        except Exception as e:
            logger.error("Verbindung zu Hub %s fehlgeschlagen: %s", self.hub_ip, e)
            # Fallback auf Backup
            self._config = self._load_backup_config()
            if self._config:
                self._connected = True
                logger.info("Backup-Config als Fallback geladen")
                return True
            return False

    async def disconnect(self) -> None:
        """Trennt Verbindung sauber."""
        if self._client is not None:
            try:
                await self._client.close()
            except Exception as e:
                logger.warning("Fehler beim Trennen: %s", e)
            self._client = None
        self._connected = False
        logger.info("HarmonyAdapter getrennt")

    @property
    def is_connected(self) -> bool:
        return self._connected

    # -- Aktivitaeten ------------------------------------------------------ #

    async def start_activity(self, activity_name: str) -> bool:
        """Startet Aktivitaet per Name (case-insensitive).

        Returns:
            True wenn Aktivitaet erfolgreich gestartet.
        """
        if not self._connected:
            logger.error("start_activity: Nicht verbunden")
            return False

        activity_id = self._find_activity_id(activity_name)
        if activity_id is None:
            logger.error(
                "Aktivitaet '%s' nicht gefunden. Verfuegbar: %s",
                activity_name,
                ", ".join(self.list_activities_sync()),
            )
            return False

        if self._client is None:
            logger.error("start_activity: Kein Hub-Client (nur Backup-Config)")
            return False

        try:
            await self._client.start_activity(int(activity_id))
            logger.info("Aktivitaet gestartet: %s (ID: %s)", activity_name, activity_id)
            return True
        except Exception as e:
            logger.error("start_activity fehlgeschlagen: %s", e)
            return False

    async def power_off(self) -> bool:
        """Schaltet alle Geraete aus (PowerOff-Aktivitaet)."""
        if not self._connected:
            logger.error("power_off: Nicht verbunden")
            return False

        if self._client is None:
            logger.error("power_off: Kein Hub-Client (nur Backup-Config)")
            return False

        try:
            await self._client.power_off()
            logger.info("Power Off gesendet")
            return True
        except Exception as e:
            logger.error("power_off fehlgeschlagen: %s", e)
            return False

    async def get_current_activity(self) -> Optional[str]:
        """Gibt aktuellen Aktivitaetsnamen zurueck, None wenn PowerOff."""
        if not self._connected:
            return None

        if self._client is None:
            return None

        try:
            current = self._client.current_activity
            if current is None:
                return None

            # aioharmony gibt (id, name) Tuple oder nur id zurueck
            if isinstance(current, tuple):
                current_id, current_name = current
                if current_id == _POWER_OFF_ACTIVITY_ID:
                    return None
                return current_name

            current_id = current
            if current_id == _POWER_OFF_ACTIVITY_ID:
                return None

            # ID zu Name aufloesen
            for activity in self._get_activities():
                if str(activity.get("id")) == str(current_id):
                    return activity.get("label", str(current_id))
            return str(current_id)
        except Exception as e:
            logger.error("get_current_activity fehlgeschlagen: %s", e)
            return None

    async def list_activities(self) -> list[str]:
        """Alle konfigurierten Aktivitaeten (ohne PowerOff)."""
        return self.list_activities_sync()

    def list_activities_sync(self) -> list[str]:
        """Synchrone Variante fuer Logging und Fehlermeldungen."""
        result = []
        for activity in self._get_activities():
            label = activity.get("label", "")
            act_id = str(activity.get("id", ""))
            if label and act_id != str(_POWER_OFF_ACTIVITY_ID):
                result.append(label)
        return result

    # -- Geraetebefehle ---------------------------------------------------- #

    async def send_command(
        self,
        device: str,
        command: str,
        repeat: int = 1,
    ) -> bool:
        """Sendet IR-Befehl an Geraet (case-insensitive Namen).

        Args:
            device: Geraetename (z.B. "Receiver", "Samsung TV").
            command: Befehlsname (z.B. "VolumeUp", "Mute").
            repeat: Anzahl Wiederholungen.

        Returns:
            True wenn Befehl erfolgreich gesendet.
        """
        if not self._connected:
            logger.error("send_command: Nicht verbunden")
            return False

        if self._client is None:
            logger.error("send_command: Kein Hub-Client (nur Backup-Config)")
            return False

        device_id = self._find_device_id(device)
        if device_id is None:
            logger.error(
                "Geraet '%s' nicht gefunden. Verfuegbar: %s",
                device,
                ", ".join(await self.list_devices()),
            )
            return False

        # Befehl validieren
        available_cmds = self._get_device_commands(device_id)
        cmd_match = None
        for cmd in available_cmds:
            if cmd.lower() == command.lower():
                cmd_match = cmd
                break
        if cmd_match is None:
            logger.error(
                "Befehl '%s' fuer '%s' nicht gefunden. Verfuegbar: %s",
                command, device, ", ".join(available_cmds[:10]),
            )
            return False

        try:
            from aioharmony.harmonyapi import SendCommandDevice

            send_cmd = SendCommandDevice(
                device=int(device_id), command=cmd_match, delay=0,
            )
            for _ in range(repeat):
                await self._client.send_commands(send_cmd)
            logger.info(
                "Befehl gesendet: %s → %s (x%d)",
                device, cmd_match, repeat,
            )
            return True
        except Exception as e:
            logger.error("send_command fehlgeschlagen: %s", e)
            return False

    async def list_commands(self, device: str) -> list[str]:
        """Alle verfuegbaren Befehle fuer ein Geraet."""
        device_id = self._find_device_id(device)
        if device_id is None:
            return []
        return self._get_device_commands(device_id)

    async def list_devices(self) -> list[str]:
        """Alle konfigurierten Geraetenames."""
        result = []
        for dev in self._get_devices():
            label = dev.get("label", "")
            if label:
                result.append(label)
        return result

    # -- Detaillierte Config ------------------------------------------------ #

    def get_detailed_config(self) -> dict:
        """Vollstaendige Config fuer die PWA (Geraete-Modus + Aktivitaeten).

        Returns:
            Dict mit "activities" und "devices", jeweils mit allen
            ControlGroups und Commands. Fuer die PWA-Geraeteansicht.
        """
        activities = []
        for activity in self._get_activities():
            act_id = str(activity.get("id", ""))
            if act_id == str(_POWER_OFF_ACTIVITY_ID):
                continue
            entry: dict = {
                "id": act_id,
                "label": activity.get("label", ""),
            }
            # Volume/Channel-Device-Zuordnung (Device-ID → Name aufloesen)
            vol_id = activity.get("VolumeActivityRole")
            if vol_id:
                entry["volume_device"] = self._device_id_to_label(str(vol_id))
            ch_id = activity.get("ChannelChangingActivityRole")
            if ch_id:
                entry["channel_device"] = self._device_id_to_label(str(ch_id))
            activities.append(entry)

        devices = []
        for dev in self._get_devices():
            control_groups = []
            for group in dev.get("controlGroup", []):
                commands = [
                    f.get("name", "")
                    for f in group.get("function", [])
                    if f.get("name")
                ]
                if commands:
                    control_groups.append({
                        "name": group.get("name", ""),
                        "commands": commands,
                    })
            devices.append({
                "id": str(dev.get("id", "")),
                "label": dev.get("label", ""),
                "control_groups": control_groups,
            })

        return {"activities": activities, "devices": devices}

    def _device_id_to_label(self, device_id: str) -> str:
        """Loest Device-ID zu Label auf, Fallback auf ID."""
        for dev in self._get_devices():
            if str(dev.get("id", "")) == device_id:
                return dev.get("label", device_id)
        return device_id

    # -- Intern ------------------------------------------------------------ #

    def _load_backup_config(self) -> dict:
        """Laedt Konfiguration aus lokalem Backup-JSON."""
        if not self.config_path.exists():
            logger.warning("Backup-Config nicht gefunden: %s", self.config_path)
            return {}
        try:
            text = self.config_path.read_text(encoding="utf-8")
            config = json.loads(text)
            if not isinstance(config, dict):
                logger.error("Backup-Config ist kein dict: %s", type(config))
                return {}
            return config
        except json.JSONDecodeError as e:
            logger.error("Backup-Config malformed: %s", e)
            return {}
        except Exception as e:
            logger.error("Backup-Config laden fehlgeschlagen: %s", e)
            return {}

    def _get_activities(self) -> list[dict]:
        """Aktivitaeten aus Config extrahieren."""
        # aioharmony speichert unter config["activity"]
        activities = self._config.get("activity", [])
        if isinstance(activities, list):
            return activities
        return []

    def _get_devices(self) -> list[dict]:
        """Geraete aus Config extrahieren."""
        devices = self._config.get("device", [])
        if isinstance(devices, list):
            return devices
        return []

    def _find_activity_id(self, name: str) -> Optional[str]:
        """Sucht Aktivitaets-ID per Name (case-insensitive)."""
        name_lower = name.lower()
        for activity in self._get_activities():
            label = activity.get("label", "")
            if label.lower() == name_lower:
                return str(activity.get("id", ""))
        return None

    def _find_device_id(self, name: str) -> Optional[str]:
        """Sucht Geraete-ID per Name (case-insensitive)."""
        name_lower = name.lower()
        for dev in self._get_devices():
            label = dev.get("label", "")
            if label.lower() == name_lower:
                return str(dev.get("id", ""))
        return None

    def _get_device_commands(self, device_id: str) -> list[str]:
        """Alle Befehle fuer ein Geraet (per ID)."""
        for dev in self._get_devices():
            if str(dev.get("id", "")) == device_id:
                control_groups = dev.get("controlGroup", [])
                commands = []
                for group in control_groups:
                    for func in group.get("function", []):
                        cmd_name = func.get("name", "")
                        if cmd_name:
                            commands.append(cmd_name)
                return commands
        return []
