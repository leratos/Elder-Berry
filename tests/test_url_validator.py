"""Tests fuer src/elder_berry/core/url_validator.py (Phase 64, H-3)."""
from __future__ import annotations

import socket
from unittest.mock import patch

import pytest

from elder_berry.core.url_validator import UnsafeUrlError, ensure_public_url


def _mock_getaddrinfo(*ips: str):
    """Helper: patcht socket.getaddrinfo so, dass die uebergebenen IPs
    als Aufloesungs-Ergebnis geliefert werden (eine IP pro Record)."""
    records = [(None, None, None, None, (ip, 0)) for ip in ips]
    return patch(
        "elder_berry.core.url_validator.socket.getaddrinfo",
        return_value=records,
    )


class TestSchemeValidation:
    def test_http_with_public_ip_ok(self):
        with _mock_getaddrinfo("8.8.8.8"):
            assert ensure_public_url("http://example.com") == "http://example.com"

    def test_https_with_public_ip_ok(self):
        with _mock_getaddrinfo("8.8.8.8"):
            assert ensure_public_url("https://example.com") == "https://example.com"

    def test_url_is_stripped(self):
        with _mock_getaddrinfo("8.8.8.8"):
            assert ensure_public_url("  https://example.com  ") == "https://example.com"

    def test_file_scheme_rejected(self):
        with pytest.raises(UnsafeUrlError, match="Schema"):
            ensure_public_url("file:///etc/passwd")

    def test_gopher_scheme_rejected(self):
        with pytest.raises(UnsafeUrlError, match="Schema"):
            ensure_public_url("gopher://example.com/")

    def test_ftp_scheme_rejected(self):
        with pytest.raises(UnsafeUrlError, match="Schema"):
            ensure_public_url("ftp://example.com/")

    def test_javascript_scheme_rejected(self):
        with pytest.raises(UnsafeUrlError, match="Schema"):
            ensure_public_url("javascript:alert(1)")

    def test_data_scheme_rejected(self):
        with pytest.raises(UnsafeUrlError, match="Schema"):
            ensure_public_url("data:text/html,<h1>x</h1>")

    def test_empty_string_rejected(self):
        with pytest.raises(UnsafeUrlError, match="leer"):
            ensure_public_url("")

    def test_whitespace_only_rejected(self):
        with pytest.raises(UnsafeUrlError, match="leer"):
            ensure_public_url("   ")

    def test_missing_host_rejected(self):
        with pytest.raises(UnsafeUrlError, match="Host"):
            ensure_public_url("http:///pfad")


class TestIPBlocklist:
    def test_loopback_127_blocked(self):
        with _mock_getaddrinfo("127.0.0.1"):
            with pytest.raises(UnsafeUrlError, match="nicht-oeffentliche"):
                ensure_public_url("http://localhost")

    def test_loopback_allowed_when_flag_set(self):
        with _mock_getaddrinfo("127.0.0.1"):
            result = ensure_public_url(
                "http://localhost",
                allow_loopback=True,
            )
            assert result == "http://localhost"

    def test_private_10_blocked(self):
        with _mock_getaddrinfo("10.1.2.3"):
            with pytest.raises(UnsafeUrlError, match="nicht-oeffentliche"):
                ensure_public_url("http://10.1.2.3")

    def test_private_192_168_blocked(self):
        with _mock_getaddrinfo("192.168.0.1"):
            with pytest.raises(UnsafeUrlError, match="nicht-oeffentliche"):
                ensure_public_url("http://192.168.0.1")

    def test_private_172_16_blocked(self):
        with _mock_getaddrinfo("172.16.42.1"):
            with pytest.raises(UnsafeUrlError, match="nicht-oeffentliche"):
                ensure_public_url("http://172.16.42.1")

    def test_aws_metadata_link_local_blocked(self):
        with _mock_getaddrinfo("169.254.169.254"):
            with pytest.raises(UnsafeUrlError, match="nicht-oeffentliche"):
                ensure_public_url("http://169.254.169.254/latest/meta-data/")

    def test_multicast_blocked(self):
        with _mock_getaddrinfo("224.0.0.1"):
            with pytest.raises(UnsafeUrlError, match="nicht-oeffentliche"):
                ensure_public_url("http://224.0.0.1")

    def test_unspecified_blocked(self):
        with _mock_getaddrinfo("0.0.0.0"):
            with pytest.raises(UnsafeUrlError, match="nicht-oeffentliche"):
                ensure_public_url("http://0.0.0.0")

    def test_ipv6_loopback_blocked(self):
        with _mock_getaddrinfo("::1"):
            with pytest.raises(UnsafeUrlError, match="nicht-oeffentliche"):
                ensure_public_url("http://[::1]")

    def test_ipv6_link_local_blocked(self):
        with _mock_getaddrinfo("fe80::1"):
            with pytest.raises(UnsafeUrlError, match="nicht-oeffentliche"):
                ensure_public_url("http://[fe80::1]")

    def test_ipv4_mapped_ipv6_private_blocked(self):
        # ::ffff:10.0.0.1 -- IPv4-mapped Form von 10.0.0.1
        with _mock_getaddrinfo("::ffff:10.0.0.1"):
            with pytest.raises(UnsafeUrlError, match="nicht-oeffentliche"):
                ensure_public_url("http://[::ffff:a00:1]")

    def test_public_ipv4_allowed(self):
        with _mock_getaddrinfo("8.8.8.8"):
            assert ensure_public_url("http://8.8.8.8") == "http://8.8.8.8"

    def test_public_ipv6_allowed(self):
        with _mock_getaddrinfo("2001:4860:4860::8888"):
            assert ensure_public_url("http://[2001:4860:4860::8888]") == \
                "http://[2001:4860:4860::8888]"

    def test_any_private_record_blocks_even_if_public_present(self):
        # DNS-Rebinding-Schutz: liefert DNS mehrere A-Records, und einer
        # davon zeigt auf eine private IP, MUSS die URL blockiert werden
        # (sonst koennte ein Angreifer via Round-Robin zufaellig die
        # oeffentliche IP beim Fetch treffen und die private spaeter).
        with _mock_getaddrinfo("8.8.8.8", "10.0.0.1"):
            with pytest.raises(UnsafeUrlError, match="nicht-oeffentliche"):
                ensure_public_url("http://multi-record.example.com")

    def test_all_public_records_allowed(self):
        with _mock_getaddrinfo("8.8.8.8", "1.1.1.1"):
            assert (
                ensure_public_url("http://multi.example.com")
                == "http://multi.example.com"
            )


class TestResolutionFailure:
    def test_dns_failure_rejected(self):
        def raises_gaierror(*args, **kwargs):
            raise socket.gaierror("Name or service not known")

        with patch(
            "elder_berry.core.url_validator.socket.getaddrinfo",
            side_effect=raises_gaierror,
        ):
            with pytest.raises(UnsafeUrlError, match="nicht aufloesbar"):
                ensure_public_url("http://this-host-should-not.exist.invalid")

    def test_empty_addrinfo_rejected(self):
        with patch(
            "elder_berry.core.url_validator.socket.getaddrinfo",
            return_value=[],
        ):
            with pytest.raises(UnsafeUrlError, match="keine IP-Adresse"):
                ensure_public_url("http://no-records.example")
