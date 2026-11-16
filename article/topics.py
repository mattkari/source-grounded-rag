"""What a thesis covers, read from its index — PLAN_V6 §4.

No model is involved. A topic here is a chapter the document itself prints,
with the sections under it, their printed page spans and how many passages the
index holds for each. Reference apparatus is never offered as a topic.

A default outline is likewise built from printed structure only: each brief
asks what the thesis says about one of its own section titles. The researcher
may replace any of it.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Section:
    title: str
    passages: int
    page_first: str | None
    page_last: str | None


@dataclass
class Topic:
    chapter: str
    passages: int
    page_first: str | None
    page_last: str | None
    sections: list[Section] = field(default_factory=list)

    @property
    def pages(self) -> str:
        return _span(self.page_first, self.page_last)


def _span(first: str | None, last: str | None) -> str:
    if first is None and last is None:
        return "pages not printed"
    if first == last or last is None or first is None:
        return f"p. {first or last}"
    return f"pp. {first}–{last}"


def _first(labels):
    return next((label for label in labels if label is not None), None)


def list_topics(chunks: list[dict]) -> list[Topic]:
    """Chapters in document order, each with its sections. Stored provenance only."""
    topics: dict[str, Topic] = {}
    members: dict[str, list[dict]] = {}
    for chunk in chunks:
        if chunk.get("kind") == "apparatus" or not chunk.get("chapter"):
            continue
        members.setdefault(chunk["chapter"], []).append(chunk)

    for chapter, passages in members.items():
        topic = Topic(
            chapter=chapter,
            passages=len(passages),
            page_first=_first(c["page_start"] for c in passages),
            page_last=_first(c["page_end"] for c in reversed(passages)),
        )
        by_section: dict[str, list[dict]] = {}
        for chunk in passages:
            if chunk.get("section"):
                by_section.setdefault(chunk["section"], []).append(chunk)
        for title, group in by_section.items():
            topic.sections.append(
                Section(
                    title=title,
                    passages=len(group),
                    page_first=_first(c["page_start"] for c in group),
                    page_last=_first(c["page_end"] for c in reversed(group)),
                )
            )
        topics[chapter] = topic
    return list(topics.values())


def default_briefs(topic: Topic, count: int = 3) -> list[str]:
    """Briefs built from the chapter's own section titles: the `count` sections
    with the most passages, kept in document order."""
    richest = sorted(topic.sections, key=lambda s: -s.passages)[:count]
    chosen = [s for s in topic.sections if s in richest]
    return [f"What does the thesis say about “{section.title}”?" for section in chosen]


# ---------------------------------------------------------------------------
# Briefs by rhetorical move — no model (ADR 0008)
# ---------------------------------------------------------------------------

# "What does the thesis say about X?" yields a summary of X. A brief that asks for a
# move yields a step in an argument. Each template is filled with one of the thesis's
# own section titles; `compare` takes two. The researcher edits the result.
SUMMARY = "what it says"
MOVES = {
    SUMMARY: "What does the thesis say about “{a}”?",
    "define": "How does the thesis define {a}?",
    "explain how": "How, according to the thesis, does {a} work?",
    "compare": "How does the thesis compare {a} with {b}?",
    "consequences": "What, according to the thesis, follows from {a}?",
    "what is not covered": "What does the thesis leave open about {a}?",
}
ARGUMENT = "an argument: define, explain how, consequences"
OUTLINE_KINDS = (SUMMARY, ARGUMENT, "define", "explain how", "compare", "consequences", "what is not covered")
_NUMBERING = __import__("re").compile(r"^\s*\d+(?:\.\d+)*[.)]?\s+")


def plain_title(title: str) -> str:
    """A section title as it can sit in a sentence: its numbering dropped, and a title
    printed in capitals put in lower case. Nothing is added or reworded."""
    text = _NUMBERING.sub("", title).strip()
    return text.lower() if text.isupper() else text


def heading(title: str) -> str:
    text = plain_title(title)
    return text[:1].upper() + text[1:]


def outline(topic: Topic, kind: str = SUMMARY, count: int = 3) -> list[tuple[str, str]]:
    """An outline to edit: `count` (heading, brief) pairs from the chapter's richest
    sections, in document order, each brief asking for the move `kind` names."""
    if kind not in OUTLINE_KINDS:
        raise ValueError(f"an outline is one of: {', '.join(OUTLINE_KINDS)}")
    richest = sorted(topic.sections, key=lambda s: -s.passages)[:count]
    chosen = [section for section in topic.sections if section in richest]
    moves = (["define", "explain how", "consequences"] * count)[:len(chosen)] if kind == ARGUMENT else [kind] * len(chosen)
    pairs = []
    for position, (section, move) in enumerate(zip(chosen, moves)):
        other = chosen[(position + 1) % len(chosen)]
        title = section.title if move == SUMMARY else plain_title(section.title)
        pairs.append((heading(section.title) if move != SUMMARY else section.title,
                      MOVES[move].format(a=title, b=plain_title(other.title))))
    return pairs


def count(passages: int) -> str:
    return "1 passage" if passages == 1 else f"{passages} passages"


def format_topics(topics: list[Topic]) -> str:
    lines = []
    for number, topic in enumerate(topics, start=1):
        thin = "  (thin: few passages)" if topic.passages < 3 else ""
        lines.append(f"{number:>2}. {topic.chapter} — {count(topic.passages)}, {topic.pages}{thin}")
        for section in topic.sections:
            lines.append(
                f"      · {section.title} — {count(section.passages)}, "
                f"{_span(section.page_first, section.page_last)}"
            )
    return "\n".join(lines)
