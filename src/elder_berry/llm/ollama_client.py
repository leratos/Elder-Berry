"""Ollama-Client – lokales LLM auf dem Tower."""
import httpx

from .base import LLMClient

OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_MODEL = "phi4:14b"
TIMEOUT = 120.0


class OllamaClient(LLMClient):
    name = "ollama"

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        base_url: str = OLLAMA_BASE_URL,
        timeout: float = TIMEOUT,
    ):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def is_available(self) -> bool:
        try:
            resp = httpx.get(f"{self.base_url}/api/tags", timeout=3.0)
            return resp.status_code == 200
        except (httpx.ConnectError, httpx.TimeoutException):
            return False

    def generate(self, prompt: str, system: str = "") -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        try:
            resp = httpx.post(
                f"{self.base_url}/api/chat",
                json={"model": self.model, "messages": messages, "stream": False},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json()["message"]["content"]
        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"Ollama HTTP-Fehler: {e.response.status_code}") from e
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            raise RuntimeError(f"Ollama nicht erreichbar: {e}") from e
