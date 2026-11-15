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


def format_topics(topics: list[Topic]) -> str:
    lines = []
    for number, topic in enumerate(topics, start=1):
        thin = "  (thin: few passages)" if topic.passages < 3 else ""
        lines.append(f"{number:>2}. {topic.chapter} — {topic.passages} passages, {topic.pages}{thin}")
        for section in topic.sections:
            lines.append(
                f"      · {section.title} — {section.passages} passages, "
                f"{_span(section.page_first, section.page_last)}"
            )
    return "\n".join(lines)
