"""Render a shareable lyric-quote card (PNG) for a picked line + AI insight."""

from __future__ import annotations

import re
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

_FONT_CANDIDATES = [
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/msyhbd.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
]

_BOLD_CANDIDATES = ["C:/Windows/Fonts/msyhbd.ttc"] + _FONT_CANDIDATES

# PIL renders emoji as tofu boxes — drop them from card text
_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF\ufe0f]")

W, H = 900, 1200
MARGIN = 80


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    for path in (_BOLD_CANDIDATES if bold else _FONT_CANDIDATES):
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)


def _clean(text: str) -> str:
    return _EMOJI_RE.sub("", text or "").strip()


def _wrap(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """Character-based wrapping (works for CJK and keeps latin words intact)."""
    lines: list[str] = []
    for para in text.split("\n"):
        cur = ""
        for ch in para:
            if font.getlength(cur + ch) > max_width and cur:
                lines.append(cur)
                cur = ch.lstrip()
            else:
                cur += ch
        lines.append(cur)
    return [ln for ln in lines if ln != ""] or [""]


def _gradient(w: int, h: int, top: tuple, bottom: tuple) -> Image.Image:
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        t = y / max(h - 1, 1)
        c = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        for x in range(w):
            px[x, y] = c
    return img


def render_share_card(
    song_title: str,
    artist: str,
    lyric_line: str,
    insight: str,
    out_dir: str | Path = "data/cards",
) -> str:
    """Draw the card and return the saved PNG path."""
    lyric_line = _clean(lyric_line)
    insight = _clean(insight)

    img = _gradient(W, H, (38, 34, 66), (86, 52, 106))
    draw = ImageDraw.Draw(img)

    inner = W - 2 * MARGIN
    y = 110

    brand_font = _font(26)
    draw.text((MARGIN, y), "歌词透镜 · LYRIC LENS", font=brand_font,
              fill=(255, 255, 255, 200))
    y += 90

    quote_font = _font(120, bold=True)
    draw.text((MARGIN - 10, y - 30), "“", font=quote_font, fill=(255, 214, 130))
    y += 70

    lyric_font = _font(46, bold=True)
    lyric_lines = _wrap(lyric_line, lyric_font, inner)[:4]
    for ln in lyric_lines:
        draw.text((MARGIN, y), ln, font=lyric_font, fill=(255, 255, 255))
        y += 68

    y += 30
    draw.line([(MARGIN, y), (MARGIN + 120, y)], fill=(255, 214, 130), width=4)
    y += 44

    body_font = _font(28)
    max_body_lines = max((H - 200 - y) // 46, 3)
    body_lines = _wrap(insight, body_font, inner)
    if len(body_lines) > max_body_lines:
        body_lines = body_lines[:max_body_lines]
        body_lines[-1] = body_lines[-1][:-1] + "…"
    for ln in body_lines:
        draw.text((MARGIN, y), ln, font=body_font, fill=(226, 222, 240))
        y += 46

    footer_font = _font(26)
    meta = f"《{song_title}》" + (f" · {artist}" if artist else "")
    draw.text((MARGIN, H - 130), meta, font=footer_font, fill=(255, 214, 130))
    draw.text((MARGIN, H - 86), "AI 解读由「歌词透镜」生成",
              font=_font(20), fill=(200, 196, 220))

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"card_{int(time.time() * 1000)}.png"
    img.save(path)
    return str(path)
