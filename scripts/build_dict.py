# -*- coding: utf-8 -*-
"""Build the bundled mini dictionary from the full ECDICT csv (MIT license,
https://github.com/skywind3000/ECDICT). Keeps word/phonetic/translation for
single words that carry at least one quality signal (frequency rank, Collins
stars, Oxford 3000 flag or an exam tag) -> small enough to commit, broad
enough for song vocabulary. Also builds a lemma map limited to kept words.
"""
import csv
import gzip
import io
import os
import re
import sys

TMP = os.environ.get("TEMP", "/tmp")
SRC = os.path.join(TMP, "ecdict_full.csv")
LEM = os.path.join(TMP, "lemma.en.txt")
OUT = "data/dict/ecdict_mini.csv.gz"
OUT_LEM = "data/dict/lemma.en.txt.gz"

WORD_RE = re.compile(r"^[a-zA-Z][a-zA-Z'\-]*$")

kept = {}
total = 0
with io.open(SRC, encoding="utf-8", errors="replace", newline="") as f:
    for row in csv.DictReader(f):
        total += 1
        w = (row.get("word") or "").strip()
        tr = (row.get("translation") or "").strip()
        if not w or not tr or not WORD_RE.match(w) or len(w) > 32:
            continue
        has_signal = any([
            (row.get("bnc") or "0").strip() not in ("", "0"),
            (row.get("frq") or "0").strip() not in ("", "0"),
            (row.get("collins") or "").strip() not in ("", "0"),
            (row.get("oxford") or "").strip() not in ("", "0"),
            (row.get("tag") or "").strip(),
        ])
        if not has_signal:
            continue
        kept[w.lower()] = (w, (row.get("phonetic") or "").strip(), tr)

with gzip.open(OUT, "wt", encoding="utf-8", newline="") as gz:
    wr = csv.writer(gz)
    wr.writerow(["word", "phonetic", "translation"])
    for key in sorted(kept):
        wr.writerow(kept[key])

# lemma.en.txt lines look like:  "abandon/262 -> abandoned,abandoning,abandons"
n_lem = 0
with io.open(LEM, encoding="utf-8", errors="replace") as f, \
        gzip.open(OUT_LEM, "wt", encoding="utf-8") as gz:
    for line in f:
        line = line.strip()
        if not line or line.startswith(";"):
            continue
        if "->" not in line:
            continue
        head, _, forms = line.partition("->")
        lemma = head.split("/")[0].strip().lower()
        if lemma not in kept:
            continue
        forms = [x.strip().lower() for x in forms.split(",") if x.strip()]
        forms = [x for x in forms if WORD_RE.match(x)]
        if forms:
            gz.write(f"{lemma}\t{','.join(forms)}\n")
            n_lem += 1

print(f"ecdict rows total={total} kept={len(kept)}")
print(f"lemma entries kept={n_lem}")
for p in (OUT, OUT_LEM):
    print(p, os.path.getsize(p), "bytes")
# sanity words a lyric reader would hit
for probe in ("crestfallen", "cardigan", "cobblestones", "hustle", "scarf"):
    print(probe, "->", kept.get(probe, ("", "", "MISS"))[2][:40])
