"""Tests: GymDataClient – Berry-Gym API Integration."""
from unittest.mock import MagicMock, patch

import pytest

from elder_berry.tools.gym_data import GymDataClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_store(with_token: bool = True):
    store = MagicMock()
    if with_token:
        store.get.return_value = "test-token-123"
        store.get_or_none.return_value = "test-token-123"
    else:
        store.get_or_none.return_value = None
    return store


MOCK_SUMMARY = {
    "letztes_training": {
        "datum": "2026-03-15T18:00:00Z",
        "dauer_minuten": 60,
        "uebungen_anzahl": 5,
    },
    "trainings_diese_woche": 3,
    "aktuelles_gewicht": {"gewicht_kg": 82.5, "datum": "2026-03-15T08:00:00Z"},
}

MOCK_LAST_TRAINING = {
    "training": {
        "datum": "2026-03-15T18:00:00Z",
        "dauer_minuten": 45,
        "kommentar": "Gutes Training",
        "ist_deload": False,
        "saetze": [
            {"uebung": "Bankdrücken", "gewicht_kg": 80.0, "wiederholungen": 8,
             "rpe": 8.0, "ist_aufwaermsatz": False, "satz_nr": 1},
            {"uebung": "Bankdrücken", "gewicht_kg": 80.0, "wiederholungen": 7,
             "rpe": 9.0, "ist_aufwaermsatz": False, "satz_nr": 2},
            {"uebung": "Rudern", "gewicht_kg": 60.0, "wiederholungen": 10,
             "rpe": 7.0, "ist_aufwaermsatz": False, "satz_nr": 1},
        ],
    }
}

MOCK_WEEK = {
    "trainings": [
        {"datum": "2026-03-15T18:00:00Z", "dauer_minuten": 60, "uebungen_anzahl": 5},
        {"datum": "2026-03-13T17:00:00Z", "dauer_minuten": 45, "uebungen_anzahl": 4},
    ]
}

MOCK_PRS = {
    "prs": [
        {"uebung": "Kreuzheben", "estimated_1rm": 163.3, "gewicht_kg": 140.0,
         "wiederholungen": 5, "datum": "2026-03-10T00:00:00Z"},
        {"uebung": "Bankdrücken", "estimated_1rm": 100.0, "gewicht_kg": 85.0,
         "wiederholungen": 6, "datum": "2026-03-12T00:00:00Z"},
    ]
}


# ---------------------------------------------------------------------------
# Init + is_available
# ---------------------------------------------------------------------------

class TestGymDataInit:
    def test_is_available_with_token(self):
        client = GymDataClient(secret_store=_make_store(True))
        assert client.is_available() is True

    def test_is_available_without_token(self):
        client = GymDataClient(secret_store=_make_store(False))
        assert client.is_available() is False

    def test_custom_base_url(self):
        client = GymDataClient(
            secret_store=_make_store(),
            base_url="http://localhost:8000",
        )
        assert client._base_url == "http://localhost:8000"

    def test_trailing_slash_stripped(self):
        client = GymDataClient(
            secret_store=_make_store(),
            base_url="https://gym.example.com/",
        )
        assert client._base_url == "https://gym.example.com"


# ---------------------------------------------------------------------------
# API Calls (mocked httpx)
# ---------------------------------------------------------------------------

class TestGymDataAPICalls:
    @patch("elder_berry.tools.gym_data.GymDataClient._get")
    def test_get_summary(self, mock_get):
        mock_get.return_value = MOCK_SUMMARY
        client = GymDataClient(secret_store=_make_store())
        result = client.get_summary()
        assert result == MOCK_SUMMARY
        mock_get.assert_called_once_with("/api/saleria/summary/")

    @patch("elder_berry.tools.gym_data.GymDataClient._get")
    def test_get_last_training(self, mock_get):
        mock_get.return_value = MOCK_LAST_TRAINING
        client = GymDataClient(secret_store=_make_store())
        result = client.get_last_training()
        assert result["datum"] == "2026-03-15T18:00:00Z"
        assert len(result["saetze"]) == 3

    @patch("elder_berry.tools.gym_data.GymDataClient._get")
    def test_get_last_training_none(self, mock_get):
        mock_get.return_value = {"training": None}
        client = GymDataClient(secret_store=_make_store())
        assert client.get_last_training() is None

    @patch("elder_berry.tools.gym_data.GymDataClient._get")
    def test_get_week(self, mock_get):
        mock_get.return_value = MOCK_WEEK
        client = GymDataClient(secret_store=_make_store())
        result = client.get_week()
        assert len(result) == 2

    @patch("elder_berry.tools.gym_data.GymDataClient._get")
    def test_get_week_api_error(self, mock_get):
        mock_get.return_value = None
        client = GymDataClient(secret_store=_make_store())
        assert client.get_week() == []

    @patch("elder_berry.tools.gym_data.GymDataClient._get")
    def test_get_prs(self, mock_get):
        mock_get.return_value = MOCK_PRS
        client = GymDataClient(secret_store=_make_store())
        result = client.get_prs()
        assert len(result) == 2
        assert result[0]["uebung"] == "Kreuzheben"


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

class TestGymDataFormat:
    def test_format_summary(self):
        client = GymDataClient(secret_store=_make_store())
        text = client.format_summary(MOCK_SUMMARY)
        assert "2026-03-15" in text
        assert "60 Min" in text
        assert "3 Trainings" in text
        assert "82.5 kg" in text

    def test_format_summary_no_training(self):
        client = GymDataClient(secret_store=_make_store())
        text = client.format_summary({
            "letztes_training": None,
            "trainings_diese_woche": 0,
            "aktuelles_gewicht": None,
        })
        assert "keins" in text.lower()

    def test_format_last_training(self):
        client = GymDataClient(secret_store=_make_store())
        text = client.format_last_training(MOCK_LAST_TRAINING["training"])
        assert "Bankdrücken" in text
        assert "80.0kg" in text
        assert "Rudern" in text
        assert "Gutes Training" in text
        assert "Satz 1" in text

    def test_format_last_training_deload(self):
        client = GymDataClient(secret_store=_make_store())
        training = {**MOCK_LAST_TRAINING["training"], "ist_deload": True}
        text = client.format_last_training(training)
        assert "Deload" in text

    def test_format_week(self):
        client = GymDataClient(secret_store=_make_store())
        text = client.format_week(MOCK_WEEK["trainings"])
        assert "2" in text
        assert "2026-03-15" in text

    def test_format_week_empty(self):
        client = GymDataClient(secret_store=_make_store())
        text = client.format_week([])
        assert "keine" in text.lower()

    def test_format_prs(self):
        client = GymDataClient(secret_store=_make_store())
        text = client.format_prs(MOCK_PRS["prs"])
        assert "Kreuzheben" in text
        assert "163.3" in text
        assert "1RM" in text

    def test_format_prs_empty(self):
        client = GymDataClient(secret_store=_make_store())
        text = client.format_prs([])
        assert "Keine" in text


# ---------------------------------------------------------------------------
# RemoteCommandHandler Integration
# ---------------------------------------------------------------------------

class TestGymCommands:
    def test_parse_training(self):
        from elder_berry.comms.remote_commands import RemoteCommandHandler
        handler = RemoteCommandHandler()
        assert handler.parse_command("training") == "training"

    def test_parse_training_details(self):
        from elder_berry.comms.remote_commands import RemoteCommandHandler
        handler = RemoteCommandHandler()
        assert handler.parse_command("training details") == "training"

    def test_parse_training_woche(self):
        from elder_berry.comms.remote_commands import RemoteCommandHandler
        handler = RemoteCommandHandler()
        assert handler.parse_command("training woche") == "training"

    def test_parse_prs(self):
        from elder_berry.comms.remote_commands import RemoteCommandHandler
        handler = RemoteCommandHandler()
        assert handler.parse_command("prs") == "prs"

    def test_parse_keyword_letztes_training(self):
        from elder_berry.comms.remote_commands import RemoteCommandHandler
        handler = RemoteCommandHandler()
        assert handler.parse_command("wie war mein letztes training") == "training"

    def test_parse_keyword_personal_records(self):
        from elder_berry.comms.remote_commands import RemoteCommandHandler
        handler = RemoteCommandHandler()
        assert handler.parse_command("zeig mir meine personal records") == "prs"

    def test_execute_training_no_client(self):
        from elder_berry.comms.remote_commands import RemoteCommandHandler
        handler = RemoteCommandHandler()
        result = handler.execute("training", "training")
        assert result.success is False
        assert "nicht konfiguriert" in result.text

    @patch("elder_berry.tools.gym_data.GymDataClient._get")
    def test_execute_training_summary(self, mock_get):
        from elder_berry.comms.remote_commands import RemoteCommandHandler
        mock_get.return_value = MOCK_SUMMARY
        client = GymDataClient(secret_store=_make_store())
        handler = RemoteCommandHandler(gym_client=client)
        result = handler.execute("training", "training")
        assert result.success is True
        assert "82.5 kg" in result.text

    @patch("elder_berry.tools.gym_data.GymDataClient._get")
    def test_execute_training_details(self, mock_get):
        from elder_berry.comms.remote_commands import RemoteCommandHandler
        mock_get.return_value = MOCK_LAST_TRAINING
        client = GymDataClient(secret_store=_make_store())
        handler = RemoteCommandHandler(gym_client=client)
        result = handler.execute("training", "training details")
        assert result.success is True
        assert "Bankdrücken" in result.text

    @patch("elder_berry.tools.gym_data.GymDataClient._get")
    def test_execute_prs(self, mock_get):
        from elder_berry.comms.remote_commands import RemoteCommandHandler
        mock_get.return_value = MOCK_PRS
        client = GymDataClient(secret_store=_make_store())
        handler = RemoteCommandHandler(gym_client=client)
        result = handler.execute("prs", "prs")
        assert result.success is True
        assert "Kreuzheben" in result.text
