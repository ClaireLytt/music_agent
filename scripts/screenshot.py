#!/usr/bin/env python3
"""Screenshot one UI tab for the design-critic loop.

Spawns its own server (same recipe as ui_probe.py) unless --port points at a
running one, opens the page in headless Chromium, clicks to the requested tab,
and saves a full-page PNG.

Usage:
    python scripts/screenshot.py                        # 🎧 播放解读 tab
    python scripts/screenshot.py --tab "🎮 互动" --sub "🕵️ 歌迷考据"
    python scripts/screenshot.py --port 7860 --out data/design_loop/iter_1.png
"""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "design_loop"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_server(base: str, timeout_s: int = 60, proc=None) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if proc is not None and proc.poll() is not None:
            raise RuntimeError(
                f"server exited with code {proc.returncode} before becoming "
                f"ready; see {OUT_DIR / 'server.log'}")
        try:
            with urllib.request.urlopen(base, timeout=3) as r:
                if r.status == 200:
                    return
        except Exception:
            time.sleep(1)
    raise RuntimeError(f"server at {base} not ready in {timeout_s}s")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tab", default="🎧 播放解读", help="top-level tab label")
    ap.add_argument("--sub", default=None, help="optional sub-tab label")
    ap.add_argument("--port", type=int, default=None,
                    help="attach to a running server instead of spawning one")
    ap.add_argument("--out", default=None,
                    help="output PNG path (default data/design_loop/<ts>.png)")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = Path(args.out) if args.out else (
        OUT_DIR / f"shot_{time.strftime('%Y%m%d_%H%M%S')}.png")

    proc = None
    log = None
    if args.port:
        base = f"http://127.0.0.1:{args.port}"
    else:
        port = free_port()
        base = f"http://127.0.0.1:{port}"
        env = {**os.environ, "UI_PORT": str(port), "BILI_AUTO_BIND": "0",
               "LL_CORPUS_REBUILD": "0", "LL_WORD_EXAMPLES": "0"}
        log = open(OUT_DIR / "server.log", "w", encoding="utf-8")
        proc = subprocess.Popen(
            [sys.executable, "-m", "lyric_agent.cli", "serve", "--no-browser"],
            cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT, env=env)
        print(f"spawned server on {base} (pid {proc.pid})")

    try:
        wait_server(base, proc=proc)
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.goto(base)
            page.wait_for_timeout(3000)  # let Gradio hydrate
            page.get_by_role("tab", name=args.tab, exact=True).click()
            page.wait_for_timeout(1000)
            if args.sub:
                page.get_by_role("tab", name=args.sub, exact=True).click()
                page.wait_for_timeout(1000)
            page.screenshot(path=str(out), full_page=True)
            browser.close()
    finally:
        if proc is not None:
            proc.kill()
            proc.wait(timeout=10)
        if log is not None:
            log.close()

    print(f"screenshot -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
