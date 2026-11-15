"""Checks of form on article prose — ADR 0005.

`ask.validate` shows that every claim points at a passage that was supplied.
These checks are about how the prose reads, and they apply in the article path
only. Each is plain pattern matching on the model's text; none calls a model.
A failure blocks the section, with its reason shown and recorded (hard rule 9).

The prompts these checks enforce are versioned files under `prompts/`, hashed
into every article record.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

PROMPTS = Path(__file__).resolve().parent.parent / "prompts"
SECTION_PROMPT = "article_section_v1.md"

_HANDLE = r"\[E\d+\]"
_HANDLES = rf"{_HANDLE}(?:\s*(?:,|and|&)?\s*{_HANDLE})*"
# Verbs of saying. A handle directly before one is standing where a noun should.
_REPORTING = (
    "states?|notes?|describes?|argues?|says?|shows?|explains?|claims?|suggests?|observes?|writes?|"
    "reports?|indicates?|mentions?|discusses?|presents?|defines?|adds?|emphasi[sz]es?|highlights?|"
    "identifies|points|addresses|refers|outlines?|clarifies|maintains?|asserts?|concludes?|stresses"
)
_BEFORE_VERB = re.compile(rf"{_HANDLES}\s+(?:(?:also|further|then|thus|only|clearly)\s+)?(?:{_REPORTING})\b", re.IGNORECASE)
_AS_NOUN = re.compile(rf"\b(?:according to|as|per|see|in|from|by)\s+{_HANDLE}", re.IGNORECASE)
# A marker that opens a sentence and runs on in lower case is its subject. One that
# trails the full stop before a new, capitalised sentence is only placed late.
_AT_START = re.compile(rf"(?:^|(?<=[.!?])\s+|\n)[\"'“‘(]*{_HANDLES}\s+[a-z]\w*")
_SENTENCE = re.compile(r".+?(?:[.!?][\"'’”)]*(?:\s?\[E\d+\])*(?=\s|$)|$)", re.DOTALL)


def load_prompt(name: str) -> tuple[str, str]:
    """A prompt file's text and the first 12 hex digits of its SHA-256."""
    text = (PROMPTS / name).read_text(encoding="utf-8")
    return text, hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def sentences(text: str) -> list[str]:
    return [m.group(0).strip() for line in text.split("\n") for m in _SENTENCE.finditer(line) if m.group(0).strip()]


def _texts(result: dict) -> list[str]:
    return [result.get("answer") or "", *result.get("limitations", []), *result.get("ai_interpretation", [])]


def handle_as_subject(text: str) -> list[str]:
    """Places where a note marker stands as a word of the sentence."""
    spans: list[tuple[int, int]] = []
    for pattern in (_AT_START, _BEFORE_VERB, _AS_NOUN):
        for match in pattern.finditer(text):
            if not any(start <= match.start() < end or match.start() <= start < match.end() for start, end in spans):
                spans.append((match.start(), match.end()))
    return [" ".join(text[start:end].split()) for start, end in sorted(spans)]


def prose_failures(result: dict) -> list[str]:
    """Why this payload may not be printed in an article, as recorded reasons."""
    failures = []
    subjects = [hit for text in _texts(result) for hit in handle_as_subject(text)]
    if subjects:
        shown = "; ".join(f"“{hit}”" for hit in subjects[:3])
        failures.append(f"handle_used_as_subject: a note marker stands where a noun should ({shown})")
    return failures
