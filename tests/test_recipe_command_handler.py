"""Tests for RecipeCommandHandler."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from elder_berry.comms.commands.recipe_commands import (
    RecipeCommandHandler,
    RecipeMatch,
)
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
