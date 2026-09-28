"""Shazam-style audio fingerprinting over the local library (听歌识曲).

Constellation-map approach: STFT → local spectral peaks → hash pairs of
peaks (f1, f2, Δt). Matching counts hash hits with a consistent time
offset. Pure numpy/scipy on PCM data.

Decoding: WAV via scipy; everything else (mp3/m4a/…) via pydub, which
needs ffmpeg on PATH — songs that cannot be decoded are skipped and
reported, the rest of the library still matches.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

TARGET_SR = 11025          # mono downsample rate for fingerprinting
PEAK_NEIGHBORHOOD = 12     # local-max footprint (freq bins x frames)
FAN_OUT = 12               # pairs generated per anchor peak
MIN_HASH_HITS = 12         # matches below this are noise
MIN_OFFSET_SHARE = 0.25    # top offset bin must hold this share of hits


def _decode(path: str | Path) -> tuple[int, np.ndarray] | None:
    """(sample_rate, mono float32) or None when the file can't be decoded."""
    path = Path(path)
    try:
        if path.suffix.lower() == ".wav":
            from scipy.io import wavfile
            sr, data = wavfile.read(str(path))
            data = data.astype(np.float32)
            if data.ndim > 1:
                data = data.mean(axis=1)
            peak = np.abs(data).max() or 1.0
            return sr, data / peak
        from pydub import AudioSegment  # needs ffmpeg for mp3/m4a
        seg = AudioSegment.from_file(str(path))
        seg = seg.set_channels(1)
        data = np.array(seg.get_array_of_samples(), dtype=np.float32)
        peak = np.abs(data).max() or 1.0
        return seg.frame_rate, data / peak
    except Exception as exc:
        logger.warning("decode failed for %s: %s", path, exc)
        return None


def _resample(sr: int, data: np.ndarray) -> np.ndarray:
    if sr == TARGET_SR:
        return data
    from scipy.signal import resample_poly
    from math import gcd
    g = gcd(sr, TARGET_SR)
    return resample_poly(data, TARGET_SR // g, sr // g).astype(np.float32)


def _peaks(data: np.ndarray) -> list[tuple[int, int]]:
    """(freq_bin, frame) spectral peaks of a mono TARGET_SR signal."""
    from scipy.ndimage import maximum_filter
    from scipy.signal import stft
    _f, _t, z = stft(data, fs=TARGET_SR, nperseg=1024, noverlap=512)
    mag = np.abs(z)
    if mag.size == 0:
        return []
    local_max = maximum_filter(mag, size=PEAK_NEIGHBORHOOD) == mag
    threshold = np.percentile(mag, 97)
    fs, ts = np.nonzero(local_max & (mag >= threshold))
    order = np.argsort(ts)
    return list(zip(fs[order].tolist(), ts[order].tolist()))


def _hashes(peaks: list[tuple[int, int]]):
    """Yield (hash, anchor_frame) for peak pairs inside the target zone."""
    for i, (f1, t1) in enumerate(peaks):
        for f2, t2 in peaks[i + 1: i + 1 + FAN_OUT]:
            dt = t2 - t1
            if 0 < dt <= 200:
                yield (int(f1) << 20) | (int(f2) << 8) | int(dt), t1


@dataclass
class FingerprintIndex:
    table: dict[int, list[tuple[str, int]]] = field(default_factory=dict)
    indexed: list[str] = field(default_factory=list)   # song titles
    skipped: list[str] = field(default_factory=list)   # undecodable songs


def build_index(songs: list[dict]) -> FingerprintIndex:
    """Fingerprint every library song that has decodable audio."""
    index = FingerprintIndex()
    for s in songs:
        src = s.get("audio_src")
        if s.get("audio_type") != "local" or not src:
            continue
        decoded = _decode(src)
        if decoded is None:
            index.skipped.append(s["title"])
            continue
        data = _resample(*decoded)
        n = 0
        for h, t in _hashes(_peaks(data)):
            index.table.setdefault(h, []).append((s["title"], t))
            n += 1
        if n:
            index.indexed.append(s["title"])
        else:
            index.skipped.append(s["title"])
    return index


def match_sample(index: FingerprintIndex, sr: int,
                 data: np.ndarray) -> tuple[str, float, float] | None:
    """(song_title, offset_seconds, confidence 0-1) or None."""
    if not index.table:
        return None
    data = np.asarray(data, dtype=np.float32)
    if data.ndim > 1:
        data = data.mean(axis=1)
    peak = np.abs(data).max() or 1.0
    data = _resample(sr, data / peak)

    votes: dict[tuple[str, int], int] = {}
    total = 0
    for h, t_sample in _hashes(_peaks(data)):
        for title, t_song in index.table.get(h, ()):
            key = (title, t_song - t_sample)
            votes[key] = votes.get(key, 0) + 1
            total += 1
    if not votes:
        return None
    (title, offset_frames), hits = max(votes.items(), key=lambda kv: kv[1])
    # a real match concentrates its hash hits at ONE time offset; scattered
    # hits across many offsets are coincidence
    title_total = sum(v for (t, _o), v in votes.items() if t == title)
    if hits < MIN_HASH_HITS or hits < MIN_OFFSET_SHARE * title_total:
        return None
    # STFT hop = 512 samples at TARGET_SR
    offset_s = max(0.0, offset_frames * 512 / TARGET_SR)
    confidence = min(1.0, hits / 50.0)
    return title, offset_s, confidence
