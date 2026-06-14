"""Phase 98 (PR #308 A): Anthropic-gestützte Command-Pfade sind im
Privacy-Modus hart gesperrt (refuse statt stiller Cloud-Call).

Deckt camera (Bildbeschreibung), mail (Antwort-Entwurf), recipe
(LLM-Generierung) und die Intent-Parser von route/nearby ab.
"""

from unittest.mock import MagicMock, patch

from elder_berry.comms.commands.camera_commands import CameraCommandHandler
from elder_berry.comms.commands.mail_commands import MailCommandHandler
from elder_berry.comms.commands.multi_stop_route_commands import (
    MultiStopRouteCommandHandler,
)
from elder_berry.comms.commands.nearby_place_commands import NearbyPlaceCommandHandler
from elder_berry.comms.commands.recipe_commands import RecipeCommandHandler
from elder_berry.core.privacy_state import PrivacyState
from elder_berry.tools.maps_link_builder import MapsLinkBuilder

ON = PrivacyState(enabled=True)


class TestCameraDescribePrivacy:
    def test_describe_refuses_and_skips_anthropic(self):
        anthropic = MagicMock()
        handler = CameraCommandHandler(
            anthropic_client=anthropic, privacy_state=ON
        )
        with patch.object(
            handler, "_capture_image", return_value=(b"jpeg-bytes", None)
        ):
            result = handler.execute("camera_describe", "was siehst du")

        # Foto kommt (lokal), aber keine Cloud-Vision.
        assert result.image_path is not None
        assert "Privacy-Modus" in (result.text or "")
        anthropic.describe_image.assert_not_called()


class TestMailReplyPrivacy:
    def test_reply_refuses_and_skips_anthropic(self):
        anthropic = MagicMock()
        handler = MailCommandHandler(
            email_client=MagicMock(),
            anthropic_client=anthropic,
            privacy_state=ON,
        )
        result = handler._cmd_mail_reply("#1 zusagen")
        assert result.success is False
        assert "Privacy-Modus" in (result.text or "")
        anthropic.generate.assert_not_called()

    def test_reply_modify_refuses(self):
        anthropic = MagicMock()
        handler = MailCommandHandler(
            email_client=MagicMock(),
            anthropic_client=anthropic,
            privacy_state=ON,
        )
        result = handler._cmd_mail_reply_modify("#1 freundlicher")
        assert result.success is False
        assert "Privacy-Modus" in (result.text or "")
        anthropic.generate.assert_not_called()


class TestRecipePrivacy:
    def test_generation_refuses_and_skips_anthropic(self):
        cookbook = MagicMock()
        cookbook.list_recipes.return_value = []
        cookbook.search_recipes.return_value = []
        index = MagicMock()
        index.search.return_value = None
        anthropic = MagicMock()

        handler = RecipeCommandHandler(
            cookbook=cookbook,
            anthropic_client=anthropic,
            index=index,
            privacy_state=ON,
        )
        result = handler.execute("recipe_lookup", "rezept carbonara")

        assert result.success is False
        assert "Privacy-Modus" in (result.text or "")
        anthropic.generate.assert_not_called()


class TestRoutePrivacy:
    def test_intent_parse_refuses_and_skips_parser(self):
        parser = MagicMock()
        handler = MultiStopRouteCommandHandler(
            intent_parser=parser,
            route_planner=MagicMock(),
            contact_store=MagicMock(),
            session_store=MagicMock(),
            link_builder=MapsLinkBuilder(),
            privacy_state=ON,
        )
        result = handler.execute(
            "multi_stop_route", "Fahrt zu Lisa, vorher Andrea abholen"
        )
        assert result.success is False
        assert "Privacy-Modus" in (result.text or "")
        parser.parse.assert_not_called()


class TestNearbyPrivacy:
    def test_intent_parse_refuses_and_skips_parser(self):
        parser = MagicMock()
        handler = NearbyPlaceCommandHandler(
            intent_parser=parser,
            place_search=MagicMock(),
            draft_store=MagicMock(),
            privacy_state=ON,
        )
        result = handler.execute(
            "nearby_place", "kannst du mir eine Rockerbar nennen?"
        )
        assert result.success is False
        assert "Privacy-Modus" in (result.text or "")
        parser.parse.assert_not_called()
