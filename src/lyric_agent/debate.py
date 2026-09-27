"""Dual-persona AI debate about a lyric line (PRD F-19).

Two personas argue from different angles:
  critic — 文学评论家: rhetoric, metaphor systems, literary tradition
  fan    — 粉丝考据家: narrative threads, real-life mapping, easter eggs

The only feature that calls the LLM at runtime. Degrades gracefully
when no API key is configured.
"""

from __future__ import annotations

import logging
import queue
import threading
from dataclasses import dataclass, field
from typing import Any, Iterator

from .config import Settings

logger = logging.getLogger(__name__)

PERSONAS = {
    "assistant": {
        "name_zh": "🤖 AI 助手",
        "name_en": "🤖 AI Assistant",
        "system": (
            "你是一位精通 Taylor Swift 作品与歌词文学分析的私人 AI 助手。"
            "用户会针对某一句歌词提问，你结合已有批注、专辑背景、创作故事与文学视角，"
            "用平实亲切的简体中文回答，可以适当引用歌词原文。"
            "回答 100-250 字，直接给出内容，不要客套开场白。"
        ),
    },
    "critic": {
        "name_zh": "🎭 文学评论家",
        "name_en": "🎭 Literary Critic",
        "system": (
            "你是一位比较文学教授，正在参加一场关于歌词解读的圆桌辩论。"
            "你的分析侧重：隐喻体系、修辞技法、文学传统与互文、语言结构。"
            "你会引用文学理论但不掉书袋。你尊重对方观点但坚持文本细读的立场。"
            "每次发言 120-200 字，直接输出观点，不要客套开场白。用中文回答。"
        ),
    },
    "fan": {
        "name_zh": "🎵 粉丝考据家",
        "name_en": "🎵 Fan Theorist",
        "system": (
            "你是一位资深 Swiftie 粉丝考据家，正在参加一场关于歌词解读的圆桌辩论。"
            "你的分析侧重：专辑叙事线索（如 folklore 三部曲）、真实事件与人物映射、"
            "彩蛋与自我互文、粉丝社群的经典理论。"
            "你认为文学分析有时想得太多——故事逻辑和创作背景才是钥匙。"
            "每次发言 120-200 字，直接输出观点，不要客套开场白。用中文回答。"
        ),
    },
}


@dataclass
class DebateSession:
    lyric_line: str
    song_title: str
    annotation_context: str = ""
    line_index: int = -1
    history: list[dict] = field(default_factory=list)  # {"speaker","text"}


def _build_context(session: DebateSession) -> str:
    parts = [
        f"正在讨论的歌词：《{session.song_title}》中的一句 —— \"{session.lyric_line}\"",
    ]
    if session.annotation_context:
        parts.append(f"已有的 AI 批注参考：{session.annotation_context}")
    if session.history:
        parts.append("辩论记录：")
        for turn in session.history:
            parts.append(f"[{turn['speaker']}] {turn['text']}")
    return "\n\n".join(parts)


def is_available(settings: Settings) -> bool:
    return bool(settings.api_key)


def speak(
    settings: Settings,
    session: DebateSession,
    persona: str,
    user_prompt: str = "",
) -> Iterator[str]:
    """Stream one persona's next utterance. Yields text deltas."""
    if persona not in PERSONAS:
        raise ValueError(f"Unknown persona: {persona}")
    if not is_available(settings):
        yield ("⚠️ AI 回答需要配置 LLM API Key。"
               "请到「⚙️ 设置」页签填写 API Key 并保存。")
        return

    from .llm import LLMClient

    context = _build_context(session)
    if user_prompt:
        instruction = f"用户提出了新的观点/问题：{user_prompt}\n请回应用户，并推进你的论点。"
    elif session.history:
        instruction = "请针对辩论记录中最近一条对方发言进行回应，提出你的反驳或补充。"
    else:
        instruction = "请给出你对这句歌词的开场分析。"

    client = LLMClient(settings)
    q: queue.Queue = queue.Queue()
    _DONE = object()
    state: dict[str, Any] = {}

    def worker() -> None:
        try:
            resp = client.generate(
                system_prompt=PERSONAS[persona]["system"],
                user_message=f"{context}\n\n{instruction}",
                on_text_delta=q.put,
            )
            state["full"] = resp.reply_text
        except Exception as exc:
            logger.exception("Debate LLM call failed")
            state["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            q.put(_DONE)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

    chunks: list[str] = []
    while True:
        item = q.get()
        if item is _DONE:
            break
        chunks.append(item)
        yield item
    thread.join()

    if state.get("error"):
        detail = str(state["error"])[:200]
        yield f"⚠️ LLM 调用失败，请检查网络与 API Key 配置。\n\n错误详情：{detail}"
        return

    streamed = "".join(chunks)
    full = state.get("full") or streamed
    # non-streamed remainder (e.g. reply_text longer than streamed deltas)
    if full != streamed and full.startswith(streamed):
        tail = full[len(streamed):]
        if tail:
            yield tail
    elif not streamed and full:
        yield full

    session.history.append({
        "speaker": PERSONAS[persona]["name_zh"],
        "text": full,
    })
