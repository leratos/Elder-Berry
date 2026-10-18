"""Tests für die öffentliche ``has_credentials``-Property (#1422 E2-neu).

NextcloudFilesClient, NextcloudNotesClient, CardDAVSyncClient und
StirlingPDFClient: True nur bei vollständigen Zugangsdaten. Die Property
delegiert an das bestehende ``_has_credentials``.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from elder_berry.tools.nextcloud_files import NextcloudFilesClient
from elder_berry.tools.nextcloud_notes_client import NextcloudNotesClient
from elder_berry.tools.stirling_pdf import StirlingPDFClient

_NC_FULL = {
    "nextcloud_url": "https://cloud.x",
    "nextcloud_user": "u",
    "nextcloud_app_password": "p",
}
_STIRLING_FULL = {
    "stirling_pdf_url": "https://pdf.x",
    "stirling_pdf_api_key": "k",
}


def _store(values: dict[str, str]) -> MagicMock:
    store = MagicMock()
    store.get_or_none.side_effect = values.get
    store.get.side_effect = values.__getitem__
    return store


def _nextcloud_classes():
    classes = [NextcloudFilesClient, NextcloudNotesClient]
    try:
        from elder_berry.tools.carddav_sync import CardDAVSyncClient
    except ImportError:  # vobject optional
        return classes
    return [*classes, CardDAVSyncClient]


@pytest.mark.parametrize("cls", _nextcloud_classes())
class TestNextcloudClients:
    def test_full_credentials(self, cls):
        assert cls(secret_store=_store(_NC_FULL)).has_credentials is True

    @pytest.mark.parametrize("missing", sorted(_NC_FULL))
    def test_missing_value(self, cls, missing):
        values = {k: v for k, v in _NC_FULL.items() if k != missing}
        assert cls(secret_store=_store(values)).has_credentials is False

    def test_empty_value(self, cls):
        values = {**_NC_FULL, "nextcloud_app_password": ""}
        assert cls(secret_store=_store(values)).has_credentials is False

    def test_delegates_to_private(self, cls):
        client = cls(secret_store=_store(_NC_FULL))
        assert client.has_credentials == client._has_credentials


class TestStirling:
    def test_full_credentials(self):
        client = StirlingPDFClient(secret_store=_store(_STIRLING_FULL))
        assert client.has_credentials is True

    @pytest.mark.parametrize("missing", sorted(_STIRLING_FULL))
    def test_missing_value(self, missing):
        values = {k: v for k, v in _STIRLING_FULL.items() if k != missing}
        assert StirlingPDFClient(secret_store=_store(values)).has_credentials is False
