"""AI 电台: synthesize spoken intros (串场语音) for songs via edge-tts.

edge-tts talks to Microsoft's free TTS endpoint, so it needs network at
generation time. The synthesized mp3 is cached in the song directory
(radio_intro.mp3) and served like any other audio file.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

INTRO_AUDIO_FILENAME = "radio_intro.mp3"
DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"


def intro_audio_path(song_dir: str | Path) -> Path:
    return Path(song_dir) / INTRO_AUDIO_FILENAME


def synthesize_intro(song_dir: str | Path, text: str,
                     voice: str = DEFAULT_VOICE) -> Path:
    """Generate (or reuse) the cached spoken intro for one song."""
    out = intro_audio_path(song_dir)
    if out.exists():
        if out.stat().st_size > 0:
            return out
        out.unlink()  # empty leftover from a previously failed run
    import edge_tts

    async def _run() -> None:
        await edge_tts.Communicate(text, voice).save(str(out))

    try:
        try:
            asyncio.run(_run())
        except RuntimeError:
            # already inside an event loop (e.g. some gradio setups)
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(_run())
            finally:
                loop.close()
        if not out.exists() or out.stat().st_size == 0:
            raise RuntimeError("edge-tts 未产出音频（请检查网络）")
    except BaseException:
        # never leave a partial/empty file behind — the exists() check
        # above would otherwise treat it as a valid cached intro forever
        out.unlink(missing_ok=True)
        raise
    return out
