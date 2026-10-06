"""Spawn the real app, screenshot the play tab with the new theme."""
import subprocess, sys, time
from pathlib import Path
from playwright.sync_api import sync_playwright

PORT = 7903
proc = subprocess.Popen([sys.executable, "-m", "lyric_agent.cli", "serve", "--port", str(PORT)],
                        cwd=str(Path(__file__).parents[1]),
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        page = b.new_page(viewport={"width": 1600, "height": 1000})
        for _ in range(60):
            try:
                page.goto(f"http://127.0.0.1:{PORT}", timeout=2000)
                break
            except Exception:
                time.sleep(1)
        page.wait_for_timeout(4000)
        try:  # dismiss onboarding if present
            page.get_by_text("跳过", exact=True).click(timeout=3000)
        except Exception:
            pass
        page.wait_for_timeout(1000)
        page.screenshot(path=str(Path(__file__).parent / "live_pop.png"))
        b.close()
finally:
    proc.terminate()
print("done")
