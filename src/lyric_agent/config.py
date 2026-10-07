"""Application settings loaded from environment variables."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

_VALID_PROVIDERS = ("anthropic", "openai")

# fallback model per provider when the user leaves 模型名称 blank
DEFAULT_MODELS = {"anthropic": "claude-sonnet-5", "openai": "deepseek-chat"}

# canonical embedding model: corpus embeddings and query encoding must agree,
# so every layer (config / embeddings / search) references this one constant
DEFAULT_EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"

# 彩蛋 (easter-egg) similarity thresholds:
#   ECHO_MIN_SIMILARITY    strong echo — whole-song 🥚 map + artist network map
#   ECHO_SEARCH_SIMILARITY exploratory — per-line 互文追踪 panel (top-K cards)
# *_CJK variants apply when either line is mostly CJK: even with the
# multilingual model, CJK similarities run hotter than English ones, so
# CJK pairs keep a somewhat stricter cutoff. (The old English-only
# all-MiniLM-L6-v2 needed 0.90 here; retune if the model changes again.)
DEFAULT_ECHO_MIN_SIMILARITY = 0.62
DEFAULT_ECHO_MIN_SIMILARITY_CJK = 0.75
DEFAULT_ECHO_SEARCH_SIMILARITY = 0.35
DEFAULT_ECHO_SEARCH_SIMILARITY_CJK = 0.45
DEFAULT_ECHO_TOP_K = 4
DEFAULT_ECHO_MAP_MAX_NODES = 18

# metadata.json "source" value of hackathon-playlist material, which is
# licensed for offline demo only and must never appear on a public deployment
HACKATHON_PLAYLIST_SOURCE = "tme_hackathon_playlist"

def user_settings_path() -> Path:
    return Path(os.getenv("USER_SETTINGS_PATH", "data/user_settings.json"))


def default_model_for(provider: str) -> str:
    return DEFAULT_MODELS.get(provider, DEFAULT_MODELS["openai"])


def _load_user_settings() -> dict:
    """Settings saved from the UI 设置 tab; they override .env values."""
    path = user_settings_path()
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:
        # a corrupt settings file silently reverting to .env is confusing —
        # leave a trace, then fall back
        logger.exception("Failed reading %s — falling back to .env", path)
    return {}


def save_user_settings(values: dict) -> None:
    from .jsonio import write_json_atomic
    write_json_atomic(user_settings_path(), values, indent=2)


@dataclass(frozen=True)
class Settings:
    api_key: str
    model_name: str = DEFAULT_MODELS["openai"]
    max_tokens: int = 16000
    llm_provider: str = "openai"
    llm_base_url: str = ""
    temperature: float = 0.3
    songs_dir: str = "data/songs"
    corpus_dir: str = "data/corpus"
    evolution_path: str = "data/evolution/evolution.json"
    embedding_model: str = DEFAULT_EMBEDDING_MODEL
    echo_min_similarity: float = DEFAULT_ECHO_MIN_SIMILARITY
    echo_min_similarity_cjk: float = DEFAULT_ECHO_MIN_SIMILARITY_CJK
    echo_search_min_similarity: float = DEFAULT_ECHO_SEARCH_SIMILARITY
    echo_search_min_similarity_cjk: float = DEFAULT_ECHO_SEARCH_SIMILARITY_CJK
    echo_top_k: int = DEFAULT_ECHO_TOP_K
    echo_map_max_nodes: int = DEFAULT_ECHO_MAP_MAX_NODES
    ui_port: int = 7860
    # per-request LLM timeout (seconds); the SDK defaults are 10 minutes,
    # which turns one dead proxy request into a 10-minute stall
    llm_timeout: int = 120
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
    llm_timeout = int(os.getenv("LLM_TIMEOUT", "120") or 120)
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

    return Settings(
        api_key=api_key,
        model_name=user.get("model_name", "")
        or os.getenv("MODEL_NAME", default_model_for(llm_provider)),
        max_tokens=int(os.getenv("MAX_TOKENS", "16000")),
        llm_provider=llm_provider,
        llm_base_url=user.get("llm_base_url", "") or os.getenv("LLM_BASE_URL", ""),
        temperature=float(os.getenv("TEMPERATURE", "0.3")),
        songs_dir=os.getenv("SONGS_DIR", "data/songs"),
        corpus_dir=os.getenv("CORPUS_DIR", "data/corpus"),
        evolution_path=os.getenv("EVOLUTION_PATH", "data/evolution/evolution.json"),
        # the UI's rebuild-index flow persists the chosen model here
        embedding_model=user.get("embedding_model", "")
        or os.getenv("EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL),
        echo_min_similarity=float(
            os.getenv("ECHO_MIN_SIMILARITY", str(DEFAULT_ECHO_MIN_SIMILARITY))),
        echo_min_similarity_cjk=float(
            os.getenv("ECHO_MIN_SIMILARITY_CJK",
                      str(DEFAULT_ECHO_MIN_SIMILARITY_CJK))),
        echo_search_min_similarity=float(
            os.getenv("ECHO_SEARCH_SIMILARITY", str(DEFAULT_ECHO_SEARCH_SIMILARITY))),
        echo_search_min_similarity_cjk=float(
            os.getenv("ECHO_SEARCH_SIMILARITY_CJK",
                      str(DEFAULT_ECHO_SEARCH_SIMILARITY_CJK))),
        echo_top_k=int(os.getenv("ECHO_TOP_K", str(DEFAULT_ECHO_TOP_K))),
        echo_map_max_nodes=int(
            os.getenv("ECHO_MAP_MAX_NODES", str(DEFAULT_ECHO_MAP_MAX_NODES))),
        ui_port=int(os.getenv("UI_PORT", "7860")),
        public_mode=public_mode,
        llm_timeout=llm_timeout,
    )
