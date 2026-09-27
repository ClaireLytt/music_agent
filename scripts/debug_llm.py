# -*- coding: utf-8 -*-
"""Verify LLM call through the app's own LLMClient (temperature auto-retry)."""
import sys
sys.path.insert(0, "src")

from lyric_agent.config import load_settings
from lyric_agent.llm import LLMClient

s = load_settings()
print("provider:", s.llm_provider, "| model:", s.model_name,
      "| base:", s.llm_base_url)
c = LLMClient(s)

print("\n=== non-stream ===")
r = c.generate(system_prompt="你是助手。", user_message="用一句话回复：测试成功")
print("OK:", repr(r.reply_text)[:200])

print("\n=== stream (debate path) ===")
parts = []
r = c.generate(system_prompt="你是助手。", user_message="用一句话回复：测试成功",
               on_text_delta=parts.append)
print("streamed:", repr("".join(parts))[:200])
print("full:", repr(r.reply_text)[:200])
