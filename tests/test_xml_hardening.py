"""Phase 103 (S2): XML-Haertung externer Server-Antworten via safe_fromstring.

Sichert ab, dass boesartiges PROPFIND-XML (Entity-Expansion / externe Entity /
reine DTD) NICHT expandiert/akzeptiert, sondern abgewehrt wird -- in
carddav_sync und nextcloud_files. Der DTD-only-Fall deckt speziell
``forbid_dtd=True`` ab (ohne das Flag wuerde ein DOCTYPE ungehindert geparst).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from defusedxml.common import DefusedXmlException

from elder_berry.tools.nextcloud_files import NextcloudError

# Billion-Laughs: die Entity-Deklaration triggert defusedxml (EntitiesForbidden).
BILLION_LAUGHS = (
    '<?xml version="1.0"?>\n'
    "<!DOCTYPE lolz [\n"
    '  <!ENTITY lol "lol">\n'
    '  <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;">\n'
    '  <!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;">\n'
    "]>\n"
    '<d:multistatus xmlns:d="DAV:"><d:response><d:href>&lol3;</d:href>'
    "</d:response></d:multistatus>"
)

# Externe Entity (XXE-Klasse).
XXE_PAYLOAD = (
    '<?xml version="1.0"?>\n'
    "<!DOCTYPE foo [\n"
    '  <!ENTITY xxe SYSTEM "file:///etc/passwd">\n'
    "]>\n"
    '<d:multistatus xmlns:d="DAV:"><d:response><d:href>&xxe;</d:href>'
    "</d:response></d:multistatus>"
)

# Reine DTD ohne Entities -- wird NUR durch forbid_dtd=True abgewehrt.
DTD_ONLY = (
    '<?xml version="1.0"?>\n'
    "<!DOCTYPE multistatus>\n"
    '<d:multistatus xmlns:d="DAV:"><d:response>'
    "<d:href>/remote.php/dav/files/saleria/x.vcf</d:href>"
    "</d:response></d:multistatus>"
)

MALICIOUS = [BILLION_LAUGHS, XXE_PAYLOAD, DTD_ONLY]


def _nc_secret_store() -> MagicMock:
    store = MagicMock()
    store.get_or_none.side_effect = lambda key: {
        "nextcloud_url": "https://cloud.example.com",
        "nextcloud_user": "saleria",
        "nextcloud_app_password": "secret-app-pw",
    }.get(key)
    return store


class TestNextcloudParsePropfindHardened:
    @pytest.mark.parametrize("payload", MALICIOUS)
    def test_malicious_xml_raises_nextcloud_error(self, payload):
        from elder_berry.tools.nextcloud_files import NextcloudFilesClient

        client = NextcloudFilesClient(secret_store=_nc_secret_store())
        with pytest.raises(NextcloudError):
            client._parse_propfind(payload)

    def test_dtd_payload_is_dtd_forbidden_under_the_hood(self):
        # Belegt, dass die Abwehr aus forbid_dtd stammt (DefusedXmlException).
        from elder_berry.tools.safe_xml import safe_fromstring

        with pytest.raises(DefusedXmlException):
            safe_fromstring(DTD_ONLY)

    def test_get_file_id_malicious_xml_raises_nextcloud_error(self):
        # Deckt den fileid-Lookup-Pfad (_get_file_id) ab: gehaerteter Parser
        # wirft -> except -> NextcloudError statt roher DefusedXmlException.
        from elder_berry.tools.nextcloud_files import NextcloudFilesClient

        client = NextcloudFilesClient(secret_store=_nc_secret_store())
        resp = MagicMock(status_code=207, text=BILLION_LAUGHS)
        with patch(
            "elder_berry.tools.nextcloud_files.httpx.request", return_value=resp
        ):
            with pytest.raises(NextcloudError):
                client._get_file_id("Dokumente/report.pdf")

    def test_benign_xml_still_parses(self):
        from elder_berry.tools.nextcloud_files import NextcloudFilesClient

        benign = (
            '<?xml version="1.0"?>'
            '<d:multistatus xmlns:d="DAV:"><d:response>'
            "<d:href>/remote.php/dav/files/saleria/x.txt</d:href>"
            "<d:propstat><d:prop>"
            "<d:displayname>x.txt</d:displayname>"
            "<d:resourcetype/>"
            "<d:getcontentlength>5</d:getcontentlength>"
            "</d:prop></d:propstat></d:response></d:multistatus>"
        )
        client = NextcloudFilesClient(secret_store=_nc_secret_store())
        files = client._parse_propfind(benign)
        assert len(files) >= 1


class TestCardDavListHrefsHardened:
    @pytest.mark.parametrize("payload", MALICIOUS)
    def test_malicious_xml_yields_empty(self, payload):
        pytest.importorskip("vobject", reason="vobject nicht installiert")
        from elder_berry.tools.carddav_sync import CardDAVSyncClient

        store = MagicMock()
        store.get_or_none.side_effect = lambda key: {
            "nextcloud_url": "https://cloud.example.com",
            "nextcloud_user": "u",
            "nextcloud_app_password": "p",
        }.get(key)
        client = CardDAVSyncClient(secret_store=store)

        resp = MagicMock(status_code=207, text=payload)
        with patch(
            "elder_berry.tools.carddav_sync.httpx.request", return_value=resp
        ):
            # Gehaerteter Parser wirft -> except faengt -> leere Liste,
            # statt die Entities/DTD zu verarbeiten.
            assert client._list_vcf_hrefs() == []
