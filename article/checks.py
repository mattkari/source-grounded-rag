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


# ---------------------------------------------------------------------------
# Who acts — a prompt to read, never a verdict (ADR 0005, hard rule 12)
# ---------------------------------------------------------------------------

# Words that give an act or a decision to someone, grouped so that "decision" in
# the commentary is looked for as "decided" in the passage.
_ACTS = {
    "decide": r"decid\w*|decision\w*",
    "choose": r"cho(?:ose|oses|se|sen|ice|ices)|choosing",
    "endow": r"endow\w*",
    "create": r"creat(?:e|es|ed|ing|ion|or)",
    "give": r"gives?|gave|given|giving|gifts?",
    "grant": r"grant(?:s|ed|ing)?",
    "bestow": r"bestow\w*",
    "command": r"command(?:s|ed|ing|ment)?",
    "intend": r"intend(?:s|ed|ing)?|intention\w*",
    "design": r"design(?:s|ed|ing)?",
    "ordain": r"ordain\w*",
    "make": r"makes?|made|making",
    "establish": r"establish\w*",
    "impose": r"impos(?:e|es|ed|ing|ition)",
}
_ACT = "|".join(f"(?P<{name}>{pattern})" for name, pattern in _ACTS.items())
_NAME = r"(?P<agent>[A-Z][\w’'ʿʾ-]*?)"
_NOT_NAMES = {"The", "This", "That", "These", "Those", "It", "He", "She", "They", "His", "Her", "Its", "Their",
              "FIXTURE", "A", "An", "In", "On", "By", "As", "For", "And", "But"}
_POSSESSIVE = re.compile(rf"\b{_NAME}(?:’s|'s)\s+(?:\w+\s+){{0,2}}?(?:{_ACT})\b")
_SUBJECT = re.compile(rf"\b{_NAME}\s+(?:(?:also|then|thus|has|had|have)\s+)?(?:{_ACT})\b")


def agent_flags(text: str, passages: list[str]) -> list[str]:
    """Sentences that give an act to a named agent the cited passages do not show
    doing it. Raised for the researcher to read; a clean result proves nothing."""
    passage_sentences = [s for passage in passages for s in sentences(passage)]
    flags = []
    for sentence in sentences(text):
        for match in list(_POSSESSIVE.finditer(sentence)) + list(_SUBJECT.finditer(sentence)):
            agent = re.sub(r"(?:’s|'s)$", "", match.group("agent"))
            if agent in _NOT_NAMES:
                continue
            act = next(name for name in _ACTS if match.group(name))
            shown = any(
                re.search(rf"\b{re.escape(agent)}\b", s) and re.search(rf"\b(?:{_ACTS[act]})\b", s, re.IGNORECASE)
                for s in passage_sentences
            )
            flag = f"gives “{match.group(act)}” to {agent}; the cited passage does not show {agent} doing this"
            if not shown and flag not in flags:
                flags.append(flag)
    return flags
