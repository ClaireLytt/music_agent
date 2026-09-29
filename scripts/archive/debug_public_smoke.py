# -*- coding: utf-8 -*-
"""Smoke test: create_app builds in both local and public mode."""
import sys
from dataclasses import replace

sys.path.insert(0, "src")

from lyric_agent.config import load_settings
from lyric_agent.ui import create_app

s = load_settings()
create_app(s)
print("local mode: OK")

sp = replace(s, public_mode=True)
create_app(sp)
print("public mode: OK")
