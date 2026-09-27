"""Application settings loaded from environment variables."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

_VALID_PROVIDERS = ("anthropic", "openai")

USER_SETTINGS_PATH = Path("data/user_settings.json")


def _load_user_settings() -> dict:
    """Settings saved from the UI 设置 tab; they override .env values."""
    try:
        if USER_SETTINGS_PATH.exists():
            data = json.loads(USER_SETTINGS_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def save_user_settings(values: dict) -> None:
    USER_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    USER_SETTINGS_PATH.write_text(
        json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8")


@dataclass(frozen=True)
class Settings:
    api_key: str
    model_name: str = "deepseek-chat"
    max_tokens: int = 16000
    llm_provider: str = "openai"
    llm_base_url: str = ""
    temperature: float = 0.3
    songs_dir: str = "data/songs"
    corpus_dir: str = "data/corpus"
    embedding_provider: str = "local"
    embedding_model: str = "all-MiniLM-L6-v2"
    ui_port: int = 7860
    ui_lang: str = "zh"
    # public deployment: per-visitor API keys (browser localStorage), read-only
    # library, no server-side chat history, hackathon playlist songs excluded
    public_mode: bool = False


def load_settings(require_api_key: bool = False) -> Settings:
    """Load settings from .env / environment.

    The UI can run fully offline (pre-generated annotations), so the API key
    is only required for LLM-backed commands (generate, debate, era summaries).
    """
    load_dotenv()
    public_mode = os.getenv("PUBLIC_MODE", "").strip().lower() in ("1", "true", "yes")
    user = {} if public_mode else _load_user_settings()

    generic_key = os.getenv("API_KEY", "")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    api_key = user.get("api_key", "") or generic_key or anthropic_key
    if not api_key and require_api_key:
        raise RuntimeError(
            "API_KEY is not set. "
            "在界面「⚙️ 设置」页签填写，或复制 .env.example 为 .env 后填入 API_KEY。"
        )

    llm_provider = (user.get("llm_provider", "") or os.getenv("LLM_PROVIDER", "")).lower()
    if llm_provider and llm_provider not in _VALID_PROVIDERS:
        raise RuntimeError(
            f"LLM_PROVIDER='{llm_provider}' is not supported. "
            f"Choose one of: {', '.join(_VALID_PROVIDERS)}"
        )
    if not llm_provider:
        # infer from key source: only ANTHROPIC_API_KEY set -> anthropic
        llm_provider = "anthropic" if (anthropic_key and not generic_key) else "openai"

    default_model = "claude-sonnet-5" if llm_provider == "anthropic" else "deepseek-chat"

    return Settings(
        api_key=api_key,
        model_name=user.get("model_name", "") or os.getenv("MODEL_NAME", default_model),
        max_tokens=int(os.getenv("MAX_TOKENS", "16000")),
        llm_provider=llm_provider,
        llm_base_url=user.get("llm_base_url", "") or os.getenv("LLM_BASE_URL", ""),
        temperature=float(os.getenv("TEMPERATURE", "0.3")),
        songs_dir=os.getenv("SONGS_DIR", "data/songs"),
        corpus_dir=os.getenv("CORPUS_DIR", "data/corpus"),
        embedding_provider=os.getenv("EMBEDDING_PROVIDER", "local"),
        embedding_model=os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2"),
        ui_port=int(os.getenv("UI_PORT", "7860")),
        ui_lang=os.getenv("UI_LANG", "zh"),
        public_mode=public_mode,
    )
