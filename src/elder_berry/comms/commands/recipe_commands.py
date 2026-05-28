"""RecipeCommandHandler -- Nextcloud Cookbook lookup + generation flow.

Routing goal for Phase 93:
1) Semantic cache search in Chroma collection "recipes".
2) Hit -> fetch recipe from Cookbook and render.
3) Miss -> generate schema.org/Recipe JSON via LLM and ask for confirmation.
4) Confirmation executes WebDAV upload + Cookbook reindex + cache update.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from elder_berry.comms.commands.base import (
    CommandHandler,
    CommandPlugin,
    CommandResult,
    HandlerContext,
    user_friendly_error,
)
from elder_berry.memory.embedding import OllamaEmbeddingClient
from elder_berry.tools.nextcloud_cookbook_client import (
    CookbookRecipeSummary,
    NextcloudCookbookClient,
)

if TYPE_CHECKING:
    from elder_berry.comms.pending_confirmation import PendingAction
    from elder_berry.llm.anthropic_client import AnthropicClient

logger = logging.getLogger(__name__)

_QUERY_STOP_WORDS = {
    "bitte",
    "cocktail",
    "das",
    "dem",
    "den",
    "der",
    "die",
    "ein",
    "eine",
    "einem",
    "einen",
    "einer",
    "fuer",
    "für",
    "gib",
    "ich",
    "kochbuch",
    "mache",
    "mir",
    "mit",
    "rezept",
    "und",
    "von",
    "wie",
    "zu",
}

RECIPE_PATTERN = re.compile(
    r"^(?:rezept|kochbuch|cocktail)\s*(?::|-)??\s*(.*)$",
    re.IGNORECASE,
)
HOW_TO_PATTERN = re.compile(r"^wie\s+mache\s+ich\s+(.+)$", re.IGNORECASE)

RECIPE_SYSTEM_PROMPT = """Du bist eine Koch-Assistentin.
Erzeuge NUR gueltiges JSON im schema.org Recipe-Format.
Verwende in deutschen Texten die korrekte Rechtschreibung mit Umlauten (nicht ae/oe/ue, sondern ä/ö/ü, wo sprachlich korrekt).
Keine Markdown-Fences, kein Fliesstext, keine Erklaerung.
Pflichtfelder:
- @context = https://schema.org
- @type = Recipe
- name (string)
- recipeCategory (string)
- recipeIngredient (array of strings, Format pro Eintrag: "Menge Einheit Zutat",
    z.B. "200 g Karotten", "1 Prise Salz", "2 EL Olivenöl", "3 Stück Eier".
  Regeln:
  * Immer "Zahl Einheit Zutat" — niemals "Zutat nach Geschmack" oder
    "Zutat zum Garnieren". Stattdessen konkrete Mengen verwenden,
    z.B. "1 Prise Salz" statt "Salz nach Geschmack".
    * Beilagen und Garnier-Hinweise (z.B. "Reis zum Servieren",
        "Koriander zum Garnieren") gehören NICHT in recipeIngredient,
    sondern als letzten Schritt in recipeInstructions.
  * Kein Komma, kein Bindestrich, keine Klammern im Eintrag.)
- recipeYield (string, Anzahl Portionen, z.B. "4 Portionen")
- recipeInstructions (array of strings)
Optionale Felder:
- tool (array of strings, nur besondere Utensilien, z.B. "Dutch Oven",
    "Stabmixer", "Auflaufform"; maximal 8 Einträge)
- description (string)
- prepTime (ISO8601 duration, z.B. PT20M)
- cookTime (ISO8601 duration, z.B. PT35M)
- totalTime (ISO8601 duration, z.B. PT55M)
- nutrition (object), mit bevorzugten Feldern:
    * calories (z.B. "520 kcal")
    * proteinContent (z.B. "32 g")
    * fatContent (z.B. "22 g")
    * carbohydrateContent (z.B. "38 g")
- image (string URL, absolut, z.B. https://.../bild.jpg)
"""


@dataclass(frozen=True)
class RecipeMatch:
    recipe_id: str
    score: float


class RecipeSemanticIndex:
    """Small semantic index for Cookbook recipes backed by ChromaDB.

    Optional dependency: when chromadb is unavailable, search becomes a no-op.
    """

    COLLECTION_NAME = "recipes"

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or (Path.home() / ".elder-berry" / "memory")
        self._hydrated = False
        self._disabled = False
        self._collection: Any | None = None
        self._embedder = OllamaEmbeddingClient()

    def _get_collection(self) -> Any | None:
        if self._disabled:
            return None
        if self._collection is not None:
            return self._collection
        try:
            import chromadb
        except ImportError:
            self._disabled = True
            logger.info("chromadb not installed, recipe semantic index disabled")
            return None

        self._db_path.mkdir(parents=True, exist_ok=True)
        client = chromadb.PersistentClient(path=str(self._db_path))
        self._collection = client.get_or_create_collection(name=self.COLLECTION_NAME)
        return self._collection

    @staticmethod
    def _doc_text(summary: CookbookRecipeSummary) -> str:
        parts = [summary.name, summary.category]
        if summary.keywords:
            parts.append(", ".join(summary.keywords))
        return "\n".join([p for p in parts if p]).strip()

    def upsert(self, summary: CookbookRecipeSummary) -> None:
        col = self._get_collection()
        if col is None:
            return

        doc = self._doc_text(summary)
        if not doc:
            return

        vec = self._embedder.embed(doc)
        col.upsert(
            ids=[summary.recipe_id],
            documents=[doc],
            embeddings=[vec],
            metadatas=[{"recipe_id": summary.recipe_id}],
        )

    def hydrate_once(self, recipes: list[CookbookRecipeSummary]) -> None:
        if self._hydrated:
            return
        for recipe in recipes:
            try:
                self.upsert(recipe)
            except Exception as exc:
                logger.debug("recipe index upsert skipped: %s", exc)
        self._hydrated = True

    def search(self, query: str, threshold: float = 0.82) -> RecipeMatch | None:
        col = self._get_collection()
        if col is None:
            return None
        if not query.strip():
            return None

        try:
            vec = self._embedder.embed(query)
            result = col.query(
                query_embeddings=[vec],
                n_results=1,
                include=["metadatas", "distances"],
            )
        except Exception as exc:
            logger.debug("recipe index query failed: %s", exc)
            return None

        ids = result.get("ids", [[]])
        distances = result.get("distances", [[]])
        if not ids or not ids[0]:
            return None

        recipe_id = str(ids[0][0])
        distance = float(distances[0][0]) if distances and distances[0] else 1.0
        score = max(0.0, 1.0 - distance)
        if score < threshold:
            return None
        return RecipeMatch(recipe_id=recipe_id, score=score)


class RecipeCommandHandler(CommandHandler):
    """Commands for Cookbook lookup and guided recipe creation."""

    def __init__(
        self,
        cookbook: NextcloudCookbookClient | None,
        anthropic_client: AnthropicClient | None,
        index: RecipeSemanticIndex | None = None,
    ) -> None:
        self._cookbook = cookbook
        self._anthropic = anthropic_client
        self._index = index or RecipeSemanticIndex()

    @property
    def patterns(self) -> list[tuple[re.Pattern[str], str, bool, bool]]:
        return [
            (RECIPE_PATTERN, "recipe_lookup", False, False),
            (HOW_TO_PATTERN, "recipe_lookup", False, False),
        ]

    @property
    def command_descriptions(self) -> list[str]:
        return [
            "rezept <name>: Rezept aus Nextcloud Cookbook suchen",
            "kochbuch <name>: Alias fuer Rezeptsuche",
            "cocktail <name>: Cocktail als Rezept suchen",
            "wie mache ich <gericht>: Rezept suchen oder Entwurf erzeugen",
        ]

    @property
    def keywords(self) -> dict[str, list[str]]:
        return {
            "recipe_lookup": [
                "rezept",
                "kochbuch",
                "cocktail",
                "wie mache ich",
            ]
        }

    def execute(self, command: str, raw_text: str) -> CommandResult:
        if command == "recipe_lookup":
            return self._cmd_lookup(raw_text)
        return CommandResult(
            command=command,
            success=False,
            text=f"Unbekannter Rezept-Command: {command}",
        )

    def confirm_pending_recipe(self, action: PendingAction) -> CommandResult:
        if self._cookbook is None:
            return self.not_configured("recipe_lookup", "Nextcloud", setup_step=4)

        recipe_json = action.data.get("recipe_json")
        if not isinstance(recipe_json, dict):
            return CommandResult(
                command="recipe_lookup",
                success=False,
                text="Ungueltige Rezeptdaten in der Bestaetigung.",
            )

        try:
            path = self._cookbook.save_recipe(recipe_json)
        except Exception as exc:
            return CommandResult(
                command="recipe_lookup",
                success=False,
                text=user_friendly_error(exc, "Cookbook-Speichern"),
            )

        summary = self._summary_from_recipe_json(recipe_json, fallback_id=path)
        try:
            self._index.upsert(summary)
        except Exception as exc:
            logger.debug("recipe index update skipped: %s", exc)

        title = summary.name or "Rezept"
        return CommandResult(
            command="recipe_lookup",
            success=True,
            text=(
                f"OK, gespeichert: {title}\n"
                f"Pfad: {path}\n"
                "Cookbook-Reindex wurde angestossen."
            ),
        )

    def _cmd_lookup(self, raw_text: str) -> CommandResult:
        if self._cookbook is None:
            return self.not_configured("recipe_lookup", "Nextcloud", setup_step=4)

        query = self._extract_query(raw_text)
        if not query:
            return CommandResult(
                command="recipe_lookup",
                success=False,
                text="Bitte ein Rezept nennen, z.B. 'rezept carbonara'.",
            )

        try:
            recipes = self._cookbook.list_recipes(limit=400)
            self._index.hydrate_once(recipes)
        except Exception as exc:
            logger.debug("recipe index hydration skipped: %s", exc)

        try:
            api_hits = self._cookbook.search_recipes(query, limit=1)
        except Exception as exc:
            logger.error("cookbook search failed: %s", exc)
            return CommandResult(
                command="recipe_lookup",
                success=False,
                text=user_friendly_error(exc, "Cookbook-Suche"),
            )

        if isinstance(api_hits, list) and api_hits:
            top = api_hits[0]
            try:
                self._index.upsert(top)
            except Exception as exc:
                logger.debug("recipe index update skipped: %s", exc)
            try:
                recipe = self._cookbook.get_recipe(top.recipe_id)
                return CommandResult(
                    command="recipe_lookup",
                    success=True,
                    text=self._render_recipe(recipe, score=None),
                )
            except Exception as exc:
                return CommandResult(
                    command="recipe_lookup",
                    success=False,
                    text=user_friendly_error(exc, "Cookbook-Rezept"),
                )

        try:
            match = self._index.search(query)
        except Exception as exc:
            logger.debug("recipe semantic search failed: %s", exc)
            match = None

        if match is not None:
            try:
                recipe = self._cookbook.get_recipe(match.recipe_id)
                if not self._is_semantic_match_plausible(recipe, query):
                    logger.info(
                        "semantic hit rejected as implausible (query=%r, recipe=%r)",
                        query,
                        recipe.get("name"),
                    )
                    raise LookupError("semantic false positive")
                return CommandResult(
                    command="recipe_lookup",
                    success=True,
                    text=self._render_recipe(recipe, score=match.score),
                )
            except LookupError:
                pass
            except Exception as exc:
                logger.warning("semantic hit could not be loaded: %s", exc)

        generated = self._generate_recipe_json(query)
        if generated is None:
            return CommandResult(
                command="recipe_lookup",
                success=False,
                text=(
                    "Kein Rezept in Cookbook gefunden und kein LLM-Fallback moeglich. "
                    "Pruefe ANTHROPIC_API_KEY oder lege das Rezept manuell im Cookbook an."
                ),
            )

        preview = self._render_recipe(generated, score=None)
        return CommandResult(
            command="recipe_lookup",
            success=True,
            text=(
                "Kein passendes Rezept gefunden. Ich habe einen Entwurf erstellt:\n\n"
                f"{preview}\n\n"
                "Soll ich das in Nextcloud Cookbook speichern? (ja/nein)"
            ),
            pending_confirmation=True,
            pending_data={
                "action_type": "recipe_save",
                "recipe_json": generated,
                "query": query,
            },
        )

    @staticmethod
    def _tokenize_for_match(text: str) -> set[str]:
        tokens = re.findall(r"[A-Za-zÄÖÜäöüß]{3,}", text, flags=re.UNICODE)
        return {tok.casefold() for tok in tokens}

    @staticmethod
    def _is_semantic_match_plausible(recipe: dict[str, Any], query: str) -> bool:
        query_tokens = RecipeCommandHandler._tokenize_for_match(query)
        query_tokens = {tok for tok in query_tokens if tok not in _QUERY_STOP_WORDS}
        if not query_tokens:
            return True

        parts: list[str] = [
            str(recipe.get("name") or ""),
            str(recipe.get("title") or ""),
            str(recipe.get("recipeCategory") or recipe.get("category") or ""),
        ]

        ingredients = recipe.get("recipeIngredient")
        if isinstance(ingredients, list):
            parts.extend(str(item) for item in ingredients)

        tools = recipe.get("tool")
        if isinstance(tools, list):
            parts.extend(str(item) for item in tools)

        candidate_tokens = RecipeCommandHandler._tokenize_for_match(" ".join(parts))
        return bool(query_tokens & candidate_tokens)

    @staticmethod
    def _normalize_recipe_yield(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            amount = int(value) if float(value).is_integer() else value
            return f"{amount} Portionen"

        text = str(value).strip()
        if not text:
            return None
        if re.search(r"portion", text, re.IGNORECASE):
            return text
        if re.fullmatch(r"\d+(?:[.,]\d+)?", text):
            return f"{text} Portionen"
        return text

    @staticmethod
    def _normalize_image(value: Any) -> str | None:
        if isinstance(value, str):
            candidate = value.strip()
            if candidate.startswith("http://") or candidate.startswith("https://"):
                return candidate
            return None
        if isinstance(value, list):
            for item in value:
                normalized = RecipeCommandHandler._normalize_image(item)
                if normalized:
                    return normalized
        return None

    @staticmethod
    def _normalize_duration(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        if re.fullmatch(r"P(?:\d+D)?(?:T(?:\d+H)?(?:\d+M)?(?:\d+S)?)?", text):
            return text
        return None

    @staticmethod
    def _normalize_nutrition(value: Any) -> dict[str, str] | None:
        if not isinstance(value, dict):
            return None
        keys = ("calories", "proteinContent", "fatContent", "carbohydrateContent")
        out: dict[str, str] = {}
        for key in keys:
            raw = value.get(key)
            if raw is None:
                continue
            text = str(raw).strip()
            if text:
                out[key] = text
        return out or None

    @staticmethod
    def _normalize_tools(value: Any) -> list[str] | None:
        items: list[str] = []

        if isinstance(value, str):
            candidate = value.strip()
            if candidate:
                items = [candidate]
        elif isinstance(value, list):
            for raw in value:
                candidate = str(raw).strip()
                if candidate:
                    items.append(candidate)

        if not items:
            return None

        # Deduplicate while preserving order, keep list short for readability.
        seen: set[str] = set()
        normalized: list[str] = []
        for item in items:
            key = item.casefold()
            if key in seen:
                continue
            seen.add(key)
            normalized.append(item)
            if len(normalized) >= 8:
                break

        return normalized or None

    @staticmethod
    def _normalize_generated_recipe(data: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(data)

        yield_text = RecipeCommandHandler._normalize_recipe_yield(
            normalized.get("recipeYield")
        )
        if yield_text:
            normalized["recipeYield"] = yield_text

        for key in ("prepTime", "cookTime", "totalTime"):
            duration = RecipeCommandHandler._normalize_duration(normalized.get(key))
            if duration:
                normalized[key] = duration
            elif key in normalized:
                normalized.pop(key, None)

        image_url = RecipeCommandHandler._normalize_image(normalized.get("image"))
        if image_url:
            normalized["image"] = image_url
        elif "image" in normalized:
            normalized.pop("image", None)

        nutrition = RecipeCommandHandler._normalize_nutrition(
            normalized.get("nutrition")
        )
        if nutrition:
            normalized["nutrition"] = nutrition
        elif "nutrition" in normalized:
            normalized.pop("nutrition", None)

        tools = RecipeCommandHandler._normalize_tools(normalized.get("tool"))
        if tools:
            normalized["tool"] = tools
        elif "tool" in normalized:
            normalized.pop("tool", None)

        return normalized

    @staticmethod
    def _clean_extracted_query(value: str) -> str:
        text = value.strip(" \t\n\r:,-")
        if not text:
            return ""

        # Strip connector words and leading determiners commonly used in NL requests.
        text = re.sub(r"^(?:rezept|kochbuch|cocktail)\b\s*", "", text, flags=re.I)
        text = re.sub(r"^(?:fuer|für|zu|von)\s+", "", text, flags=re.I)
        text = re.sub(r"^(?:ein|eine|einen|einem|einer)\s+", "", text, flags=re.I)
        text = re.sub(r"\s+(?:bitte|danke)\b[.!?]*$", "", text, flags=re.I)
        return text.strip(" .!?")

    @staticmethod
    def _extract_query(raw_text: str) -> str:
        text = raw_text.strip()
        m = RECIPE_PATTERN.match(text)
        if m:
            return RecipeCommandHandler._clean_extracted_query(m.group(1) or "")
        m = HOW_TO_PATTERN.match(text)
        if m:
            return RecipeCommandHandler._clean_extracted_query(m.group(1) or "")

        # Natural language fallback, e.g.:
        # "gib mir ein Rezept fuer vegetarisches Gulasch"
        keyword = re.search(r"\b(?:rezept|kochbuch|cocktail)\b", text, re.I)
        if keyword:
            suffix = text[keyword.end() :]
            cleaned = RecipeCommandHandler._clean_extracted_query(suffix)
            if cleaned:
                return cleaned

            by_preposition = re.search(r"\b(?:fuer|für|zu|von)\s+(.+)$", text, re.I)
            if by_preposition:
                cleaned = RecipeCommandHandler._clean_extracted_query(
                    by_preposition.group(1)
                )
                if cleaned:
                    return cleaned

        return ""

    @staticmethod
    def _extract_json_object(text: str) -> str | None:
        stripped = text.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            return stripped
        block_match = re.search(r"\{[\s\S]*\}", stripped)
        if block_match:
            return block_match.group(0)
        return None

    def _generate_recipe_json(self, query: str) -> dict[str, Any] | None:
        if self._anthropic is None:
            return None

        prompt = f"Erstelle ein Rezept fuer: {query}\nAntwort nur als JSON."
        try:
            raw = self._anthropic.generate(prompt=prompt, system=RECIPE_SYSTEM_PROMPT)
        except Exception as exc:
            logger.error("recipe generation failed: %s", exc)
            return None

        json_text = self._extract_json_object(raw)
        if not json_text:
            logger.warning("recipe generation returned no JSON object")
            return None

        try:
            data = json.loads(json_text)
        except json.JSONDecodeError:
            logger.warning("recipe generation returned invalid JSON")
            return None

        if not isinstance(data, dict):
            return None
        if data.get("@type") != "Recipe":
            data["@type"] = "Recipe"
        if "@context" not in data:
            data["@context"] = "https://schema.org"
        return self._normalize_generated_recipe(data)

    @staticmethod
    def _summary_from_recipe_json(
        recipe: dict[str, Any],
        fallback_id: str,
    ) -> CookbookRecipeSummary:
        recipe_id = str(recipe.get("recipe_id") or recipe.get("id") or fallback_id)
        name = str(recipe.get("name") or recipe.get("title") or "")
        category = str(recipe.get("recipeCategory") or recipe.get("category") or "")

        ingredients_raw = recipe.get("recipeIngredient") or []
        keywords = (
            [str(x) for x in ingredients_raw]
            if isinstance(ingredients_raw, list)
            else []
        )

        tools_raw = recipe.get("tool") or []
        tools = (
            [str(x) for x in tools_raw if str(x).strip()]
            if isinstance(tools_raw, list)
            else []
        )

        return CookbookRecipeSummary(
            recipe_id=recipe_id,
            name=name,
            category=category,
            keywords=keywords,
            tools=tools,
        )

    @staticmethod
    def _render_recipe(recipe: dict[str, Any], score: float | None) -> str:
        name = str(recipe.get("name") or recipe.get("title") or "Rezept")
        category = str(recipe.get("recipeCategory") or recipe.get("category") or "")
        recipe_yield = str(recipe.get("recipeYield") or "").strip()
        prep_time = str(recipe.get("prepTime") or "").strip()
        cook_time = str(recipe.get("cookTime") or "").strip()
        total_time = str(recipe.get("totalTime") or "").strip()
        image = str(recipe.get("image") or "").strip()
        nutrition_raw = recipe.get("nutrition")
        nutrition: dict[str, str] = (
            nutrition_raw if isinstance(nutrition_raw, dict) else {}
        )

        ingredients_raw = recipe.get("recipeIngredient") or []
        if isinstance(ingredients_raw, list):
            ingredients = [str(x) for x in ingredients_raw[:8]]
        else:
            ingredients = []

        tools_raw = recipe.get("tool") or []
        tools = (
            [str(x).strip() for x in tools_raw if str(x).strip()]
            if isinstance(tools_raw, list)
            else []
        )

        instructions_raw = recipe.get("recipeInstructions") or []
        instructions: list[str] = []
        if isinstance(instructions_raw, list):
            for step in instructions_raw[:5]:
                if isinstance(step, dict):
                    text = str(step.get("text") or "").strip()
                else:
                    text = str(step).strip()
                if text:
                    instructions.append(text)

        lines = [f"Rezept: {name}"]
        if category:
            lines.append(f"Kategorie: {category}")
        if recipe_yield:
            lines.append(f"Portionen: {recipe_yield}")
        if prep_time:
            lines.append(f"Vorbereitung: {prep_time}")
        if cook_time:
            lines.append(f"Kochzeit: {cook_time}")
        if total_time:
            lines.append(f"Gesamtzeit: {total_time}")
        if score is not None:
            lines.append(f"Treffer-Score: {score:.2f}")

        if nutrition:
            lines.append("Naehrwerte:")
            if nutrition.get("calories"):
                lines.append(f"- Kalorien: {nutrition['calories']}")
            if nutrition.get("proteinContent"):
                lines.append(f"- Protein: {nutrition['proteinContent']}")
            if nutrition.get("fatContent"):
                lines.append(f"- Fett: {nutrition['fatContent']}")
            if nutrition.get("carbohydrateContent"):
                lines.append(f"- Kohlenhydrate: {nutrition['carbohydrateContent']}")

        if image:
            lines.append(f"Bild: {image}")

        if tools:
            lines.append("Utensilien:")
            for item in tools[:8]:
                lines.append(f"- {item}")

        if ingredients:
            lines.append("Zutaten:")
            for item in ingredients:
                lines.append(f"- {item}")

        if instructions:
            lines.append("Zubereitung:")
            for idx, step in enumerate(instructions, start=1):
                lines.append(f"{idx}. {step}")

        return "\n".join(lines)


HELP_SECTION_RECIPE = """Rezepte (Nextcloud Cookbook):
  rezept <name>           -- Rezept suchen
  kochbuch <name>         -- Alias fuer Rezeptsuche
  cocktail <name>         -- Cocktail als Rezept suchen
  wie mache ich <gericht> -- Rezept suchen oder Entwurf erzeugen"""


def _factory(ctx: HandlerContext) -> CommandHandler | None:
    if ctx.secret_store is None:
        return None
    cookbook = NextcloudCookbookClient(secret_store=ctx.secret_store)
    return RecipeCommandHandler(
        cookbook=cookbook,
        anthropic_client=ctx.anthropic_client,
    )


PLUGIN = CommandPlugin(
    name="recipe",
    priority=71,
    category="cloud",
    help_section=HELP_SECTION_RECIPE,
    factory=_factory,
)
