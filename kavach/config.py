"""Settings, loaded from environment variables (a .env file in the repo root works too).

Every key is optional until the piece that needs it runs:
  GNANI_API_KEY        Prisma STT + Timbre TTS (app.gnani.ai/voice)
  GROQ_API_KEY         LLM brain via Groq (console.groq.com, free tier)
  GEMINI_API_KEY       LLM brain via Google AI Studio (aistudio.google.com, free tier)
  KAVACH_LLM           which brain: "groq", "groq:openai/gpt-oss-20b", "gemini", "ollama", "openai_compat", "mock"
  LLM_BASE_URL / LLM_API_KEY / KAVACH_LLM_MODEL   for openai_compat (e.g. vLLM serving Gnani Evon)
  KAVACH_STT_MODEL     "" = Prisma default (v2.5). "prisma-v3.0" to try v3.
  KAVACH_TTS_MODEL     default "timbre-v2.5"
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:  # optional: load .env if python-dotenv is installed
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:  # pragma: no cover
    pass

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = Path(os.getenv("KAVACH_CACHE_DIR", str(ROOT / ".cache")))

# provider -> (base_url, env var holding the key, default model)
LLM_PRESETS: dict[str, tuple[str | None, str | None, str]] = {
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY", "openai/gpt-oss-120b"),
    "gemini": (
        "https://generativelanguage.googleapis.com/v1beta/openai/",
        "GEMINI_API_KEY",
        "gemini-2.5-flash",
    ),
    "ollama": ("http://localhost:11434/v1", None, "qwen2.5:7b-instruct"),
    "openai_compat": (None, "LLM_API_KEY", ""),
    "mock": (None, None, "mock-naive"),
}


@dataclass
class LLMSettings:
    provider: str
    base_url: str | None
    api_key: str | None
    model: str
    temperature: float = 0.0
    max_rpm: int = 25  # client-side rate limit (requests per minute)

    @property
    def label(self) -> str:
        return f"{self.provider}:{self.model}"


def llm_settings(spec: str | None = None) -> LLMSettings:
    """Parse a brain spec like 'groq', 'groq:openai/gpt-oss-20b', 'gemini', 'mock'."""
    spec = spec or os.getenv("KAVACH_LLM", "groq")
    provider, _, model = spec.partition(":")
    if provider not in LLM_PRESETS:
        raise ValueError(f"Unknown LLM provider {provider!r}. Use one of {sorted(LLM_PRESETS)}")
    base_url, key_env, default_model = LLM_PRESETS[provider]
    if provider == "openai_compat":
        base_url = os.getenv("LLM_BASE_URL")
        if not base_url:
            raise ValueError("Set LLM_BASE_URL for openai_compat (e.g. http://localhost:8000/v1)")
    api_key = os.getenv(key_env, "") if key_env else "not-needed"
    if provider in ("groq", "gemini") and not api_key:
        raise ValueError(f"{key_env} is not set. Add it to .env (see .env.example).")
    model = model or os.getenv("KAVACH_LLM_MODEL") or default_model
    if not model:
        raise ValueError("Set KAVACH_LLM_MODEL (or use provider:model).")
    rpm = int(os.getenv("KAVACH_LLM_RPM", "25"))
    return LLMSettings(provider, base_url, api_key or None, model, max_rpm=rpm)


def gnani_key() -> str:
    return os.getenv("GNANI_API_KEY", "")


STT_MODEL = os.getenv("KAVACH_STT_MODEL", "").strip() or None  # None = Prisma default (v2.5)
TTS_MODEL = os.getenv("KAVACH_TTS_MODEL", "timbre-v2.5")
