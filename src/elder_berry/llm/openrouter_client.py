"""OpenRouter-Client – Cloud-Fallback wenn Ollama nicht verfügbar."""

import os

import httpx
from dotenv import load_dotenv

from .base import LLMClient

load_dotenv()  # .env lokal; Codespaces-Secret überschreibt nicht bereits gesetzte Vars

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "meta-llama/llama-3.1-70b-instruct"
TIMEOUT = 60.0


class OpenRouterClient(LLMClient):
    name = "openrouter"

    def __init__(self, model: str = DEFAULT_MODEL):
        self.model = model
        self._api_key: str | None = os.environ.get("OPENROUTER_API_KEY")

    def is_available(self) -> bool:
        return bool(self._api_key)

    def generate(self, prompt: str, system: str = "") -> str:
        if not self._api_key:
            raise RuntimeError("OPENROUTER_API_KEY nicht gesetzt.")

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        try:
            resp = httpx.post(
                OPENROUTER_URL,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={"model": self.model, "messages": messages},
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as e:
            raise RuntimeError(
                f"OpenRouter HTTP-Fehler: {e.response.status_code} – {e.response.text}"
            ) from e
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            raise RuntimeError(f"OpenRouter nicht erreichbar: {e}") from e
