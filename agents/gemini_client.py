"""
Thin wrapper over google-genai with the resilience this app needs.

Gemini's flash tier returns 503 UNAVAILABLE or times out under load often enough
that a single-model call is not dependable for a live demo, and the Pro models
answer 429 on a free-tier key. So every request walks a chain of interchangeable
flash models and only fails once all of them have been tried.

The API key is read from the environment and never logged.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any

from dotenv import load_dotenv
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

# The SDK warns about automatic function calling on every generate_content call;
# we never pass tools, so the warning is pure noise.
logging.getLogger('google_genai.models').setLevel(logging.ERROR)

# Verified as serving on this key. Ordered fastest-and-most-reliable first.
MODEL_CHAIN = [
    'gemini-3.5-flash',
    'gemini-2.5-flash',
    'gemini-3-flash-preview',
    'gemini-3.1-flash-lite',
    'gemini-3.6-flash',
]
DEFAULT_MODEL = MODEL_CHAIN[0]

# Offered in the sidebar. Pro models are excluded: they return 429 on this key.
SELECTABLE_MODELS = list(MODEL_CHAIN)

DEFAULT_TIMEOUT_MS = 90_000

# Thinking models can spend the whole budget on reasoning and return empty text,
# so the ceiling stays generous.
DEFAULT_MAX_TOKENS = 8192


class GeminiError(RuntimeError):
    """A Gemini call failed in a way the caller should surface to the user."""


class GeminiAuthError(GeminiError):
    """The API key is missing, malformed or rejected."""


class GeminiUnavailable(GeminiError):
    """Every model in the chain refused the request."""


def load_api_key(explicit: str | None = None) -> str:
    """Explicit value wins, then GEMINI_API_KEY from the environment or .env."""
    if explicit and explicit.strip():
        return explicit.strip()
    load_dotenv()
    key = os.environ.get('GEMINI_API_KEY', '').strip()
    if not key:
        raise GeminiAuthError(
            'No Gemini API key found. Add GEMINI_API_KEY to .env or paste a key '
            'in the sidebar.')
    return key


def _is_transient(exc: Exception) -> bool:
    """503/429/500 and read timeouts are worth trying on another model."""
    if isinstance(exc, genai_errors.ServerError):
        return True
    if isinstance(exc, genai_errors.ClientError):
        return getattr(exc, 'code', None) in (408, 429)
    return isinstance(exc, (TimeoutError,)) or 'timeout' in type(exc).__name__.lower()


def _is_auth(exc: Exception) -> bool:
    return (isinstance(exc, genai_errors.ClientError)
            and getattr(exc, 'code', None) in (401, 403))


FENCE_RE = re.compile(r'^\s*```(?:json)?\s*(.*?)\s*```\s*$', re.DOTALL)


def _parse_json(text: str) -> Any:
    """Structured output should be clean JSON, but strip a code fence just in case."""
    if not text or not text.strip():
        raise GeminiError('Gemini returned an empty response.')
    stripped = text.strip()
    if (match := FENCE_RE.match(stripped)):
        stripped = match.group(1)
    try:
        return json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise GeminiError(f'Gemini returned malformed JSON: {exc}') from exc


@dataclass
class CallRecord:
    """One completed request, for the diagnostics panel in the UI."""
    label: str
    model: str
    seconds: float
    tokens: int
    attempts: int


@dataclass
class GeminiClient:
    api_key: str
    model: str = DEFAULT_MODEL
    timeout_ms: int = DEFAULT_TIMEOUT_MS
    calls: list[CallRecord] = field(default_factory=list)
    _client: genai.Client | None = field(default=None, repr=False)

    @classmethod
    def create(cls, api_key: str | None = None, model: str = DEFAULT_MODEL,
               timeout_ms: int = DEFAULT_TIMEOUT_MS) -> 'GeminiClient':
        return cls(api_key=load_api_key(api_key), model=model or DEFAULT_MODEL,
                   timeout_ms=timeout_ms)

    @property
    def client(self) -> genai.Client:
        if self._client is None:
            self._client = genai.Client(
                api_key=self.api_key,
                http_options=types.HttpOptions(timeout=self.timeout_ms),
            )
        return self._client

    def model_chain(self) -> list[str]:
        """Preferred model first, then the rest of the chain as fallbacks."""
        return [self.model] + [m for m in MODEL_CHAIN if m != self.model]

    def check(self) -> str:
        """Smoke-test the key. Returns the model that answered."""
        _, model, _ = self._generate('connectivity check', 'Reply with OK.',
                                     system_instruction=None, schema=None,
                                     temperature=0.0, max_output_tokens=256)
        return model

    def generate_json(self, prompt: str, schema: dict, *, label: str = 'call',
                      system_instruction: str | None = None, temperature: float = 0.2,
                      max_output_tokens: int = DEFAULT_MAX_TOKENS) -> Any:
        text, _, _ = self._generate(label, prompt, system_instruction, schema,
                                    temperature, max_output_tokens)
        return _parse_json(text)

    def generate_text(self, prompt: str, *, label: str = 'call',
                      system_instruction: str | None = None, temperature: float = 0.3,
                      max_output_tokens: int = DEFAULT_MAX_TOKENS) -> str:
        text, _, _ = self._generate(label, prompt, system_instruction, None,
                                    temperature, max_output_tokens)
        return text

    def _generate(self, label: str, prompt: str, system_instruction: str | None,
                  schema: dict | None, temperature: float,
                  max_output_tokens: int) -> tuple[str, str, int]:
        config_kwargs: dict[str, Any] = {
            'temperature': temperature,
            'max_output_tokens': max_output_tokens,
        }
        if system_instruction:
            config_kwargs['system_instruction'] = system_instruction
        if schema is not None:
            config_kwargs['response_mime_type'] = 'application/json'
            config_kwargs['response_schema'] = schema

        config = types.GenerateContentConfig(**config_kwargs)

        started = time.time()
        attempts = 0
        failures: list[str] = []

        for model in self.model_chain():
            attempts += 1
            try:
                resp = self.client.models.generate_content(
                    model=model, contents=prompt, config=config)
            except Exception as exc:
                if _is_auth(exc):
                    raise GeminiAuthError(
                        'Gemini rejected the API key. Check GEMINI_API_KEY.') from exc
                if not _is_transient(exc):
                    raise GeminiError(f'{type(exc).__name__}: {exc}') from exc
                failures.append(f'{model}: {type(exc).__name__}')
                continue

            text = resp.text or ''
            if not text.strip():
                # Usually a thinking model that spent its whole token budget.
                failures.append(f'{model}: empty response')
                continue

            tokens = getattr(getattr(resp, 'usage_metadata', None),
                             'total_token_count', 0) or 0
            self.calls.append(CallRecord(label=label, model=model,
                                         seconds=time.time() - started,
                                         tokens=int(tokens), attempts=attempts))
            return text, model, int(tokens)

        raise GeminiUnavailable(
            'Every Gemini model in the fallback chain failed for '
            f'"{label}". Tried: ' + '; '.join(failures))

    # -- diagnostics ---------------------------------------------------------

    def total_tokens(self) -> int:
        return sum(c.tokens for c in self.calls)

    def total_seconds(self) -> float:
        return sum(c.seconds for c in self.calls)
