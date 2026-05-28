"""Tests for RecipeCommandHandler."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from elder_berry.comms.commands.recipe_commands import (
    RecipeSemanticIndex,
    RecipeCommandHandler,
    RecipeMatch,
    _factory,
)
from elder_berry.comms.commands.base import HandlerContext
from elder_berry.comms.pending_confirmation import PendingAction


@pytest.fixture()
def cookbook():
    return MagicMock()


@pytest.fixture()
def anthropic():
    return MagicMock()


@pytest.fixture()
def index():
    return MagicMock()


@pytest.fixture()
def handler(cookbook, anthropic, index):
    return RecipeCommandHandler(
        cookbook=cookbook,
        anthropic_client=anthropic,
        index=index,
    )


def test_not_configured_when_cookbook_missing(anthropic, index):
    h = RecipeCommandHandler(cookbook=None, anthropic_client=anthropic, index=index)
    result = h.execute("recipe_lookup", "rezept carbonara")
    assert result.success is False
    assert "nicht konfiguriert" in (result.text or "").lower()


def test_semantic_hit_fetches_recipe(handler, cookbook, index):
    cookbook.list_recipes.return_value = []
    index.search.return_value = RecipeMatch(recipe_id="42", score=0.91)
    cookbook.get_recipe.return_value = {
        "name": "Carbonara",
        "recipeCategory": "Pasta",
        "recipeIngredient": ["Spaghetti", "Ei", "Pecorino"],
        "recipeInstructions": ["Kochen", "Vermengen"],
    }

    result = handler.execute("recipe_lookup", "rezept carbonara")

    assert result.success is True
    assert "Carbonara" in (result.text or "")
    cookbook.get_recipe.assert_called_once_with("42")


def test_api_search_used_when_semantic_miss(handler, cookbook, index):
    cookbook.list_recipes.return_value = []
    index.search.return_value = None
    cookbook.search_recipes.return_value = [
        MagicMock(recipe_id="9", name="Moscow Mule", category="Cocktail", keywords=[])
    ]
    cookbook.get_recipe.return_value = {
        "name": "Moscow Mule",
        "recipeCategory": "Cocktail",
        "recipeIngredient": ["Wodka", "Limette"],
        "recipeInstructions": ["Mischen"],
    }

    result = handler.execute("recipe_lookup", "cocktail moscow mule")

    assert result.success is True
    assert "Moscow Mule" in (result.text or "")
    cookbook.search_recipes.assert_called_once()


def test_generate_pending_when_no_hit(handler, cookbook, index, anthropic):
    cookbook.list_recipes.return_value = []
    index.search.return_value = None
    cookbook.search_recipes.return_value = []
    anthropic.generate.return_value = (
        '{"@context":"https://schema.org","@type":"Recipe","name":"Test",'
        '"recipeCategory":"Cocktail","recipeIngredient":["A"],'
        '"recipeInstructions":["B"]}'
    )

    result = handler.execute("recipe_lookup", "wie mache ich test")

    assert result.success is True
    assert result.pending_confirmation is True
    assert result.pending_data is not None
    assert result.pending_data.get("action_type") == "recipe_save"
    assert "Soll ich das" in (result.text or "")


def test_generate_missing_llm_returns_error(cookbook, index):
    h = RecipeCommandHandler(cookbook=cookbook, anthropic_client=None, index=index)
    cookbook.list_recipes.return_value = []
    index.search.return_value = None
    cookbook.search_recipes.return_value = []

    result = h.execute("recipe_lookup", "rezept x")

    assert result.success is False
    assert "fallback" in (result.text or "").lower()


def test_confirm_pending_recipe_success(handler, cookbook, index):
    action = PendingAction(
        action_type="recipe_save",
        description="save",
        data={
            "recipe_json": {
                "@context": "https://schema.org",
                "@type": "Recipe",
                "name": "Saved",
                "recipeCategory": "Snack",
                "recipeIngredient": ["A"],
                "recipeInstructions": ["B"],
            }
        },
    )
    cookbook.save_recipe.return_value = "Recipes/saved.json"

    result = handler.confirm_pending_recipe(action)

    assert result.success is True
    assert "gespeichert" in (result.text or "")
    cookbook.save_recipe.assert_called_once()
    index.upsert.assert_called_once()


def test_confirm_pending_recipe_invalid_payload(handler):
    action = PendingAction(
        action_type="recipe_save",
        description="save",
        data={"recipe_json": "bad"},
    )

    result = handler.confirm_pending_recipe(action)

    assert result.success is False
    assert "Ungueltige" in (result.text or "")


def test_execute_unknown_command_returns_error(handler):
    result = handler.execute("unknown", "rezept x")
    assert result.success is False
    assert "Unbekannter" in (result.text or "")


def test_lookup_empty_query_returns_hint(handler, cookbook):
    cookbook.list_recipes.return_value = []
    result = handler.execute("recipe_lookup", "rezept")
    assert result.success is False
    assert "Bitte ein Rezept" in (result.text or "")


def test_lookup_search_error_returns_user_friendly_error(handler, cookbook, index):
    cookbook.list_recipes.return_value = []
    index.search.return_value = None
    cookbook.search_recipes.side_effect = RuntimeError("boom")

    result = handler.execute("recipe_lookup", "rezept suppe")

    assert result.success is False
    assert "Cookbook-Suche" in (result.text or "")


def test_lookup_semantic_hit_fetch_fail_falls_back_to_api(handler, cookbook, index):
    cookbook.list_recipes.return_value = []
    index.search.return_value = RecipeMatch(recipe_id="42", score=0.91)
    cookbook.get_recipe.side_effect = [RuntimeError("kaputt"), {"name": "API"}]
    cookbook.search_recipes.return_value = [
        MagicMock(recipe_id="9", name="API", category="", keywords=[])
    ]

    result = handler.execute("recipe_lookup", "rezept x")

    assert result.success is True
    assert "Rezept: API" in (result.text or "")
    assert cookbook.get_recipe.call_count == 2


def test_generate_recipe_json_handles_llm_exception(handler, anthropic):
    anthropic.generate.side_effect = RuntimeError("api down")
    assert handler._generate_recipe_json("x") is None


def test_generate_recipe_json_handles_missing_json(handler, anthropic):
    anthropic.generate.return_value = "kein json"
    assert handler._generate_recipe_json("x") is None


def test_generate_recipe_json_handles_invalid_json(handler, anthropic):
    anthropic.generate.return_value = "{invalid"
    assert handler._generate_recipe_json("x") is None


def test_generate_recipe_json_handles_non_dict_json(handler, anthropic):
    anthropic.generate.return_value = "[1,2,3]"
    assert handler._generate_recipe_json("x") is None


def test_generate_recipe_json_sets_context_and_type(handler, anthropic):
    anthropic.generate.return_value = '{"name":"X"}'
    data = handler._generate_recipe_json("x")
    assert data is not None
    assert data["@context"] == "https://schema.org"
    assert data["@type"] == "Recipe"


def test_generate_recipe_json_normalizes_extended_fields(handler, anthropic):
    anthropic.generate.return_value = (
        '{"name":"X","recipeYield":4,'
        '"prepTime":"PT15M","cookTime":"15 Minuten",'
        '"totalTime":"PT30M","image":"https://example.com/x.jpg",'
        '"nutrition":{"calories":"500 kcal","proteinContent":"20 g"},'
        '"tool":["Dutch Oven","Stabmixer","Dutch Oven"]}'
    )
    data = handler._generate_recipe_json("x")
    assert data is not None
    assert data["recipeYield"] == "4 Portionen"
    assert data["prepTime"] == "PT15M"
    assert data["totalTime"] == "PT30M"
    assert "cookTime" not in data
    assert data["image"] == "https://example.com/x.jpg"
    assert data["nutrition"]["calories"] == "500 kcal"
    assert data["tool"] == ["Dutch Oven", "Stabmixer"]


def test_extract_query_variants(handler):
    assert handler._extract_query("rezept carbonara") == "carbonara"
    assert handler._extract_query("wie mache ich ramen") == "ramen"
    assert (
        handler._extract_query("gib mir ein Rezept fuer ein vegetarisches Gulasch")
        == "vegetarisches Gulasch"
    )
    assert (
        handler._extract_query("ich moechte ein rezept fuer linsensuppe bitte")
        == "linsensuppe"
    )
    assert handler._extract_query("hallo") == ""


def test_extract_json_object_variants(handler):
    assert handler._extract_json_object('{"a":1}') == '{"a":1}'
    assert handler._extract_json_object('xxx {"a":1} yyy') == '{"a":1}'
    assert handler._extract_json_object("nein") is None


def test_summary_from_recipe_json_uses_fallback_and_non_list_ingredients(handler):
    summary = handler._summary_from_recipe_json(
        {"title": "T", "category": "C", "recipeIngredient": "x"},
        fallback_id="fallback",
    )
    assert summary.recipe_id == "fallback"
    assert summary.name == "T"
    assert summary.category == "C"
    assert summary.keywords == []
    assert summary.tools == []


def test_summary_from_recipe_json_reads_tools(handler):
    summary = handler._summary_from_recipe_json(
        {
            "name": "T",
            "recipeCategory": "C",
            "recipeIngredient": ["1 g Salz"],
            "tool": ["Stabmixer", "Topf"],
        },
        fallback_id="fallback",
    )
    assert summary.tools == ["Stabmixer", "Topf"]


def test_render_recipe_formats_dict_instructions_and_score(handler):
    txt = handler._render_recipe(
        {
            "name": "Suppe",
            "recipeCategory": "Lunch",
            "recipeIngredient": ["A", "B"],
            "recipeInstructions": [{"text": "Schritt 1"}, "Schritt 2"],
        },
        score=0.875,
    )
    assert "Rezept: Suppe" in txt
    assert "Kategorie: Lunch" in txt
    assert "Treffer-Score: 0.88" in txt
    assert "1. Schritt 1" in txt


def test_render_recipe_includes_extended_fields(handler):
    txt = handler._render_recipe(
        {
            "name": "Dal",
            "recipeCategory": "Hauptgericht",
            "recipeYield": "4 Portionen",
            "prepTime": "PT20M",
            "cookTime": "PT30M",
            "totalTime": "PT50M",
            "image": "https://example.com/dal.jpg",
            "nutrition": {
                "calories": "520 kcal",
                "proteinContent": "18 g",
                "fatContent": "12 g",
                "carbohydrateContent": "70 g",
            },
            "tool": ["Topf", "Pürierstab"],
            "recipeIngredient": ["200 g Linsen"],
            "recipeInstructions": ["Kochen"],
        },
        score=None,
    )
    assert "Portionen: 4 Portionen" in txt
    assert "Vorbereitung: PT20M" in txt
    assert "Kochzeit: PT30M" in txt
    assert "Gesamtzeit: PT50M" in txt
    assert "Kalorien: 520 kcal" in txt
    assert "Bild: https://example.com/dal.jpg" in txt
    assert "Utensilien:" in txt
    assert "- Topf" in txt


def test_semantic_index_doc_text_and_upsert_flow(monkeypatch):
    idx = RecipeSemanticIndex()
    fake_col = MagicMock()
    idx._collection = fake_col
    idx._embedder = MagicMock()
    idx._embedder.embed.return_value = [0.1, 0.2]

    summary = MagicMock()
    summary.recipe_id = "1"
    summary.name = "Name"
    summary.category = "Cat"
    summary.keywords = ["A", "B"]

    assert "Name" in idx._doc_text(summary)
    idx.upsert(summary)
    fake_col.upsert.assert_called_once()


def test_semantic_index_upsert_skips_without_doc():
    idx = RecipeSemanticIndex()
    idx._collection = MagicMock()
    summary = MagicMock()
    summary.recipe_id = "1"
    summary.name = ""
    summary.category = ""
    summary.keywords = []

    idx.upsert(summary)
    idx._collection.upsert.assert_not_called()


def test_semantic_index_hydrate_once_only_first_run():
    idx = RecipeSemanticIndex()
    idx.upsert = MagicMock()
    idx.hydrate_once([MagicMock(), MagicMock()])
    idx.hydrate_once([MagicMock()])
    assert idx.upsert.call_count == 2


def test_semantic_index_search_branches():
    idx = RecipeSemanticIndex()
    idx._embedder = MagicMock()
    idx._embedder.embed.return_value = [0.1]

    # no collection
    idx._collection = None
    idx._disabled = True
    assert idx.search("x") is None

    # blank query
    idx._disabled = False
    idx._collection = MagicMock()
    assert idx.search(" ") is None

    # query exception
    idx._collection.query.side_effect = RuntimeError("boom")
    assert idx.search("x") is None

    # no ids
    idx._collection.query.side_effect = None
    idx._collection.query.return_value = {"ids": [[]], "distances": [[]]}
    assert idx.search("x") is None

    # below threshold
    idx._collection.query.return_value = {"ids": [["42"]], "distances": [[0.5]]}
    assert idx.search("x", threshold=0.8) is None

    # hit
    idx._collection.query.return_value = {"ids": [["42"]], "distances": [[0.1]]}
    hit = idx.search("x", threshold=0.8)
    assert hit is not None
    assert hit.recipe_id == "42"


def test_factory_returns_none_without_secret_store():
    ctx = HandlerContext(secret_store=None)
    assert _factory(ctx) is None


def test_factory_builds_handler_with_secret_store():
    store = MagicMock()
    store.get_or_none.side_effect = lambda _k: "x"
    ctx = HandlerContext(secret_store=store, anthropic_client=MagicMock())
    h = _factory(ctx)
    assert h is not None
