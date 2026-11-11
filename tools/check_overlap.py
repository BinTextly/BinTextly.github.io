#!/usr/bin/env python3
"""Report duplicate sentences between two pages.

Strips script/style/JSON-LD, keeps visible body text, splits it into sentences,
and measures how much of each page is repeated verbatim on the other one.

  python3 tools/check_overlap.py binary-to-english/index.html binary-code-translator/index.html
"""

import html
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

STRIP_BLOCKS = re.compile(r"<(script|style)\b.*?</\1>", re.I | re.S)
TAG = re.compile(r"<[^>]+>")
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
NOISE = re.compile(r"[^a-z0-9 ]+")


def sentences(path):
    raw = (ROOT / path).read_text(encoding="utf-8")
    raw = STRIP_BLOCKS.sub(" ", raw)
    raw = re.sub(r"<br\s*/?>", " ", raw, flags=re.I)
    text = html.unescape(TAG.sub(" ", raw))
    text = re.sub(r"\s+", " ", text).strip()
    out = []
    for s in SENTENCE_SPLIT.split(text):
        s = s.strip()
        if len(s.split()) < 4:          # skip nav labels, single words, headings-as-fragments
            continue
        out.append(s)
    return out


def norm(s):
    return re.sub(r"\s+", " ", NOISE.sub(" ", s.lower())).strip()


def main(a, b):
    sa, sb = sentences(a), sentences(b)
    na = [norm(s) for s in sa]
    nb = [norm(s) for s in sb]
    set_b = set(nb)

    exact = [s for s, n in zip(sa, na) if n in set_b]
    fuzzy = []
    for s, n in zip(sa, na):
        if n in set_b:
            continue
        for m in nb:
            if abs(len(m) - len(n)) > 40:
                continue
            if SequenceMatcher(None, n, m).ratio() >= 0.85:
                fuzzy.append((s, m))
                break

    print(f"{a}: {len(sa)} sentences")
    print(f"{b}: {len(sb)} sentences")
    print(f"identical sentences: {len(exact)}/{len(sa)} = {len(exact)/len(sa):.0%} of page A")
    print(f"near-identical (>=0.85): {len(fuzzy)} extra")
    total = len(exact) + len(fuzzy)
    print(f"combined: {total}/{len(sa)} = {total/len(sa):.0%} of page A  "
          f"-> {'PASS' if total/len(sa) <= 0.30 else 'FAIL'} (limit 30%)")
    for s in exact:
        print("  = " + s)
    for s, m in fuzzy:
        print("  ~ " + s)
        print("    " + m)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
