"""Provider-agnostic LLM client.

Swapping providers (Gemini, OpenAI, Ollama, ...) is a config change only —
set LLM_PROVIDER / LLM_API_KEY / LLM_MODEL / LLM_BASE_URL in the environment.
No provider SDKs are used, only plain HTTP, so callers never depend on a
specific vendor's client library.
"""

from __future__ import annotations

import logging
from typing import Protocol

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class LLMError(RuntimeError):
    pass


def _provider_failure(name: str, response: httpx.Response) -> LLMError:
    """Never forward a provider's response body to the caller.

    It is uninteresting on a good day and dangerous on a bad one: Gemini takes
    the API key as a URL query parameter, and provider error payloads
    routinely echo request context. The body is logged for whoever is
    debugging; the browser gets the status and nothing else."""
    logger.error(f"{name} request failed ({response.status_code}): {response.text[:2000]}")
    return LLMError(f"The AI provider returned an error ({response.status_code}).")


class LLMProvider(Protocol):
    async def generate(self, prompt: str) -> str: ...


class GeminiProvider:
    """Google Gemini via the generativelanguage REST API."""

    DEFAULT_MODEL = "gemini-2.0-flash"
    DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(self, api_key: str, model: str = "", base_url: str = ""):
        self.api_key = api_key
        self.model = model or self.DEFAULT_MODEL
        self.base_url = base_url or self.DEFAULT_BASE_URL

    async def generate(self, prompt: str) -> str:
        url = f"{self.base_url}/models/{self.model}:generateContent"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                url,
                params={"key": self.api_key},
                json={"contents": [{"parts": [{"text": prompt}]}]},
            )

        if response.is_error:
            raise _provider_failure("Gemini", response)

        payload = response.json()
        try:
            return payload["candidates"][0]["content"]["parts"][0]["text"].strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("Unexpected Gemini response shape") from exc


class OpenAIProvider:
    """OpenAI (or any OpenAI-compatible) chat completions API."""

    DEFAULT_MODEL = "gpt-4o-mini"
    DEFAULT_BASE_URL = "https://api.openai.com/v1"

    def __init__(self, api_key: str, model: str = "", base_url: str = ""):
        self.api_key = api_key
        self.model = model or self.DEFAULT_MODEL
        self.base_url = base_url or self.DEFAULT_BASE_URL

    async def generate(self, prompt: str) -> str:
        url = f"{self.base_url}/chat/completions"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )

        if response.is_error:
            raise _provider_failure("OpenAI", response)

        payload = response.json()
        try:
            return payload["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("Unexpected OpenAI response shape") from exc


class OllamaProvider:
    """Local Ollama, or Ollama Cloud (ollama.com) when an api_key is set.

    Same native /api/generate endpoint either way — only the base URL and
    the presence of a bearer token differ.
    """

    DEFAULT_MODEL = "llama3.1"
    DEFAULT_BASE_URL = "http://localhost:11434"

    def __init__(self, api_key: str = "", model: str = "", base_url: str = ""):
        self.api_key = api_key
        self.model = model or self.DEFAULT_MODEL
        self.base_url = base_url or self.DEFAULT_BASE_URL

    async def generate(self, prompt: str) -> str:
        url = f"{self.base_url}/api/generate"
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                url,
                headers=headers,
                json={"model": self.model, "prompt": prompt, "stream": False},
            )

        if response.is_error:
            raise _provider_failure("Ollama", response)

        payload = response.json()
        try:
            return payload["response"].strip()
        except (KeyError, TypeError) as exc:
            raise LLMError("Unexpected Ollama response shape") from exc


_PROVIDERS: dict[str, type[LLMProvider]] = {
    "gemini": GeminiProvider,
    "openai": OpenAIProvider,
    "ollama": OllamaProvider,
}

_PROVIDERS_REQUIRING_API_KEY = {"gemini", "openai"}


def get_llm_provider() -> LLMProvider:
    provider_name = (settings.LLM_PROVIDER or "").strip().lower()
    provider_cls = _PROVIDERS.get(provider_name)
    if provider_cls is None:
        known = ", ".join(sorted(_PROVIDERS))
        raise LLMError(f"Unknown LLM_PROVIDER '{provider_name}'. Expected one of: {known}")

    if provider_name in _PROVIDERS_REQUIRING_API_KEY and not settings.LLM_API_KEY:
        raise LLMError(f"LLM_API_KEY is not configured for provider '{provider_name}'")

    return provider_cls(
        api_key=settings.LLM_API_KEY,
        model=settings.LLM_MODEL,
        base_url=settings.LLM_BASE_URL,
    )
