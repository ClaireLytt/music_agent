@echo off
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
start "" http://127.0.0.1:7860
lyric-agent serve
