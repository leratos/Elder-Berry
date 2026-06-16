"""Phase 103 (S4): defensiver Spalten-Allowlist-Guard fuer die f-String-SQL.

Heute kein Injection-Vektor (Spaltennamen stammen nur aus Klassenkonstanten,
Werte sind parametrisiert). Diese Tests sichern, dass der Guard echte
Bezeichner durchlaesst, Unbekanntes ablehnt und die proposal_store-Konstanten
nicht aus der Allowlist driften.
"""

from __future__ import annotations

import pytest

from elder_berry.tools import proposal_store
from elder_berry.tools.contact_store import ContactStore


class TestContactColumnGuard:
    def test_known_columns_pass(self):
        cols = ["user_id", *ContactStore._ALL_FIELDS, "created_at", "updated_at"]
        ContactStore._assert_known_columns(cols)  # kein Raise

    def test_unknown_column_raises(self):
        with pytest.raises(ValueError, match="Unerlaubte SQL-Spaltennamen"):
            ContactStore._assert_known_columns(["name", "evil; DROP TABLE contacts"])

    def test_all_fields_are_allowlisted(self):
        assert set(ContactStore._ALL_FIELDS) <= ContactStore._ALLOWED_COLUMNS


class TestProposalColumnConsistency:
    def test_import_time_assert_passed(self):
        # Laeuft bereits beim Import; expliziter Re-Run darf nicht werfen.
        proposal_store._assert_proposal_columns_allowed()

    def test_both_constants_describe_same_columns(self):
        plain = proposal_store._columns_of(proposal_store._PROPOSAL_COLS)
        prefixed = proposal_store._columns_of(proposal_store._PROPOSAL_COLS_PREFIXED)
        assert plain == prefixed

    def test_all_columns_allowlisted(self):
        for col in proposal_store._columns_of(proposal_store._PROPOSAL_COLS):
            assert col in proposal_store._ALLOWED_PROPOSAL_COLUMNS

    def test_drifted_constant_is_rejected(self, monkeypatch):
        monkeypatch.setattr(
            proposal_store,
            "_PROPOSAL_COLS",
            proposal_store._PROPOSAL_COLS + ", evil_injected",
        )
        with pytest.raises(ValueError, match="Unerlaubte SQL-Spaltennamen"):
            proposal_store._assert_proposal_columns_allowed()
