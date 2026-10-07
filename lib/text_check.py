"""Verify text an image model drew, with a real OCR engine.

Image models draw letters; they do not type them. A headline usually comes out
right, but long lines, technical terms and numbers swap characters ("T2" ->
"T7", "June" -> "Jume"). Gemini cannot proofread its own image either: when it
reads an image it quietly auto-corrects, hiding exactly the typo we look for.
So the check runs a local OCR engine (RapidOCR, offline once installed):

    pip install rapidocr-onnxruntime

`verify(path, expected)` compares every planned text item to what the OCR read:
  - strict items (any digit, %, $, /, & — deadlines, rates, form codes like
    "T2" or "GST/HST") must appear character for character;
  - plain words must match exactly too, after folding only the classic OCR
    look-alikes (l/i/1/|, 0/o, rn/m): a real model typo ("projct") still fails,
    while the OCR's own slip on a stylised "i" does not;
  - OCR text that matches no planned item and contains a digit fails the image:
    a stray number on a tax firm's visual is the worst possible typo.

A failing image is never worse than a refusal: the caller fixes it or falls
back to typeset text (`lib.text_card`), where every character is exact.
"""
from __future__ import annotations
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any, Sequence

_STRICT = re.compile(r"[0-9%$/&]")
_ENGINE = None


def _engine():
    global _ENGINE
    if _ENGINE is None:
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError as e:
            raise ImportError(
                "Text check needs a local OCR engine: pip install rapidocr-onnxruntime"
            ) from e
        _ENGINE = RapidOCR()
    return _ENGINE


def available() -> bool:
    try:
        _engine()
        return True
    except ImportError:
        return False


def ocr_lines(path: str) -> list[str]:
    """Text lines read from the image, top to bottom."""
    result, _ = _engine()(path)
    rows = sorted(result or [], key=lambda r: (round(r[0][0][1] / 12), r[0][0][0]))
    return [r[1] for r in rows]


def _norm(s: str, keep_symbols: bool) -> str:
    s = unicodedata.normalize("NFKC", s).casefold()
    s = s.translate(str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"',
                                   "–": "-", "—": "-"}))
    s = re.sub(r"\s+", "", s)
    if not keep_symbols:
        s = re.sub(r"[^0-9a-z]", "", s)
    return s


#: Characters OCR engines confuse with each other. Folded on both sides before
#: comparing plain words, so only a genuine misspelling survives.
_LOOKALIKES = str.maketrans({"l": "i", "1": "i", "|": "i", "!": "i", "0": "o"})


def _fold(s: str) -> str:
    return s.replace("rn", "m").translate(_LOOKALIKES)


def _best_similarity(needle: str, hay: str) -> float:
    if not needle:
        return 1.0
    if needle in hay:
        return 1.0
    n, best = len(needle), 0.0
    for i in range(0, max(1, len(hay) - n + 1)):
        best = max(best, SequenceMatcher(None, needle, hay[i:i + n]).ratio())
        if best >= 0.99:
            break
    return best


def verify(path: str, expected: Sequence[str], *, threshold: float = 0.9) -> dict[str, Any]:
    # `threshold` only decides which unplanned OCR lines count as "unexpected".
    """Check that every planned text item is on the image, exactly where it matters.

    Returns {"ok", "items": [{text, strict, found, similarity}], "unexpected": [...],
    "ocr": [...lines]}. `ok` is False if any item is missing or wrong, or if the
    image carries a stray number nobody planned.
    """
    lines = ocr_lines(path)
    hay_strict = _norm(" ".join(lines), keep_symbols=True)
    hay_loose = _norm(" ".join(lines), keep_symbols=False)
    items = []
    for text in expected:
        strict = bool(_STRICT.search(text))
        if strict:
            found = _norm(text, keep_symbols=True) in hay_strict
            sim = 1.0 if found else _best_similarity(_norm(text, True), hay_strict)
        else:
            found = _fold(_norm(text, False)) in _fold(hay_loose)
            sim = 1.0 if found else _best_similarity(_norm(text, False), hay_loose)
        items.append({"text": text, "strict": strict, "found": found, "similarity": round(sim, 3)})

    planned = _norm(" ".join(expected), keep_symbols=False)
    unexpected = []
    for ln in lines:
        key = _norm(ln, keep_symbols=False)
        if len(key) >= 2 and key not in planned and _best_similarity(key, planned) < threshold:
            unexpected.append(ln)
    stray_numbers = [u for u in unexpected if re.search(r"\d", u)]
    ok = all(i["found"] for i in items) and not stray_numbers
    return {"ok": ok, "items": items, "unexpected": unexpected,
            "stray_numbers": stray_numbers, "ocr": lines}


def fix_instruction(report: dict[str, Any]) -> str:
    """A targeted edit prompt for the items that failed (multi-turn fix)."""
    wrong = [i["text"] for i in report["items"] if not i["found"]]
    parts = []
    if wrong:
        quoted = "; ".join(f'"{t}"' for t in wrong)
        parts.append(f"Correct the spelling of these text elements so each reads exactly: {quoted}.")
    if report.get("stray_numbers"):
        parts.append("Remove any other numbers or stray characters that are not part of the planned text.")
    parts.append("Keep everything else in the image exactly the same: layout, colours, illustration and all other text.")
    return " ".join(parts)
