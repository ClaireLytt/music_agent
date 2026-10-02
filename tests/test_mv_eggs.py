"""Tests for the MV easter-egg module (no LLM, no gradio)."""

from lyric_agent.mv_eggs import (
    MvEggs,
    load_mv,
    mv_messages,
    parse_mv,
    render_mv_html,
    save_mv,
    search_links,
)


def test_messages_contain_song_meta():
    system, user = mv_messages("cardigan", "Taylor Swift", "folklore", 2020)
    assert "《cardigan》" in user and "Taylor Swift" in user
    assert "folklore" in user and "2020" in user
    assert "known" in user  # schema reaches the prompt
    assert "编造" in system  # anti-hallucination clause


def test_parse_tolerant():
    assert parse_mv("not a dict").eggs == []
    assert parse_mv({"eggs": "nope"}).eggs == []
    m = parse_mv({
        "known": True, "director": " X ",
        "eggs": [{"detail": "piano turns gold", "lyric_link": "gold rush",
                  "moment": "副歌"},
                 {"detail": "bad ts", "moment": "大概中间某处"},
                 {"detail": ""}, 42, {"lyric_link": "no detail"}],
        "caveat": "maybe",
    })
    assert m.known and m.director == "X"
    # 3-tuples; moments outside the enum are dropped (anti-fabrication)
    assert m.eggs == [("piano turns gold", "gold rush", "副歌"),
                      ("bad ts", "", "")]
    assert m.caveat == "maybe"


def test_render_known_and_unknown():
    html_known = render_mv_html(
        MvEggs(known=True, director="D",
               eggs=[("a <b> detail", "some & lyric")]),
        "cardigan", "Taylor Swift")
    assert "a &lt;b&gt; detail" in html_known  # escaped
    assert "some &amp; lyric" in html_known
    # timestamp chip renders for 3-tuple eggs (old 2-tuple caches still work)
    html_ts = render_mv_html(
        MvEggs(known=True, eggs=[("egg", "", "副歌")]), "x", "y")
    assert "🎞️ 副歌" in html_ts
    assert "search.bilibili.com" in html_known
    assert "youtube.com/results" in html_known
    # unknown MV -> honest guard, no invented eggs
    html_unknown = render_mv_html(MvEggs(known=False), "x", "y")
    assert "mv-egg" not in html_unknown
    assert "没有可靠了解" in html_unknown
    assert "search.bilibili.com" in html_unknown


def test_search_links_quoted():
    links = search_links("晴天", "周杰伦")
    assert " " not in links.split('href="')[1].split('"')[0]  # URL-encoded


def test_save_load_roundtrip(tmp_path):
    assert load_mv(tmp_path) is None
    save_mv(tmp_path, {"known": True, "eggs": []})
    assert load_mv(tmp_path) == {"known": True, "eggs": []}
