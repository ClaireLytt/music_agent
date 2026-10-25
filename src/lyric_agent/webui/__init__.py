"""webui — the Gradio front-end, split by tab.

Layout/handlers per tab live in tab_*.py; shared state in context.py /
runtime.py; cross-tab JS/MCP channels in channels.py; app.py glues them.
`lyric_agent.ui` stays as the public import surface (create_app 等从那里走).
"""
