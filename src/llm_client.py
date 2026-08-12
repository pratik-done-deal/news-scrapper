"""The chat client every LLM call in this service goes through.

Gemini speaks the OpenAI chat-completions protocol at its compatibility
endpoint, so the client built here is a drop-in for the Groq client it
replaced: same `client.chat.completions.create(...)` call, same response
object, same `response_format={"type": "json_object"}`. Nothing downstream of
this factory changed when the provider did — only the client construction and
the model name in `config/settings.yaml`.

The key still arrives as `--groq-api-key` / `config.groq.api_key`, and the
model still lives under the `groq:` block in settings. Those names are now
misnomers, but every deployment command line and every exported
NEWS_SCRAPPER_CONFIG blob uses them, so they stay put — the value they carry
is simply a Gemini key.
"""

from typing import Optional

from openai import OpenAI

# Gemini's OpenAI-compatible endpoint. Overridable from `groq.base_url` in
# config/settings.yaml for a proxy or a pinned API version.
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"

# Fallback for callers that read the model straight out of settings; the real
# value lives in `groq.model` in config/settings.yaml.
DEFAULT_MODEL = "gemini-3.5-flash-lite"


def create_llm_client(api_key: str, settings: Optional[dict] = None) -> OpenAI:
    """Build the chat client from the `groq` block of `config/settings.yaml`."""
    llm_cfg = (settings or {}).get("groq", {}) or {}
    return OpenAI(
        api_key=api_key,
        base_url=llm_cfg.get("base_url", GEMINI_BASE_URL),
    )
