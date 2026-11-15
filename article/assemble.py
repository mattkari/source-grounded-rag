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
from article import checks

COMMENTARY_LABEL = "Commentary (the article's own reading, not the author's):"
DRAFT_LINE = "DRAFT — the notes in this article have not yet been checked by the researcher."
CLOSING_LINE = "This article was drafted with an AI system from the source named above."
CLOSING_LINE_REVIEWED = (
    "This article was drafted with an AI system from the source named above and checked by the researcher."
)
# Printed, at the researcher's choice, under the heading of a section the thesis
# could not support. A statement about the collection, not the world (hard rule 11).
NOT_COVERED_LINE = "The thesis does not hold enough evidence to say."
INSUFFICIENT = "the thesis does not hold enough evidence for this"
# Limits are gathered under one closing heading, one line per section at most (ADR 0005).
NOT_COVERED_HEADING = "What this article does not cover"
LIMIT_OPENING = "the thesis does not"      # a line a reader can follow opens like this
LIMIT_MAX_WORDS = 30
RESEARCHER, GENERATED = "researcher", "generated"
# A sentence, with any closing quotation marks and note markers that trail its full stop.
_SENTENCE = re.compile(r".+?(?:[.!?][\"'’”)]*(?:\s?\[E\d+\])*(?=\s|$)|$)", re.DOTALL)
_TABLE_LINE = re.compile(r"^\s*\|.*\|\s*$", re.MULTILINE)


@dataclass
class SectionDraft:
    heading: str
    brief: str
    outcome: ask.QueryOutcome | None = None   # None when the pipeline raised
    error: str | None = None
    kept: bool = True                         # False: the researcher dropped the section
    state_gap: bool = False                   # True: print that the thesis does not cover it
    # The editorial pass, if one was run (ADR 0005). `prose` is the accepted rewrite of
    # the answer, or None; `editorial` is the full recorded outcome of the pass.
    prose: str | None = None
    editorial: dict | None = None


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
    notes: list[dict] = field(default_factory=list)      # {n, chunk_id}
    blocked: list[dict] = field(default_factory=list)    # {what, reason}
    # note number -> the sentences that carry it, for the side-by-side review (§9)
    carriers: dict[int, list[str]] = field(default_factory=dict)
    # generated frame text holding sentences with no note: raised for the researcher (§6)
    unnoted: list[dict] = field(default_factory=list)    # {what, sentences}
    # section heading -> the one limitation line printed for it, as printed
    limits_printed: dict[str, str] = field(default_factory=dict)
    limits_held_back: int = 0                            # limitation lines kept in the record only
    # One entry per section the model gave commentary for (ADR 0005):
    # {section, heading, text, printed, flags, held_back}. `text` is as printed.
    commentary: list[dict] = field(default_factory=list)


def block_reason(outcome: ask.QueryOutcome | None, error: str | None = None) -> str | None:
    """Why an outcome may not be printed, or None if it may."""
    if outcome is None:
        return f"the pipeline failed: {error}"
    if outcome.failures:
        return "validation failed: " + "; ".join(outcome.failures)
    result = outcome.result
    if result.get("evidence_sufficiency") == "insufficient" or result.get("answer") is None:
        return INSUFFICIENT
    form = checks.prose_failures(result)
    if form:
        return "article check failed: " + "; ".join(form)
    texts = [result["answer"], *result.get("limitations", []), *result.get("ai_interpretation", [])]
    if any(_TABLE_LINE.search(text) for text in texts):
        return "the draft contains a table, which the article format does not allow"
    return None


def split_sentences(text: str) -> list[str]:
    return [match.group(0).strip() for match in _SENTENCE.finditer(text) if match.group(0).strip()]


class _Notes:
    """One run of note numbers across the whole article, keyed by passage."""

    def __init__(self, removed: set[str]) -> None:
        self.removed = removed                    # passages whose sentences the researcher removed
        self.numbers: dict[str, int] = {}
        self.items: dict[int, ask.EvidenceItem] = {}
        self.carriers: dict[int, list[str]] = {}

    def renumber(self, text: str, items: list[ask.EvidenceItem]) -> str:
        """`text` with `[En]` handles as article note numbers, paragraph by paragraph.
        A sentence carrying a note the researcher judged unsupported and removed is left out."""
        by_handle = {item.handle: item for item in items}

        def chunk_ids(sentence: str) -> list[str]:
            # validation guarantees every handle exists
            return [by_handle[f"E{n}"].chunk["chunk_id"] for n in ask.MARKER_RE.findall(sentence)]

        def swap(match: re.Match) -> str:
            item = by_handle[f"E{match.group(1)}"]
            chunk_id = item.chunk["chunk_id"]
            if chunk_id not in self.numbers:
                self.numbers[chunk_id] = len(self.numbers) + 1
                self.items[self.numbers[chunk_id]] = item
            return f"[{self.numbers[chunk_id]}]"

        paragraphs = []
        for paragraph in text.split("\n"):
            sentences = []
            for sentence in split_sentences(paragraph):
                if any(chunk_id in self.removed for chunk_id in chunk_ids(sentence)):
                    continue
                printed = ask.MARKER_RE.sub(swap, sentence)
                for chunk_id in dict.fromkeys(chunk_ids(sentence)):
                    self.carriers.setdefault(self.numbers[chunk_id], []).append(printed)
                sentences.append(printed)
            paragraphs.append(" ".join(sentences))
        return "\n".join(paragraphs).strip()


def _cited_passages(text: str, items: list[ask.EvidenceItem]) -> list[str]:
    cited = {f"E{n}" for n in ask.MARKER_RE.findall(text)}
    return [item.chunk["text"] for item in items if item.handle in cited] or [item.chunk["text"] for item in items]


def _section_body(section: SectionDraft, notes: _Notes) -> list[str]:
    body = notes.renumber(section.prose or section.outcome.result["answer"], section.outcome.items)
    return [body] if body else []


def _commentary(index: int, section: SectionDraft, notes: _Notes, show: bool) -> dict | None:
    """The one commentary paragraph a section may carry: the model's first. It is
    printed only when the researcher has switched commentary on and not rejected it."""
    given = section.outcome.result.get("ai_interpretation", [])
    if not given:
        return None
    entry = {"section": index, "heading": section.heading, "text": "", "printed": False,
             "flags": checks.agent_flags(given[0], _cited_passages(given[0], section.outcome.items)),
             "held_back": len(given) - 1}
    if show:
        entry["text"] = notes.renumber(given[0], section.outcome.items)
        entry["printed"] = bool(entry["text"])
    return entry


def reader_limit(result: dict) -> str | None:
    """The one limitation line that may be printed for a section: the first that is
    written for a reader. The rest stay in the record."""
    for line in result.get("limitations", []):
        plain = ask.MARKER_RE.sub("", line).strip()
        if plain.lower().startswith(LIMIT_OPENING) and len(plain.split()) <= LIMIT_MAX_WORDS:
            return line.strip()
    return None


def _frame_text(element: FrameElement | None, what: str, notes: _Notes, article: "Article") -> str | None:
    if element is None:
        return None
    if element.origin == RESEARCHER:
        return element.text.strip() or None
    reason = block_reason(element.outcome, element.error)
    if reason:
        article.blocked.append({"what": what, "reason": reason})
        return None
    answer = notes.renumber(element.outcome.result["answer"], element.outcome.items)
    if not answer:
        return None
    bare = sum(1 for sentence in split_sentences(answer) if not re.search(r"\[\d+\]", sentence))
    if bare:
        article.unnoted.append({"what": what, "sentences": bare})
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
    removed: set[str] | None = None,
    commentary: bool = False,
    commentary_rejected: set[int] | None = None,
) -> Article:
    """`removed` holds the passages whose sentences the researcher took out after
    judging that the passage does not support them (§9)."""
    notes = _Notes(set(removed or ()))
    article = Article(markdown="")
    out: list[str] = []
    if not reviewed:
        out += [f"*{DRAFT_LINE}*", ""]
    out += [f"# {title.strip()}", ""]
    out += [f"*Drawn from {document.author} ({document.year}), {document.title}.*", ""]

    intro = _frame_text(introduction, "introduction", notes, article)
    if intro:
        out += [intro, ""]

    # What will be printed for each section: its paragraphs, or the gap line.
    printed: list[tuple[SectionDraft, bool]] = []          # (section, is a real drafted section)
    for section in sections:
        if not section.kept:
            continue
        reason = block_reason(section.outcome, section.error)
        if reason is None:
            printed.append((section, True))
        elif reason == INSUFFICIENT and section.state_gap:
            printed.append((section, False))
        else:
            article.blocked.append({"what": f"section: {section.heading}", "reason": reason})

    transitions = transitions or []
    previous: SectionDraft | None = None
    shown: list[SectionDraft] = []                           # drafted sections that reached the page
    for section, drafted in printed:
        body = _section_body(section, notes) if drafted else [NOT_COVERED_LINE]
        if not body:
            continue                                         # every sentence of it was removed
        if drafted:
            shown.append(section)
        position = sections.index(section) - 1
        # A transition joins two drafted sections that stood next to each other in the outline.
        if drafted and previous is not None and position >= 0 and sections[position] is previous:
            bridge = transitions[position] if position < len(transitions) else None
            text = _frame_text(bridge, f"transition before: {section.heading}", notes, article)
            if text:
                out += [text, ""]
        out += [f"## {section.heading}", ""]
        for paragraph in body:
            out += [paragraph, ""]
        if drafted:
            index = sections.index(section)
            entry = _commentary(index, section, notes, commentary and index not in (commentary_rejected or ()))
            if entry:
                article.commentary.append(entry)
                if entry["printed"]:
                    out += [f"{COMMENTARY_LABEL} {entry['text']}", ""]
        previous = section if drafted else None

    ending = _frame_text(conclusion, "conclusion", notes, article)
    if ending:
        out += [ending, ""]

    # Limits, gathered. A section whose every sentence was removed states none.
    for section in shown:
        chosen = reader_limit(section.outcome.result)
        line = notes.renumber(chosen, section.outcome.items) if chosen else ""
        if line:
            article.limits_printed[section.heading] = line
        article.limits_held_back += len(section.outcome.result.get("limitations", [])) - bool(line)
    if article.limits_printed:
        out += [f"## {NOT_COVERED_HEADING}", ""]
        out += [f"- {line}" for line in article.limits_printed.values()]
        out.append("")

    if notes.items:
        out += ["## Sources", ""]
        for n in sorted(notes.items):
            # ask.footnote writes "n. Author (year), …"; the article uses "[n] …".
            # One paragraph each: consecutive lines would run together when rendered.
            out += [f"[{n}] " + ask.footnote(n, notes.items[n]).split(". ", 1)[1], ""]
    out += [f"*{CLOSING_LINE_REVIEWED if reviewed else CLOSING_LINE}*", ""]

    article.markdown = "\n".join(out)
    article.notes = [{"n": n, "chunk_id": notes.items[n].chunk["chunk_id"], "verdict": None} for n in sorted(notes.items)]
    article.carriers = notes.carriers
    return article


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
