"""FastAPI 薄 API 层（前端重写 M2 垂直切片：播放解读页所需端点）。

铁律（docs/frontend_rewrite_plan.md）：本层不搬业务逻辑——参数校验 →
调 songdata/dictionary 数据层 → 序列化。MCP/CLI/SPA 三入口共享同一行为。
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import asdict
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import dictionary, songdata
from .config import load_settings
from .songdata import (
    _INTRO_FILENAME,
    _discover_songs,
    _load_intro,
    _load_notes,
    _load_song_data,
    _save_notes,
)

logger = logging.getLogger(__name__)

_FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


def _songs() -> list[dict]:
    settings = load_settings()
    songdata.set_songs_root(settings.songs_dir)
    exclude_cjk = os.getenv("LL_SHOW_CJK", "") not in ("1", "true", "yes")
    return _discover_songs(settings.songs_dir, exclude_cjk=exclude_cjk)


def _find_song(song_id: str) -> dict:
    for s in _songs():
        if s["name"] == song_id:
            return s
    raise HTTPException(status_code=404, detail=f"song not found: {song_id}")


def _song_payload(s: dict) -> dict:
    return {
        "id": s["name"], "title": s["title"], "artist": s["artist"],
        "album": s["album"], "year": s["year"],
        "audio_type": s["audio_type"],
        "audio_offset_ms": s["audio_offset_ms"],
        "bvid": s["bvid"],
    }


def _write_meta(song_dir: str, mutate) -> None:
    """读-改-写 metadata.json（与旧 UI handler 同一套逻辑）。"""
    meta_path = Path(song_dir) / "metadata.json"
    meta = (json.loads(meta_path.read_text(encoding="utf-8"))
            if meta_path.exists() else {})
    mutate(meta)
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                         encoding="utf-8")


# 导读后台生成状态（长耗时 LLM 铁律：后台线程 + 落盘 + 轮询）
_INTRO_TASKS: dict[str, str] = {}   # song_id -> "running" | "error: ..."
_FANLORE_TASKS: dict[str, dict] = {}   # song_id -> {status, progress?, msg?}
_REBUILD_STATE: dict = {"status": "none", "msg": ""}
_CORPUS_REBUILDING = threading.Lock()


def _kick_corpus_rebuild() -> None:
    """曲库增删后后台重建语料+embeddings（零 LLM），与旧 Runtime 同口径。"""
    if os.getenv("LL_CORPUS_REBUILD", "1") == "0":
        return  # probe/tests：不污染真实语料
    if not _CORPUS_REBUILDING.acquire(blocking=False):
        return

    def _run() -> None:
        try:
            from .intertextuality.corpus import build_corpus
            from .intertextuality.embeddings import generate_embeddings
            s = load_settings()
            build_corpus(s.songs_dir, s.corpus_dir,
                         catalog_path="data/catalog/catalog.json")
            generate_embeddings(s.corpus_dir, model_name=s.embedding_model)
        except Exception:
            logger.exception("background corpus rebuild failed")
        finally:
            _CORPUS_REBUILDING.release()
    threading.Thread(target=_run, daemon=True).start()


def _fanlore_echo_pairs(info: dict, data: dict) -> list[tuple]:
    """曲库呼应 = 喂给模型的硬证据（同旧 build_echo_map 的 top-5）。"""
    try:
        from .intertextuality.embeddings import load_embeddings
        from .intertextuality.search import find_song_echoes
        s = load_settings()
        embeddings, corpus = load_embeddings(s.corpus_dir, s.embedding_model)
        texts = [ln.text for ln in data["timed_lines"]]
        echoes = find_song_echoes(
            texts, embeddings, corpus, model_name=s.embedding_model,
            exclude_song=info.get("title", ""),
            artist=info.get("artist") or None,
            min_similarity=s.echo_min_similarity,
            min_similarity_cjk=s.echo_min_similarity_cjk)
        hits = [(e.similarity, texts[i], e.song, e.line)
                for i, e in enumerate(echoes) if e]
        hits.sort(reverse=True)
        return [(t, sg, ln) for _sim, t, sg, ln in hits[:5]]
    except Exception:
        logger.exception("fanlore echo scan unavailable")
        return []


def _gen_fanlore_bg(song_id: str, info: dict) -> None:
    try:
        from .fanlore import fanlore_messages, progress_stage, save_fanlore
        from .intertextuality.search import artist_matches
        from .llm import LLMClient
        data = _load_song_data(info["dir"])
        pairs = _fanlore_echo_pairs(info, data)
        titles = [s["title"] for s in _songs()
                  if artist_matches(info.get("artist", ""),
                                    s.get("artist", ""))]
        system, user_msg = fanlore_messages(
            info.get("title", ""), info.get("artist", ""),
            info.get("album", ""), info.get("year"),
            echo_pairs=pairs, library_titles=titles)
        settings = load_settings()
        buf: list[str] = []

        def _on_delta(piece: str) -> None:
            buf.append(piece)
            s = "".join(buf)
            _FANLORE_TASKS[song_id] = {"status": "running",
                                       "progress": progress_stage(s),
                                       "chars": len(s)}

        verdict = LLMClient(settings).generate_json(
            system, user_msg, on_text_delta=_on_delta)
        save_fanlore(info["dir"], verdict, settings.model_name)
        _FANLORE_TASKS[song_id] = {"status": "done"}
    except Exception as exc:
        logger.exception("fanlore generation failed for %s", song_id)
        _FANLORE_TASKS[song_id] = {"status": "error", "msg": str(exc)[:150]}


def _rebuild_index_bg(model: str) -> None:
    try:
        from .config import save_user_settings, user_settings_path
        from .intertextuality.corpus import build_corpus
        from .intertextuality.embeddings import generate_embeddings
        from .jsonio import read_json
        s = load_settings()
        catalog = Path("data/catalog/catalog.json")
        n_songs, n_lines = build_corpus(
            s.songs_dir, s.corpus_dir,
            catalog_path=catalog if catalog.exists() else None)
        _REBUILD_STATE.update(
            status="running",
            msg=f"2/2 语料库完成（{n_songs} 首 / {n_lines} 行），"
                f"正在用 {model} 生成 embeddings（首次需下载，1-3 分钟）…")
        generate_embeddings(s.corpus_dir, model_name=model)
        # 持久化模型选择（合并，不覆盖其他键）
        cur = read_json(user_settings_path(), default={})
        cur = cur if isinstance(cur, dict) else {}
        cur["embedding_model"] = model
        save_user_settings(cur)
        _REBUILD_STATE.update(
            status="done", msg=f"重建完成：{n_songs} 首 / {n_lines} 行，"
                               f"模型 {model} 已生效并保存")
    except Exception as exc:
        logger.exception("rebuild index failed")
        _REBUILD_STATE.update(status="error", msg=str(exc)[:200])


def _gen_intro_bg(song_id: str, info: dict) -> None:
    try:
        data = _load_song_data(info["dir"])
        lyrics_text = "\n".join(ln.text for ln in data["timed_lines"])
        user_msg = (
            f"歌名：《{info.get('title', '')}》\n"
            f"歌手：{info.get('artist', '')}\n"
            f"专辑：{info.get('album', '') or '未知'}\n\n"
            f"完整歌词：\n{lyrics_text}\n\n"
            "请写一段 120-180 字的「歌曲导读」：这首歌讲了什么故事/情绪，"
            "创作背景（确定的才写），以及听的时候值得注意的 1-2 个歌词细节。"
            "语气亲切自然，直接输出正文。"
        )
        from .llm import LLMClient
        resp = LLMClient(load_settings()).generate(
            system_prompt=("你是精通流行音乐与歌词分析的电台 DJ，"
                           "用简体中文写作，克制而准确。"),
            user_message=user_msg,
        )
        text = (resp.reply_text or "").strip()
        if not text:
            _INTRO_TASKS[song_id] = "error: AI 未返回内容，请重试"
            return
        (Path(info["dir"]) / _INTRO_FILENAME).write_text(
            text, encoding="utf-8")
        _INTRO_TASKS.pop(song_id, None)
    except Exception as exc:
        logger.exception("Intro generation failed for %s", song_id)
        _INTRO_TASKS[song_id] = f"error: {str(exc)[:150]}"


def create_app() -> FastAPI:
    app = FastAPI(title="Lyric Lens API")

    @app.get("/api/songs")
    def list_songs(q: str = "") -> list[dict]:
        songs = _songs()
        q = (q or "").strip().lower()
        if q:
            def hit(s: dict) -> bool:
                if q in s["title"].lower() or q in s["artist"].lower():
                    return True
                try:  # 全文歌词匹配（与旧 UI 歌单筛选同口径）
                    data = _load_song_data(s["dir"])
                    return any(q in ln.text.lower()
                               for ln in data["timed_lines"])
                except Exception:
                    return False
            songs = [s for s in songs if hit(s)]
        return [_song_payload(s) for s in songs]

    @app.get("/api/songs/{song_id}")
    def get_song(song_id: str) -> dict:
        return _song_payload(_find_song(song_id))

    @app.get("/api/songs/{song_id}/lyrics")
    def get_lyrics(song_id: str) -> dict:
        s = _find_song(song_id)
        data = _load_song_data(s["dir"])
        return {
            "timed_lines": [
                {"line_index": tl.line_index, "timestamp_ms": tl.timestamp_ms,
                 "text": tl.text}
                for tl in data["timed_lines"]
            ],
            "annotations": {
                str(idx): asdict(ann)
                for idx, ann in data["annotations"].items()
            },
        }

    @app.get("/api/songs/{song_id}/audio")
    def get_audio(song_id: str):
        s = _find_song(song_id)
        if s["audio_type"] == "url":
            return RedirectResponse(s["audio_src"])
        if s["audio_type"] == "local" and Path(s["audio_src"]).exists():
            return FileResponse(s["audio_src"])
        raise HTTPException(status_code=404, detail="no audio for this song")

    # ── 歌曲工具（旧 tab_play_tools 的 REST 化） ──────────────

    @app.put("/api/songs/{song_id}/bvid")
    def put_bvid(song_id: str, value: str = Body("", embed=True)) -> dict:
        from .bilibili import extract_bvid
        s = _find_song(song_id)
        value = (value or "").strip()
        bvid = extract_bvid(value) if value else ""
        if value and not bvid:
            raise HTTPException(422, "无法识别 BV 号/链接")

        def mutate(meta: dict) -> None:
            if bvid:
                meta["bvid"] = bvid
                meta.pop("bvid_no_auto", None)  # 用户重选=重新放行自动绑定
            else:
                meta.pop("bvid", None)
                meta["bvid_no_auto"] = True     # 留空保存=解绑且不再自动绑
        _write_meta(s["dir"], mutate)
        return {"bvid": bvid}

    @app.put("/api/songs/{song_id}/offset")
    def put_offset(song_id: str,
                   offset_ms: int = Body(0, embed=True)) -> dict:
        s = _find_song(song_id)

        def mutate(meta: dict) -> None:
            if int(offset_ms):
                meta["audio_offset_ms"] = int(offset_ms)
            else:
                meta.pop("audio_offset_ms", None)
        _write_meta(s["dir"], mutate)
        return {"audio_offset_ms": int(offset_ms)}

    @app.post("/api/songs/{song_id}/audio")
    async def upload_audio(song_id: str, file: UploadFile) -> dict:
        s = _find_song(song_id)
        ext = Path(file.filename or "").suffix.lower()
        if ext not in {".mp3", ".wav", ".flac", ".ogg", ".m4a"}:
            raise HTTPException(422, "仅支持 mp3 / wav / flac / ogg / m4a")
        d = Path(s["dir"])
        for old in d.glob("audio.*"):
            old.unlink()
        (d / f"audio{ext}").write_bytes(await file.read())
        # 手动上传的是完整歌曲——清掉试听片段偏移（与旧 UI 行为一致）
        _write_meta(s["dir"], lambda m: m.pop("audio_offset_ms", None))
        return {"audio_type": "local"}

    # ── 听歌笔记 ──────────────────────────────────────────────

    @app.get("/api/songs/{song_id}/notes")
    def get_notes(song_id: str) -> list[dict]:
        return _load_notes(_find_song(song_id)["dir"])

    @app.post("/api/songs/{song_id}/notes")
    def add_note(song_id: str, ts_ms: int = Body(...),
                 text: str = Body(...)) -> list[dict]:
        s = _find_song(song_id)
        text = (text or "").strip()
        if not text:
            raise HTTPException(422, "笔记内容不能为空")
        notes = _load_notes(s["dir"])
        notes.append({"ts_ms": int(ts_ms), "text": text})
        _save_notes(s["dir"], notes)
        return notes

    @app.delete("/api/songs/{song_id}/notes/{ts_ms}")
    def del_note(song_id: str, ts_ms: int) -> list[dict]:
        s = _find_song(song_id)
        notes = [n for n in _load_notes(s["dir"])
                 if int(n.get("ts_ms", -1)) != int(ts_ms)]
        _save_notes(s["dir"], notes)
        return notes

    # ── 单词本 / 词组本（跟随歌曲） ───────────────────────────

    @app.get("/api/wordbook")
    def get_wordbook(song: str = "") -> list[dict]:
        book = dictionary.load_wordbook()
        if song:
            book = [e for e in book if e.get("song", "") == song]
        return book

    @app.post("/api/wordbook")
    def post_word(word: str = Body(...), line: str = Body(""),
                  song: str = Body(""),
                  line_index: int = Body(-1)) -> list[dict]:
        if not (word or "").strip():
            raise HTTPException(422, "word 不能为空")
        # 弹卡里生成过的 AI 语境解释随词条入本（与旧 on_wb_act 一致）
        import hashlib
        key = hashlib.md5(f"v3:{word.strip()}\x00{line}".encode()).hexdigest()
        try:
            ai = json.loads(
                (Path(load_settings().songs_dir).parent / "dict"
                 / "ai_cache.json").read_text(encoding="utf-8")).get(key, "")
        except (OSError, ValueError):
            ai = ""
        return dictionary.add_word(word.strip(), line=line, song=song,
                                   line_index=line_index, ai=ai)

    @app.delete("/api/wordbook/{word}")
    def delete_word(word: str) -> list[dict]:
        return dictionary.remove_word(word)

    # ── 歌曲导读（缓存命中直接回；否则后台生成 + 轮询） ──────

    @app.get("/api/songs/{song_id}/intro")
    def get_intro(song_id: str) -> dict:
        s = _find_song(song_id)
        text = _load_intro(s["dir"])
        if text:
            return {"status": "done", "text": text}
        st = _INTRO_TASKS.get(song_id, "")
        if st == "running":
            return {"status": "running", "text": ""}
        if st.startswith("error:"):
            return {"status": "error", "text": st[6:].strip()}
        return {"status": "none", "text": ""}

    @app.post("/api/songs/{song_id}/intro")
    def gen_intro(song_id: str) -> dict:
        s = _find_song(song_id)
        if _load_intro(s["dir"]):
            return {"status": "done"}
        if not load_settings().api_key:
            raise HTTPException(400, "未配置 API Key：请在 .env 填写后重启")
        if _INTRO_TASKS.get(song_id) != "running":
            _INTRO_TASKS[song_id] = "running"
            threading.Thread(target=_gen_intro_bg, args=(song_id, s),
                             daemon=True).start()
        return {"status": "running"}

    # ── 歌曲寻词（打字练习；旧 tab_review 的 REST 化） ────────

    def _drill_book(group: str) -> list[dict]:
        from .dictionary import is_phrase
        book = dictionary.load_wordbook()
        if group == "📖 歌词收藏":
            return [e for e in book if not e.get("group")]
        if group == "🔤 单词":
            return [e for e in book if not is_phrase(e.get("word", ""))]
        if group == "🧩 词组":
            return [e for e in book if is_phrase(e.get("word", ""))]
        if group and group != "全部":
            return [e for e in book if e.get("group") == group]
        return book

    @app.get("/api/drill/queue")
    def drill_queue(group: str = "全部") -> dict:
        from .review import book_stats, round_queue
        book = _drill_book(group)
        order = round_queue(book)
        by_word = {e.get("word", "").lower(): e for e in book}
        return {
            "entries": [by_word[w.lower()] for w in order
                        if w.lower() in by_word],
            "stats": book_stats(dictionary.load_wordbook()),
        }

    @app.get("/api/drill/card/{word}")
    def drill_card(word: str) -> dict:
        from .review import synthesize_word, word_examples
        entry = next((e for e in dictionary.load_wordbook()
                      if e.get("word", "").lower() == word.lower()), None)
        if not entry:
            raise HTTPException(404, f"单词本里没有「{word}」")
        examples = word_examples(
            entry["word"], exclude_song=entry.get("song", ""),
            corpus_dir=load_settings().corpus_dir)
        tts = synthesize_word(entry["word"])
        return {"entry": entry, "examples": examples, "tts": bool(tts)}

    @app.get("/api/drill/tts/{word}")
    def drill_tts(word: str):
        from .review import synthesize_word
        mp3 = synthesize_word(word)
        if not mp3:
            raise HTTPException(404, "TTS 不可用")
        return FileResponse(mp3, media_type="audio/mpeg")

    @app.post("/api/drill/result")
    def drill_result(word: str = Body(...), clean: bool = Body(...),
                     blind: bool = Body(False),
                     peeks: int = Body(0)) -> dict:
        from .review import book_stats, record_result
        record_result(word, clean, blind=blind, peeks=max(0, int(peeks)))
        return {"stats": book_stats(dictionary.load_wordbook())}

    @app.get("/api/drill/analysis")
    def drill_analysis() -> dict:
        from .review import is_mastered, weak_words
        from .stats import backfill_from_wordbook, year_series
        book = dictionary.load_wordbook()
        stats = backfill_from_wordbook(book)
        practiced = [e for e in book
                     if (e.get("review") or {}).get("correct", 0)
                     + (e.get("review") or {}).get("wrong", 0) > 0]
        return {
            "practice": year_series(stats, "practice"),
            "collect": year_series(stats, "collect"),
            "totals": {
                "collected": len(book),
                "practiced": len(practiced),
                "mastered": len([e for e in book if is_mastered(e)]),
            },
            "weak": weak_words(book),
        }

    # ── 单词本分组 / 导入 / 导出 ──────────────────────────────

    @app.get("/api/wordbook/groups")
    def wordbook_groups() -> list[str]:
        return dictionary.word_groups()

    @app.delete("/api/wordbook/groups/{group}")
    def wordbook_del_group(group: str) -> dict:
        return {"removed": dictionary.delete_group(group)}

    @app.post("/api/wordbook/import")
    async def wordbook_import(file: UploadFile,
                              group: str = "") -> dict:
        import tempfile
        suffix = Path(file.filename or "words.txt").suffix or ".txt"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            f.write(await file.read())
            tmp = f.name
        try:
            rows = dictionary.parse_wordlist_file(tmp)
        finally:
            os.unlink(tmp)
        if not rows:
            raise HTTPException(422, "没有解析出任何单词（支持 txt/json 词表）")
        group = (group or "").strip() or Path(file.filename or "导入").stem
        added, skipped = dictionary.import_words(rows, group)
        return {"added": added, "skipped": skipped, "group": group}

    @app.get("/api/wordbook/export")
    def wordbook_export(format: str = "json"):
        from fastapi.responses import PlainTextResponse
        from .review import export_anki, export_qwerty
        book = dictionary.load_wordbook()
        if not book:
            raise HTTPException(404, "单词本是空的，没有可导出的词")
        if format == "anki":
            return PlainTextResponse(
                export_anki(book), media_type="text/tab-separated-values",
                headers={"Content-Disposition":
                         'attachment; filename="lyric_lens_anki.txt"'})
        return PlainTextResponse(
            json.dumps(export_qwerty(book), ensure_ascii=False, indent=2),
            media_type="application/json",
            headers={"Content-Disposition":
                     'attachment; filename="lyric_lens_qwerty.json"'})

    # ── 歌迷考据（长文后台生成 + 缓存；铁律同导读） ──────────

    @app.get("/api/songs/{song_id}/fanlore")
    def get_fanlore(song_id: str) -> dict:
        from dataclasses import asdict as dc_asdict
        from .fanlore import load_fanlore, parse_fanlore
        s = _find_song(song_id)
        cached = load_fanlore(s["dir"])
        if cached is not None:
            return {"status": "done", "data": dc_asdict(parse_fanlore(cached))}
        st = _FANLORE_TASKS.get(song_id) or {}
        if st.get("status") == "running":
            return {"status": "running",
                    "progress": st.get("progress", ""),
                    "chars": st.get("chars", 0)}
        if st.get("status") == "error":
            return {"status": "error", "msg": st.get("msg", "")}
        return {"status": "none"}

    @app.post("/api/songs/{song_id}/fanlore")
    def gen_fanlore(song_id: str) -> dict:
        from .fanlore import load_fanlore
        s = _find_song(song_id)
        if load_fanlore(s["dir"]) is not None:
            return {"status": "done"}
        if not load_settings().api_key:
            raise HTTPException(400, "未配置 API Key：请到「设置」页填写")
        if (_FANLORE_TASKS.get(song_id) or {}).get("status") != "running":
            _FANLORE_TASKS[song_id] = {"status": "running"}
            threading.Thread(target=_gen_fanlore_bg, args=(song_id, s),
                             daemon=True).start()
        return {"status": "running"}

    @app.post("/api/chat/lore")
    def chat_lore(song_id: str = Body(...), question: str = Body(...),
                  history: list[dict] = Body(default=[])) -> dict:
        from .debate import DebateSession, speak as ai_speak
        from .fanlore import load_fanlore, parse_fanlore
        s = _find_song(song_id)
        question = (question or "").strip()
        if not question:
            raise HTTPException(422, "问题不能为空")
        settings = load_settings()
        if not settings.api_key:
            raise HTTPException(400, "未配置 API Key：请到「设置」页填写")
        ctx_txt = ""
        cached = load_fanlore(s["dir"])
        if cached is not None:
            f = parse_fanlore(cached)
            bits = ([f"一句话看懂：{f.hook}"] if f.hook else [])
            bits += [f"线索[{c.type}]{c.title}：{c.body}" for c in f.clues]
            if f.chain:
                bits.append("剧情推测链：" + " → ".join(
                    f"《{sg}》（{b}）" for sg, b in f.chain))
            if f.summary:
                bits.append(f"总结：{f.summary}")
            ctx_txt = ("用户正在看的考据页内容：\n" + "\n".join(bits))[:1500]
        session = DebateSession(
            lyric_line="（用户在看这首歌的考据页，可能就页面任何内容提问）",
            song_title=s.get("title", ""), artist=s.get("artist", ""),
            annotation_context=ctx_txt)
        session.history = [h for h in history
                           if isinstance(h, dict) and h.get("text")]
        session.history.append({"speaker": "user", "text": question})
        answer = "".join(ai_speak(settings, session, "assistant",
                                  user_prompt=question))
        return {"answer": answer}

    # ── 游戏（答案随 payload 下发，前端判题——与旧版同口径） ──

    @app.get("/api/games/quiz")
    def game_quiz() -> dict:
        from dataclasses import asdict as dc_asdict
        from .quiz import make_question
        pool = {
            s["title"]: (s["artist"],
                         [ln.text for ln in
                          _load_song_data(s["dir"])["timed_lines"]])
            for s in _songs()
            if (Path(s["dir"]) / "lyrics.lrc").exists()
        }
        q = make_question(pool)
        if q is None:
            raise HTTPException(409, "歌曲列表至少需要 2 首歌才能出题")
        return dc_asdict(q)

    @app.get("/api/games/title-puzzle")
    def game_title_puzzle() -> dict:
        from dataclasses import asdict as dc_asdict
        from .quiz import make_title_puzzle
        q = make_title_puzzle([(s["title"], s["artist"]) for s in _songs()])
        if q is None:
            raise HTTPException(409, "曲库里可拼的歌名不足（至少 2 首可挖）")
        return dc_asdict(q)

    # ── 曲库管理（内置曲库 / 手动添加 / 删除） ────────────────

    @app.get("/api/catalog")
    def get_catalog(q: str = "") -> list[dict]:
        from .songdata import _load_catalog
        have = {(s["title"], s["artist"]) for s in _songs()}
        ql = (q or "").strip().lower()
        out = []
        cat_keys = set()
        for c in _load_catalog():
            cat_keys.add((c["title"], c["artist"]))
            if ql and not (ql in c["title"].lower()
                           or ql in c["artist"].lower()
                           or ql in c.get("album", "").lower()):
                continue
            out.append({"title": c["title"], "artist": c["artist"],
                        "album": c.get("album", ""),
                        "in_library": (c["title"], c["artist"]) in have})
        # 曲库里有但内置目录没有的歌（手动添加）也可被搜到，标已在列表
        for s in _songs():
            key = (s["title"], s["artist"])
            if key in cat_keys:
                continue
            if ql and ql not in f"{key[0]} — {key[1]}".lower():
                continue
            out.append({"title": key[0], "artist": key[1],
                        "album": s.get("album", ""), "in_library": True})
        return out

    @app.post("/api/songs/from-catalog")
    def add_from_catalog(labels: list[str] = Body(..., embed=True)) -> dict:
        import re as _re
        import time as _time
        from .songdata import _load_catalog
        catalog = _load_catalog()
        added, existed, missing = [], [], []
        for label in labels or []:
            entry = next((c for c in catalog
                          if f"{c['title']} — {c['artist']}" == label), None)
            if not entry:
                missing.append(label)
                continue
            slug = _re.sub(r"[^\w]+", "_", entry["title"].lower()) \
                .strip("_") or f"song_{int(_time.time())}"
            d = Path(load_settings().songs_dir) / slug
            if d.exists():
                try:
                    have = json.loads((d / "metadata.json")
                                      .read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    have = {}
                if (have.get("title") == entry["title"]
                        and have.get("artist") == entry["artist"]):
                    existed.append(entry["title"])
                    continue
                slug += "_" + (_re.sub(r"[^\w]+", "_",
                                       entry["artist"].lower()).strip("_")
                               or "x")
                d = Path(load_settings().songs_dir) / slug
                if d.exists():
                    existed.append(entry["title"])
                    continue
            d.mkdir(parents=True)
            (d / "lyrics.lrc").write_text(entry["lrc"], encoding="utf-8")
            (d / "metadata.json").write_text(json.dumps({
                "title": entry["title"], "artist": entry["artist"],
                "album": entry.get("album", ""), "year": 0,
                "era": entry.get("era", ""), "themes": [],
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            added.append(entry["title"])
        if added:
            _kick_corpus_rebuild()
        return {"added": added, "existed": existed, "missing": missing}

    @app.post("/api/songs")
    async def add_song(title: str = Body(...), artist: str = Body(""),
                       album: str = Body(""),
                       lrc_text: str = Body("")) -> dict:
        import re as _re
        import time as _time
        from .lrc_parser import parse_lrc
        from .songdata import _PLACEHOLDER_LRC, _fetch_lrc_from_lrclib
        title = (title or "").strip()
        if not title:
            raise HTTPException(422, "请填写歌曲标题（唯一必填项）")
        slug = _re.sub(r"[^\w]+", "_", title.lower()).strip("_") \
            or f"song_{int(_time.time())}"
        d = Path(load_settings().songs_dir) / slug
        if d.exists():
            raise HTTPException(409, f"歌曲目录已存在：{slug}，请换一个标题")
        lrc_content = (lrc_text or "").strip()
        if lrc_content:
            _, timed = parse_lrc(lrc_content)
            if not timed:
                raise HTTPException(
                    422, "未能解析出带时间戳的歌词行，请检查格式"
                         "（如 [00:12.34] 歌词内容）；暂无歌词可留空")
            lrc_note = f"{len(timed)} 行歌词"
        else:
            fetched = _fetch_lrc_from_lrclib(title, (artist or "").strip())
            if fetched:
                lrc_content = fetched
                _, timed = parse_lrc(lrc_content)
                lrc_note = f"已自动从 LRCLIB 获取 {len(timed)} 行歌词"
            else:
                lrc_content = _PLACEHOLDER_LRC
                lrc_note = "LRCLIB 未找到歌词，已创建占位歌词"
        d.mkdir(parents=True)
        (d / "lyrics.lrc").write_text(lrc_content, encoding="utf-8")
        (d / "metadata.json").write_text(json.dumps({
            "title": title, "artist": (artist or "").strip() or "未知歌手",
            "album": (album or "").strip(), "year": 0, "era": "",
            "themes": [],
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        _kick_corpus_rebuild()
        return {"id": slug, "note": lrc_note}

    @app.delete("/api/songs/{song_id}")
    def delete_song(song_id: str) -> dict:
        import shutil
        from .songdata import _SONG_DATA_CACHE
        s = _find_song(song_id)
        try:
            shutil.rmtree(s["dir"])
        except Exception as exc:
            raise HTTPException(409, f"删除失败（文件可能被占用）："
                                     f"{str(exc)[:120]}")
        _SONG_DATA_CACHE.pop(s["dir"], None)
        _kick_corpus_rebuild()
        return {"deleted": song_id}

    # ── 设置（API 密钥 / 用量 / Embedding 重建） ──────────────

    @app.get("/api/settings")
    def get_settings() -> dict:
        s = load_settings()
        return {"llm_provider": s.llm_provider, "has_key": bool(s.api_key),
                "llm_base_url": s.llm_base_url, "model_name": s.model_name,
                "embedding_model": s.embedding_model}

    @app.put("/api/settings")
    def put_settings(provider: str = Body(...), key: str = Body(...),
                     base: str = Body(""), model: str = Body("")) -> dict:
        from .config import default_model_for, save_user_settings
        key = (key or "").strip()
        if not key:
            raise HTTPException(422, "请填写 API Key")
        model = (model or "").strip() or default_model_for(provider)
        save_user_settings({
            "api_key": key, "llm_provider": provider,
            "llm_base_url": (base or "").strip(), "model_name": model,
        })
        return {"model_name": model}

    @app.get("/api/usage")
    def get_usage() -> dict:
        from .llm import load_usage
        return load_usage()

    @app.get("/api/rebuild-index")
    def rebuild_status() -> dict:
        return dict(_REBUILD_STATE)

    @app.post("/api/rebuild-index")
    def rebuild_index(model: str = Body("", embed=True)) -> dict:
        model = (model or "").strip() or load_settings().embedding_model
        if _REBUILD_STATE.get("status") == "running":
            return {"status": "running"}
        _REBUILD_STATE.update(status="running", msg="1/2 正在重建语料库…")
        threading.Thread(target=_rebuild_index_bg, args=(model,),
                         daemon=True).start()
        return {"status": "running"}

    @app.get("/api/dict/{word}")
    def dict_lookup(word: str) -> dict:
        hit = dictionary.lookup(word)
        if not hit:
            raise HTTPException(status_code=404, detail=f"not found: {word}")
        return hit

    # ── 弹卡 ✨AI 语境解释（v3 三行模板，落盘缓存命中零调用） ──

    _AI_CACHE_PATH = Path(load_settings().songs_dir).parent \
        / "dict" / "ai_cache.json"

    def _ai_cache() -> dict:
        try:
            return json.loads(_AI_CACHE_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _ai_key(word: str, line: str) -> str:
        import hashlib
        # v3: strict three-line template with a few-shot example
        return hashlib.md5(f"v3:{word}\x00{line}".encode()).hexdigest()

    @app.get("/api/dict-ai")
    def dict_ai_cached(word: str, line: str = "") -> dict:
        return {"ai": _ai_cache().get(_ai_key(word.strip(), line), "")}

    @app.post("/api/dict-ai")
    def dict_ai(word: str = Body(...), line: str = Body(""),
                song: str = Body("")) -> dict:
        word = (word or "").strip()
        if not word:
            raise HTTPException(422, "word 不能为空")
        key = _ai_key(word, line)
        cache = _ai_cache()
        if key in cache:
            return {"ai": cache[key]}
        settings = load_settings()
        if not settings.api_key:
            raise HTTPException(400, "AI 语境解释需要配置 API Key（设置页）")
        from .llm import LLMClient
        resp = LLMClient(settings).generate(
            system_prompt=(
                "你是英语歌词阅读助手。用户双击了歌词里的一个单词。"
                "用简体中文回答，不超过 120 字。严格按下面模板输出"
                "三行，不得增删行、加标题、加 markdown 或任何"
                "模板外内容：\n"
                "①语境义：<这个词在这句歌词里的含义>\n"
                "②整句：<这句歌词的通顺翻译>\n"
                "③用法：<常见用法/搭配>。例：<简短英文例句> "
                "<例句中文翻译>\n"
                "示例（单词 resist，歌词句 'Cause I can't "
                "resist it no more）：\n"
                "①语境义：再也忍不住、无法克制（想挣脱的冲动）\n"
                "②整句：因为我再也忍不住了\n"
                "③用法：can't resist (doing) sth 忍不住做某事。"
                "例：I can't resist checking my phone. "
                "我忍不住看手机。"),
            user_message=(f"单词：{word}\n"
                          f"歌词句：{line}\n出自：《{song}》"),
        )
        text = (resp.reply_text or "").strip()
        cache[key] = text
        _AI_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _AI_CACHE_PATH.write_text(
            json.dumps(cache, ensure_ascii=False, indent=2),
            encoding="utf-8")
        return {"ai": text}

    # 生产形态：Vite build 产物由同一进程托管（部署体验与 serve 一致）。
    # SPA 路由（/words 等）回退到 index.html。
    if _FRONTEND_DIST.exists():
        app.mount("/assets",
                  StaticFiles(directory=_FRONTEND_DIST / "assets"),
                  name="spa-assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            file = _FRONTEND_DIST / path
            if path and file.is_file():
                return FileResponse(file)
            return FileResponse(_FRONTEND_DIST / "index.html")
    return app
