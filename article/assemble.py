"""Assemble validated sections into one article Medium can import — PLAN_V6 §5, §6, §8.

Nothing here generates text. It takes outcomes the pipeline has already
validated and lays them out:

  * a section whose outcome failed validation, was refused as `insufficient`,
    or contains a table is **blocked** and left out, with the reason recorded;
  * evidence handles become plain `[n]` markers, numbered once across the
    article, and a Sources list is built from stored provenance (`ask.footnote`);
  * the model's own inferences, and any generated introduction, transition or
    conclusion, are **commentary** and open with a fixed label in words;
  * the article body never contains a table.

Text the researcher wrote is laid out as written and recorded as theirs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import ask

COMMENTARY_LABEL = "Commentary (the article's own reading, not the author's):"
DRAFT_LINE = "DRAFT — the notes in this article have not yet been checked by the researcher."
CLOSING_LINE = "This article was drafted with an AI system from the source named above."
CLOSING_LINE_REVIEWED = (
    "This article was drafted with an AI system from the source named above and checked by the researcher."
)
RESEARCHER, GENERATED = "researcher", "generated"
_TABLE_LINE = re.compile(r"^\s*\|.*\|\s*$", re.MULTILINE)


@dataclass
class SectionDraft:
    heading: str
    brief: str
    outcome: ask.QueryOutcome | None = None   # None when the pipeline raised
    error: str | None = None


@dataclass
class FrameElement:
    """An introduction, a transition or a conclusion, and where it came from."""
    origin: str                                # RESEARCHER | GENERATED
    text: str = ""                             # researcher-written
    brief: str = ""                            # generated: what the model was asked
    outcome: ask.QueryOutcome | None = None
    error: str | None = None


@dataclass
class Article:
    markdown: str
    notes: list[dict] = field(default_factory=list)      # {n, chunk_id, handle context}
    blocked: list[dict] = field(default_factory=list)    # {what, reason}


def block_reason(outcome: ask.QueryOutcome | None, error: str | None = None) -> str | None:
    """Why an outcome may not be printed, or None if it may."""
    if outcome is None:
        return f"the pipeline failed: {error}"
    if outcome.failures:
        return "validation failed: " + "; ".join(outcome.failures)
    result = outcome.result
    if result.get("evidence_sufficiency") == "insufficient" or result.get("answer") is None:
        return "the thesis does not hold enough evidence for this"
    texts = [result["answer"], *result.get("limitations", []), *result.get("ai_interpretation", [])]
    if any(_TABLE_LINE.search(text) for text in texts):
        return "the draft contains a table, which the article format does not allow"
    return None


class _Notes:
    """One run of note numbers across the whole article, keyed by passage."""

    def __init__(self) -> None:
        self.numbers: dict[str, int] = {}
        self.items: dict[int, ask.EvidenceItem] = {}

    def renumber(self, text: str, items: list[ask.EvidenceItem]) -> str:
        by_handle = {item.handle: item for item in items}

        def swap(match: re.Match) -> str:
            item = by_handle[f"E{match.group(1)}"]        # validation guarantees it exists
            chunk_id = item.chunk["chunk_id"]
            if chunk_id not in self.numbers:
                self.numbers[chunk_id] = len(self.numbers) + 1
                self.items[self.numbers[chunk_id]] = item
            return f"[{self.numbers[chunk_id]}]"

        return ask.MARKER_RE.sub(swap, text)


def _section_body(outcome: ask.QueryOutcome, notes: _Notes) -> list[str]:
    result = outcome.result
    paragraphs = [notes.renumber(result["answer"], outcome.items)]
    paragraphs += [notes.renumber(line, outcome.items) for line in result.get("limitations", [])]
    paragraphs += [
        f"{COMMENTARY_LABEL} {notes.renumber(line, outcome.items)}"
        for line in result.get("ai_interpretation", [])
    ]
    return paragraphs


def _frame_text(element: FrameElement | None, what: str, notes: _Notes, blocked: list[dict]) -> str | None:
    if element is None:
        return None
    if element.origin == RESEARCHER:
        return element.text.strip() or None
    reason = block_reason(element.outcome, element.error)
    if reason:
        blocked.append({"what": what, "reason": reason})
        return None
    answer = notes.renumber(element.outcome.result["answer"], element.outcome.items)
    return f"{COMMENTARY_LABEL} {answer}"


def assemble(
    *,
    title: str,
    document,
    sections: list[SectionDraft],
    introduction: FrameElement | None = None,
    transitions: list[FrameElement | None] | None = None,
    conclusion: FrameElement | None = None,
    reviewed: bool = False,
) -> Article:
    notes, blocked = _Notes(), []
    out: list[str] = []
    if not reviewed:
        out += [f"*{DRAFT_LINE}*", ""]
    out += [f"# {title.strip()}", ""]
    out += [f"*Drawn from {document.author} ({document.year}), {document.title}.*", ""]

    intro = _frame_text(introduction, "introduction", notes, blocked)
    if intro:
        out += [intro, ""]

    kept: list[SectionDraft] = []
    for section in sections:
        reason = block_reason(section.outcome, section.error)
        if reason:
            blocked.append({"what": f"section: {section.heading}", "reason": reason})
        else:
            kept.append(section)

    transitions = transitions or []
    for index, section in enumerate(kept):
        if index > 0:
            # A transition joins two sections that stood next to each other in the outline.
            # It is printed only when the section before it was kept too.
            position = sections.index(section) - 1
            joins_kept = sections[position] is kept[index - 1]
            bridge = transitions[position] if joins_kept and position < len(transitions) else None
            text = _frame_text(bridge, f"transition before: {section.heading}", notes, blocked)
            if text:
                out += [text, ""]
        out += [f"## {section.heading}", ""]
        for paragraph in _section_body(section.outcome, notes):
            out += [paragraph, ""]

    ending = _frame_text(conclusion, "conclusion", notes, blocked)
    if ending:
        out += [ending, ""]

    if notes.items:
        out += ["## Sources", ""]
        for n in sorted(notes.items):
            # ask.footnote writes "n. Author (year), …"; the article uses "[n] …".
            out.append(f"[{n}] " + ask.footnote(n, notes.items[n]).split(". ", 1)[1])
        out.append("")
    out += [f"*{CLOSING_LINE_REVIEWED if reviewed else CLOSING_LINE}*", ""]

    return Article(
        markdown="\n".join(out),
        notes=[{"n": n, "chunk_id": notes.items[n].chunk["chunk_id"], "verdict": None} for n in sorted(notes.items)],
        blocked=blocked,
    )


# ---------------------------------------------------------------------------
# The researcher's verdicts (PLAN_V6 §9)
# ---------------------------------------------------------------------------

VERDICTS = ("supports", "partly", "does not")


def support_rate(notes: list[dict]) -> dict:
    """Counts of the researcher's verdicts. A note not yet judged is counted as
    not judged — never as supported."""
    counts = {verdict: sum(1 for note in notes if note.get("verdict") == verdict) for verdict in VERDICTS}
    counts["not judged"] = sum(1 for note in notes if note.get("verdict") not in VERDICTS)
    counts["notes"] = len(notes)
    return counts
