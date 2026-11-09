"""Text normalisation and word/character error rates for Indian-language ASR.

Before scoring: Unicode NFC, drop invisible joiners and the Devanagari nukta, lowercase,
punctuation (incl. the danda ।) -> space, Devanagari/Kannada digits -> ASCII.

CER matters for Kannada: it is agglutinative, so one wrong suffix makes a whole word wrong
and WER overstates the damage. Report both.

Known bias: references are the exact text Timbre was asked to speak. If Prisma writes a
number as words where the reference has digits (or English words in native script), WER
counts it as an error even when a human would not. Task success, not WER, is the headline.
"""

from __future__ import annotations

import unicodedata

_TRANSLATE = {0x200C: None, 0x200D: None, 0x093C: None, 0x0901: 0x0902}


def normalize(text: str) -> str:
    t = unicodedata.normalize("NFC", text or "").translate(_TRANSLATE).lower()
    out = []
    for ch in t:
        cat = unicodedata.category(ch)
        if ch.isdigit():
            out.append(str(unicodedata.digit(ch)))
        elif cat.startswith("P") or cat.startswith("S"):
            out.append(" ")
        else:
            out.append(ch)
    return " ".join("".join(out).split())


def _edit_distance(a: list, b: list) -> int:
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, y in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y))
        prev = cur
    return prev[-1]


def wer(ref: str, hyp: str) -> float:
    r, h = normalize(ref).split(), normalize(hyp).split()
    if not r:
        return 0.0 if not h else 1.0
    return _edit_distance(r, h) / len(r)


def cer(ref: str, hyp: str) -> float:
    r, h = list(normalize(ref).replace(" ", "")), list(normalize(hyp).replace(" ", ""))
    if not r:
        return 0.0 if not h else 1.0
    return _edit_distance(r, h) / len(r)


def same_script(a: str, b: str) -> bool:
    """Rough check that two strings are mostly in the same script (else WER is meaningless)."""
    def script(s: str) -> str:
        for ch in s:
            if ch.isalpha():
                name = unicodedata.name(ch, "")
                return name.split()[0]
        return ""
    return script(a) == script(b)
