"""The chat client every LLM call in this service goes through.

Gemini is called through Google's own SDK (`google-genai`) — no OpenAI package
and no OpenAI-compatibility endpoint in the path. What this module exports is a
thin adapter: `create_llm_client()` returns an object whose
`client.chat.completions.create(...)` takes the same arguments and returns the
same `.choices[0].message.content` / `.usage.prompt_tokens` shape the Groq and
OpenAI clients did. That surface is kept deliberately — every call site passes
the identical kwargs, and `scripts/side_by_side_extraction.py` A/Bs this client
against a real Groq client through one shared `call_model()` helper. Swapping
the transport underneath left all of that untouched.

The key still arrives as `--groq-api-key` / `config.groq.api_key`, and the
model still lives under the `groq:` block in settings. Those names are now
misnomers, but every deployment command line and every exported
NEWS_SCRAPPER_CONFIG blob uses them, so they stay put — the value they carry
is simply a Gemini key.
"""

from dataclasses import dataclass
from typing import Any, Optional

from google import genai
from google.genai import types

# Fallback for callers that read the model straight out of settings; the real
# value lives in `groq.model` in config/settings.yaml.
DEFAULT_MODEL = "gemini-3.5-flash-lite"

# Deployments that predate the SDK swap still export
# `groq.base_url: .../v1beta/openai` in their config blob. That path only
# exists for the compatibility endpoint and is meaningless to the native
# client, so it is dropped rather than handed to the SDK, which would then
# build request URLs under it and 404. A base_url pointing anywhere else is a
# real proxy and is passed through.
_LEGACY_COMPAT_SUFFIXES = ("/v1beta/openai", "/v1beta/openai/")


@dataclass
class _Message:
    content: Optional[str]


@dataclass
class _Choice:
    message: _Message
    finish_reason: Optional[str] = None


@dataclass
class _Usage:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@dataclass
class _Response:
    """OpenAI-shaped view of a `GenerateContentResponse`."""

    choices: list
    usage: Optional[_Usage]
    model: str
    raw: Any


def _split_messages(messages: list) -> tuple:
    """Map chat-completions messages onto (system_instruction, contents)."""
    system_parts, contents = [], []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content") or ""
        if role == "system":
            system_parts.append(content)
            continue
        contents.append(
            types.Content(
                # Gemini names the assistant turn "model"; everything else is
                # a user turn.
                role="model" if role in ("assistant", "model") else "user",
                parts=[types.Part.from_text(text=content)],
            )
        )
    return ("\n\n".join(system_parts) or None), contents


class _Completions:
    def __init__(self, client: genai.Client):
        self._client = client

    def create(
        self,
        *,
        model: str,
        messages: list,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        response_format: Optional[dict] = None,
        **kwargs,
    ) -> _Response:
        system_instruction, contents = _split_messages(messages)
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=temperature,
            max_output_tokens=max_tokens,
            # `{"type": "json_object"}` is the only response_format this
            # service uses; Gemini expresses it as a response MIME type.
            response_mime_type=(
                "application/json"
                if (response_format or {}).get("type") == "json_object"
                else None
            ),
            **kwargs,
        )
        response = self._client.models.generate_content(
            model=model, contents=contents, config=config
        )

        candidates = response.candidates or []
        finish_reason = None
        if candidates and candidates[0].finish_reason is not None:
            finish_reason = str(candidates[0].finish_reason)

        usage = None
        if response.usage_metadata is not None:
            prompt_tokens = response.usage_metadata.prompt_token_count or 0
            # Thinking tokens bill as output but are counted separately, so
            # both go into completion_tokens to match what the OpenAI-shaped
            # cost math downstream expects.
            completion_tokens = (response.usage_metadata.candidates_token_count or 0) + (
                response.usage_metadata.thoughts_token_count or 0
            )
            usage = _Usage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=response.usage_metadata.total_token_count
                or (prompt_tokens + completion_tokens),
            )

        return _Response(
            choices=[_Choice(message=_Message(content=response.text), finish_reason=finish_reason)],
            usage=usage,
            model=model,
            raw=response,
        )


class _Chat:
    def __init__(self, client: genai.Client):
        self.completions = _Completions(client)


class GeminiChatClient:
    """`google-genai` behind a chat-completions-shaped facade."""

    def __init__(self, client: genai.Client):
        self.client = client
        self.chat = _Chat(client)


def create_llm_client(api_key: str, settings: Optional[dict] = None) -> GeminiChatClient:
    """Build the chat client from the `groq` block of `config/settings.yaml`."""
    llm_cfg = (settings or {}).get("groq", {}) or {}
    base_url = llm_cfg.get("base_url")
    if base_url and base_url.rstrip().endswith(_LEGACY_COMPAT_SUFFIXES):
        base_url = None

    http_options = types.HttpOptions(base_url=base_url) if base_url else None
    return GeminiChatClient(genai.Client(api_key=api_key, http_options=http_options))
