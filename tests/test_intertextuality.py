"""Tests for echo detection (find_song_echoes) and the 彩蛋地图 graph."""

from __future__ import annotations

import numpy as np
import pytest

from lyric_agent.intertextuality import search as search_mod
from lyric_agent.intertextuality.corpus import CorpusLine
from lyric_agent.intertextuality.echo_map import (
    base_title,
    build_echo_graph,
    is_filler,
    render_echo_map_html,
)
from lyric_agent.intertextuality.search import (
    artist_matches,
    cjk_pair_anchored,
    find_song_echoes,
    is_cjk_text,
)

# orthogonal basis: lines assigned the same vector are "similar", others not
_DIM = 8


def _vec(k: int) -> np.ndarray:
    v = np.zeros(_DIM)
    v[k] = 1.0
    return v


def _blend(a: int, b: int, w: float) -> np.ndarray:
    """Vector with cosine ~w against _vec(a)."""
    v = w * _vec(a) + np.sqrt(1 - w * w) * _vec(b)
    return v


class _FakeModel:
    """Encodes known texts to fixed vectors — no sentence-transformers needed."""

    def __init__(self, table: dict[str, np.ndarray]):
        self.table = table

    def encode(self, texts, **_kw):
        return np.stack([self.table[t] for t in texts])


def _corpus(entries):
    return [
        CorpusLine(song=s, album=al, line_index=i, text=t, artist=ar)
        for i, (s, al, t, ar) in enumerate(entries)
    ]


@pytest.fixture
def echo_setup(monkeypatch):
    corpus = _corpus([
        ("Song A", "Album 1", "the scarf in your drawer", "Artist X"),
        ("Song B", "Album 1", "you kept my old scarf", "Artist X"),
        ("Other", "Album 2", "completely unrelated line", "Artist Y"),
    ])
    embeddings = np.stack([
        _vec(0),            # Song A: scarf line
        _blend(0, 1, 0.8),  # Song B: ~0.8 similar to Song A's line
        _vec(2),            # Other artist
    ])
    table = {
        "the scarf in your drawer": _vec(0),
        "nothing like the corpus": _vec(5),
    }
    monkeypatch.setattr(search_mod, "get_model", lambda *a, **k: _FakeModel(table))
    return embeddings, corpus


def test_find_song_echoes_basic(echo_setup):
    embeddings, corpus = echo_setup
    echoes = find_song_echoes(
        ["the scarf in your drawer", "nothing like the corpus"],
        embeddings, corpus,
        exclude_song="Song A", min_similarity=0.6, artist="Artist X",
    )
    assert echoes[0] is not None
    assert echoes[0].song == "Song B"          # Song A excluded, Y filtered
    assert echoes[0].similarity == pytest.approx(0.8, abs=0.01)
    assert echoes[1] is None                   # below threshold


def test_find_song_echoes_artist_filter(echo_setup):
    embeddings, corpus = echo_setup
    echoes = find_song_echoes(
        ["the scarf in your drawer"], embeddings, corpus,
        min_similarity=0.6, artist="Artist Z",
    )
    assert echoes == [None]


def test_find_song_echoes_degenerate_pair(monkeypatch):
    # two different texts on identical vectors = encoder collapse, not an echo
    corpus = _corpus([("Song B", "", "另一句完全不同的歌词", "X")])
    embeddings = np.stack([_vec(0)])
    table = {"这句中文歌词": _vec(0)}
    monkeypatch.setattr(search_mod, "get_model",
                        lambda *a, **k: _FakeModel(table))
    echoes = find_song_echoes(
        ["这句中文歌词"], embeddings, corpus, min_similarity=0.5,
        min_similarity_cjk=0.8)
    assert echoes == [None]


def test_is_cjk_text():
    assert is_cjk_text("消失的下雨天 我好想再淋一遍")
    assert not is_cjk_text("plain english line")
    assert not is_cjk_text("")


def test_cjk_pair_anchored():
    assert cjk_pair_anchored("童年的盪鞦韆隨記憶晃到現在", "童年的紙飛機")
    assert not cjk_pair_anchored("怎麼會怎麼會", "誰在偷笑呢")


def test_artist_matches_feat():
    assert artist_matches("Taylor Swift", "Taylor Swift ft. Bon Iver")
    assert not artist_matches("Taylor Swift", "Ed Sheeran")


def test_is_filler():
    assert is_filler("(Oh, oh, oh-oh, oh)")
    assert is_filler("la la la yeah")
    assert not is_filler("Think I know it's with me")
    assert not is_filler("消失的下雨天")
    assert not is_filler("")


def test_base_title_strips_version_suffix():
    assert base_title("All Too Well (10 Minute Version)") == "all too well"
    assert base_title("晴天（Live）") == "晴天"


def _graph_fixture():
    """3 songs by X: A echoes B (2 line pairs), C is isolated; D is a
    duplicate recording of A under another title."""
    corpus = _corpus([
        ("A", "al1", "we dance in the storm", "X"),
        ("A", "al1", "golden light on your face", "X"),
        ("B", "al1", "dancing through the storm again", "X"),
        ("B", "al1", "golden hour in your eyes", "X"),
        ("C", "al2", "totally different topic", "X"),
        ("D", "al3", "we dance in the storm", "X"),
        ("D", "al3", "golden light on your face", "X"),
    ])
    embeddings = np.stack([
        _vec(0), _vec(1),
        _blend(0, 3, 0.8), _blend(1, 3, 0.75),
        _vec(2),
        _vec(0), _vec(1),   # D duplicates A's vectors AND texts
    ])
    return embeddings, corpus


def test_build_echo_graph_edges_and_duplicate_guard():
    embeddings, corpus = _graph_fixture()
    g = build_echo_graph(embeddings, corpus, "X", min_similarity=0.7,
                         library_titles={"A"})
    pairs = {(e.song_a, e.song_b) for e in g.edges}
    assert ("A", "B") in pairs
    # D is a duplicate recording of A (100% identical lines) — no edge
    assert not any("D" in p and "A" in p for p in pairs)
    ab = next(e for e in g.edges if (e.song_a, e.song_b) == ("A", "B"))
    assert ab.count == 2
    assert ab.example.similarity == pytest.approx(0.8, abs=0.01)
    node_a = next(n for n in g.nodes if n.song == "A")
    assert node_a.in_library
    assert all(n.song != "C" for n in g.nodes)  # isolated song not drawn


def test_build_echo_graph_no_songs():
    g = build_echo_graph(np.zeros((0, _DIM)), [], "X")
    assert g.song_total == 0 and not g.edges
    assert "不足 2 首" in render_echo_map_html(g)


def test_render_echo_map_html_smoke():
    embeddings, corpus = _graph_fixture()
    g = build_echo_graph(embeddings, corpus, "X", min_similarity=0.7)
    out = render_echo_map_html(g)
    assert "<svg" in out and "egg-edge" in out
    assert "呼应最强的歌曲对" in out


def test_build_echo_graph_cross_artist():
    corpus = _corpus([
        ("A", "al1", "we dance in the storm", "Artist X"),
        ("B", "al1", "dancing through the storm again", "Artist X"),
        ("C", "al2", "storm dancing once more", "Artist Y"),
    ])
    embeddings = np.stack([_vec(0), _blend(0, 3, 0.8), _blend(0, 4, 0.85)])
    g = build_echo_graph(embeddings, corpus, None, min_similarity=0.7)
    assert g.cross_artist
    pairs = {(e.song_a, e.song_b) for e in g.edges}
    # cross-artist mode: X↔Y pair kept, X's own A↔B pair excluded
    assert ("A · Artist X", "C · Artist Y") in pairs
    assert not any("A · Artist X" in p and "B · Artist X" in p for p in pairs)


def test_trace_imagery_keyword_and_semantic(monkeypatch):
    from lyric_agent.intertextuality.search import trace_imagery
    corpus = _corpus([
        ("A", "al1", "the storm keeps raging", "X"),
        ("B", "al2", "wind and thunder tonight", "X"),
        ("C", "al3", "nothing related at all", "X"),
    ])
    embeddings = np.stack([_vec(0), _blend(0, 1, 0.7), _vec(2)])
    table = {"storm": _vec(0)}
    monkeypatch.setattr(search_mod, "get_model",
                        lambda *a, **k: _FakeModel(table))
    hits = trace_imagery("storm", embeddings, corpus, min_similarity=0.5)
    songs = [h.song for h in hits]
    assert songs[0] == "A" and hits[0].keyword          # literal match first
    assert "B" in songs                                  # semantic neighbour
    assert "C" not in songs


def test_doctor_duplicate_and_freshness(tmp_path):
    from lyric_agent.doctor import (
        check_corpus_duplicates, check_corpus_freshness, check_library)
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    lines = [f"line number {i}" for i in range(10)]
    (corpus_dir / "discography.jsonl").write_text(
        "\n".join([
            '{"title": "A", "artist": "X", "album": "", "lyrics_lines": %s}'
            % str(lines).replace("'", '"'),
            '{"title": "A2", "artist": "X", "album": "", "lyrics_lines": %s}'
            % str(lines).replace("'", '"'),
        ]), encoding="utf-8")
    dups = check_corpus_duplicates(corpus_dir)
    assert len(dups) == 1 and dups[0].severity == "error"

    songs_dir = tmp_path / "songs"
    d = songs_dir / "new_song"
    d.mkdir(parents=True)
    (d / "lyrics.lrc").write_text("[00:01.00] hello\n", encoding="utf-8")
    (d / "metadata.json").write_text(
        '{"title": "Brand New", "artist": "X"}', encoding="utf-8")
    fresh = check_corpus_freshness(songs_dir, corpus_dir)
    assert any("Brand New" in f.message for f in fresh)
    lib = check_library(songs_dir)
    assert any("尚无 AI 批注" in f.message for f in lib)
