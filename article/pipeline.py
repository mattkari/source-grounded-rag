"""From an outline to a saved, reviewable article — PLAN_V6 §4–§9.

This module holds no generation logic of its own. Sections are drafted by
`ask.run_query` on the filtered sources (`article.sources`); generated frame
text by `ask.draft_from_evidence` on the passages the sections already cite.
Everything else here is bookkeeping: the draft, the researcher's verdicts, the
record, and saving and loading.

Nothing is retried. A section or frame element that fails is kept, with its
reason, and shown.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import ask
from article import assemble, sources, topics, voice
from article.assemble import GENERATED, RESEARCHER, VERDICTS, FrameElement, SectionDraft
from documents import Document, default_document

DEFAULT_OUT_DIR = Path(__file__).resolve().parent.parent / "output" / "articles"
SCHEMA_VERSION = 2
MIN_SECTIONS, MAX_SECTIONS = 3, 6
DRAFT, REVIEWED = "draft", "reviewed"


class ArticleError(RuntimeError):
    """Something the researcher has to put right; the message says what."""


# ---------------------------------------------------------------------------
# The workspace: one document, its filtered sources
# ---------------------------------------------------------------------------


@dataclass
class Workspace:
    document: Document
    sources: sources.Sources
    manifest: dict

    def __post_init__(self) -> None:
        self.by_id = {chunk["chunk_id"]: chunk for chunk in self.sources.chunks}

    def topics(self) -> list[topics.Topic]:
        return topics.list_topics(self.sources.chunks)


def open_workspace(document: Document | None = None, *, store: bool = True) -> Workspace:
    document = document or default_document(ask.settings)
    vectors, chunks, manifest = ask.load_index(document)
    return Workspace(document, sources.open_sources(document, vectors, chunks, manifest, store=store), manifest)


# ---------------------------------------------------------------------------
# Drafting
# ---------------------------------------------------------------------------


def _attempt(call, *args) -> tuple[ask.QueryOutcome | None, str | None]:
    try:
        return call(*args), None
    except (Exception, SystemExit) as exc:  # recorded, never retried (hard rule 9)
        return None, f"{type(exc).__name__}: {' '.join(str(exc).split())[:300]}"


def draft_section(workspace: Workspace, heading: str, brief: str) -> SectionDraft:
    """One brief through the one pipeline, on the filtered sources."""
    outcome, error = _attempt(
        ask.run_query, brief, workspace.sources.vectors, workspace.sources.chunks, None, workspace.document
    )
    return SectionDraft(heading.strip(), brief.strip(), outcome, error)


def usable(section: SectionDraft) -> bool:
    return section.kept and assemble.block_reason(section.outcome, section.error) is None


def cited(outcome: ask.QueryOutcome) -> list[ask.EvidenceItem]:
    """The passages a section actually cites, in order of first use."""
    order = ask.assign_order(outcome.result, outcome.items)
    by_handle = {item.handle: item for item in outcome.items}
    return [by_handle[handle] for handle, _ in sorted(order.items(), key=lambda pair: pair[1])]


def _rehandle(items: list[ask.EvidenceItem]) -> list[ask.EvidenceItem]:
    """The same passages under fresh handles E1..En, without duplicates."""
    seen, fresh = set(), []
    for item in items:
        if item.chunk["chunk_id"] not in seen:
            seen.add(item.chunk["chunk_id"])
            fresh.append(ask.EvidenceItem(f"E{len(fresh) + 1}", item.chunk, item.score, item.document))
    return fresh


def _generated(brief: str, items: list[ask.EvidenceItem]) -> FrameElement:
    if not items:
        return FrameElement(GENERATED, brief=brief, error="no cited passages to draw on")
    outcome, error = _attempt(ask.draft_from_evidence, brief, _rehandle(items))
    return FrameElement(GENERATED, brief=brief, outcome=outcome, error=error)


def written(text: str) -> FrameElement | None:
    """Frame text the researcher typed. It is theirs: not validated, not labelled."""
    return FrameElement(RESEARCHER, text=text.strip()) if text.strip() else None


def draft_introduction(title: str, sections: list[SectionDraft]) -> FrameElement:
    return _generated(
        "In two or three sentences for a general reader, introduce what these passages together "
        f"show about: {title}. Use only what the passages say.",
        [item for section in sections if usable(section) for item in cited(section.outcome)],
    )


def draft_transition(before: SectionDraft, after: SectionDraft) -> FrameElement | None:
    """A bridge between two neighbouring sections; None unless both can be printed."""
    if not (usable(before) and usable(after)):
        return None
    return _generated(
        f"In one sentence, connect “{before.heading}” to “{after.heading}”, using only what the passages say.",
        cited(before.outcome) + cited(after.outcome),
    )


def draft_conclusion(title: str, sections: list[SectionDraft]) -> FrameElement:
    return _generated(
        f"In two or three sentences, say what these passages together establish about: {title}, "
        "and what they leave open. Use only what the passages say.",
        [item for section in sections if usable(section) for item in cited(section.outcome)],
    )


# ---------------------------------------------------------------------------
# The draft and the researcher's verdicts
# ---------------------------------------------------------------------------


@dataclass
class Draft:
    title: str
    sections: list[SectionDraft]
    introduction: FrameElement | None = None
    transitions: list[FrameElement | None] = field(default_factory=list)
    conclusion: FrameElement | None = None
    topic: str | None = None
    # chunk id -> {"verdict", "reason", "judged_at"}; the researcher's, never the model's
    verdicts: dict[str, dict] = field(default_factory=dict)
    removed: set[str] = field(default_factory=set)      # passages whose sentences were taken out
    article_id: str | None = None
    created: str | None = None


def check_outline(title: str, outline: list[tuple[str, str]]) -> None:
    if not title.strip():
        raise ArticleError("Give the article a title. The title is yours to write.")
    if not MIN_SECTIONS <= len(outline) <= MAX_SECTIONS:
        raise ArticleError(
            f"An outline has {MIN_SECTIONS} to {MAX_SECTIONS} sections; this one has {len(outline)}."
        )
    for heading, brief in outline:
        if not heading.strip() or not brief.strip():
            raise ArticleError("Every section needs a heading and a question it must answer.")


def render(workspace: Workspace, draft: Draft) -> assemble.Article:
    """The article as it stands, marked reviewed only if the verdicts say so."""
    def build(reviewed: bool) -> assemble.Article:
        return assemble.assemble(
            title=draft.title, document=workspace.document, sections=draft.sections,
            introduction=draft.introduction, transitions=draft.transitions, conclusion=draft.conclusion,
            reviewed=reviewed, removed=draft.removed,
        )

    article = build(False)
    return build(True) if status(draft, article) == REVIEWED else article


def status(draft: Draft, article: assemble.Article) -> str:
    """Reviewed only when every note in the article has a verdict and none is *does not*."""
    if not article.notes:
        return DRAFT
    given = [draft.verdicts.get(note["chunk_id"], {}).get("verdict") for note in article.notes]
    return REVIEWED if all(v in VERDICTS and v != "does not" for v in given) else DRAFT


def set_verdict(draft: Draft, chunk_id: str, verdict: str, reason: str = "") -> None:
    if verdict not in VERDICTS:
        raise ArticleError(f"A verdict is one of: {', '.join(VERDICTS)}.")
    draft.verdicts[chunk_id] = {
        "verdict": verdict,
        "reason": reason.strip(),
        "judged_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def remove_sentences(draft: Draft, chunk_id: str) -> None:
    """Take out every sentence that carries this note. Only after a *does not*
    verdict, which stays in the record."""
    if draft.verdicts.get(chunk_id, {}).get("verdict") != "does not":
        raise ArticleError("Sentences are removed only for a note judged “does not”.")
    draft.removed.add(chunk_id)


def notes_record(draft: Draft, article: assemble.Article) -> list[dict]:
    """Every note the article has or had: its number now, and the researcher's verdict."""
    numbers = {note["chunk_id"]: note["n"] for note in article.notes}
    rows = []
    for chunk_id in list(numbers) + sorted(draft.removed - set(numbers)):
        given = draft.verdicts.get(chunk_id, {})
        rows.append({
            "n": numbers.get(chunk_id),
            "chunk_id": chunk_id,
            "verdict": given.get("verdict"),
            "reason": given.get("reason", ""),
            "judged_at": given.get("judged_at"),
            "judged_by": "researcher" if given else None,
            "sentences_removed": chunk_id in draft.removed,
        })
    return rows


# ---------------------------------------------------------------------------
# The record
# ---------------------------------------------------------------------------


def _outcome_record(outcome: ask.QueryOutcome | None, error: str | None) -> dict:
    if outcome is None:
        return {"error": error}
    return {
        "prompt_sha256_12": outcome.prompt_hash,
        "evidence": [
            {"handle": item.handle, "chunk_id": item.chunk["chunk_id"], "score": item.score}
            for item in outcome.items
        ],
        "result": outcome.result,
        "validation_failures": list(outcome.failures),
    }


def _frame_record(element: FrameElement | None) -> dict | None:
    if element is None:
        return None
    if element.origin == RESEARCHER:
        # The researcher's own words: kept so the article can be rebuilt; outside the support rate.
        return {"origin": RESEARCHER, "text": element.text}
    return {"origin": GENERATED, "brief": element.brief, **_outcome_record(element.outcome, element.error)}


def voice_columns(article: assemble.Article, reference_text: str = "") -> dict:
    """Surface counts for the draft, sourced prose and commentary apart (§10)."""
    body = article.markdown.split("## Sources")[0].splitlines()
    label = assemble.COMMENTARY_LABEL
    commentary = "\n".join(line[len(label):] for line in body if line.startswith(label))
    sourced = "\n".join(line for line in body if line and not line.startswith(("#", "*", label)))
    columns = {"your writing": voice.measure(reference_text)} if reference_text.strip() else {}
    columns["draft, whole"] = voice.measure(sourced + "\n" + commentary)
    columns["draft, sourced"] = voice.measure(sourced)
    columns["draft, commentary"] = voice.measure(commentary)
    return columns


def build_record(workspace: Workspace, draft: Draft, article: assemble.Article, reference_text: str = "") -> dict:
    cut = workspace.sources.removed
    notes = notes_record(draft, article)

    def section_record(section: SectionDraft) -> dict:
        retrieved = [item.chunk["chunk_id"] for item in section.outcome.items] if section.outcome else []
        answer = (section.outcome.result.get("answer") or "") if section.outcome else ""
        return {
            "heading": section.heading,
            "brief": section.brief,
            "kept_by_researcher": section.kept,
            "gap_stated": section.state_gap,
            "blocked": assemble.block_reason(section.outcome, section.error),
            "footnote_text_cut_from": [chunk_id for chunk_id in retrieved if chunk_id in cut],
            "voice": voice.measure(answer) if answer else None,
            **_outcome_record(section.outcome, section.error),
        }

    return {
        "schema_version": SCHEMA_VERSION,
        "article_id": draft.article_id,
        "created": draft.created,
        "saved": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": status(draft, article),
        "document_id": workspace.document.document_id,
        "corpus_text_sha256": workspace.manifest.get("corpus_text_sha256"),
        "model": ask.settings.llm_model,
        "provider": ask.settings.llm_provider,
        "title": {"origin": RESEARCHER, "text": draft.title},
        "topic": draft.topic,
        "sections": [section_record(section) for section in draft.sections],
        "frame": {
            "introduction": _frame_record(draft.introduction),
            "transitions": [_frame_record(element) for element in draft.transitions],
            "conclusion": _frame_record(draft.conclusion),
        },
        "blocked": article.blocked,
        "frame_sentences_without_a_note": article.unnoted,
        "notes": notes,
        "support": assemble.support_rate(notes),
        "support_excludes": "text written by the researcher, which carries no notes",
        "source_filter": workspace.sources.report.to_json(),
        "voice": voice_columns(article, reference_text),
    }


def _slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40] or "article"


def save(workspace: Workspace, draft: Draft, out_dir: Path | None = None, reference_text: str = "") -> Path:
    """Write `article.md` and `record.json`. A draft keeps its folder across saves."""
    out_dir = Path(out_dir or DEFAULT_OUT_DIR)
    if draft.article_id is None:
        now = datetime.now(timezone.utc)
        base = f"{now.strftime('%Y%m%dT%H%M%SZ')}_{_slug(draft.title)}"
        candidate, attempt = base, 1
        while (out_dir / candidate).exists():          # never overwrite another article
            attempt += 1
            candidate = f"{base}_{attempt}"
        draft.article_id, draft.created = candidate, now.isoformat(timespec="seconds")
    folder = out_dir / draft.article_id
    folder.mkdir(parents=True, exist_ok=True)
    article = render(workspace, draft)
    (folder / "article.md").write_text(article.markdown, encoding="utf-8")
    record = build_record(workspace, draft, article, reference_text)
    (folder / "record.json").write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    return folder


# ---------------------------------------------------------------------------
# Loading a saved draft back
# ---------------------------------------------------------------------------


def _outcome_from(record: dict, brief: str, workspace: Workspace) -> tuple[ask.QueryOutcome | None, str | None]:
    if "error" in record:
        return None, record["error"]
    try:
        items = [
            ask.EvidenceItem(e["handle"], workspace.by_id[e["chunk_id"]], e.get("score", 0.0), workspace.document)
            for e in record["evidence"]
        ]
    except KeyError as missing:
        raise ArticleError(f"The saved article cites a passage this index does not hold: {missing}.") from None
    return ask.QueryOutcome(brief, record["result"], items, list(record["validation_failures"]),
                            record["prompt_sha256_12"]), None


def _frame_from(record: dict | None, workspace: Workspace) -> FrameElement | None:
    if record is None:
        return None
    if record["origin"] == RESEARCHER:
        return FrameElement(RESEARCHER, text=record.get("text", ""))
    outcome, error = _outcome_from(record, record["brief"], workspace)
    return FrameElement(GENERATED, brief=record["brief"], outcome=outcome, error=error)


def load(folder: Path, workspace: Workspace) -> Draft:
    """Rebuild a draft from its record. No model is called."""
    record = json.loads((Path(folder) / "record.json").read_text(encoding="utf-8"))
    if record.get("schema_version") != SCHEMA_VERSION:
        raise ArticleError("This article was saved by an earlier version and cannot be reopened.")
    if record["document_id"] != workspace.document.document_id:
        raise ArticleError(f"This article was drafted from {record['document_id']}, not the thesis now open.")
    if record["corpus_text_sha256"] != workspace.manifest.get("corpus_text_sha256"):
        raise ArticleError("The index has changed since this article was drafted; its notes can no longer be trusted.")
    sections = []
    for entry in record["sections"]:
        outcome, error = _outcome_from(entry, entry["brief"], workspace)
        sections.append(SectionDraft(entry["heading"], entry["brief"], outcome, error,
                                     kept=entry["kept_by_researcher"], state_gap=entry["gap_stated"]))
    return Draft(
        title=record["title"]["text"],
        sections=sections,
        introduction=_frame_from(record["frame"]["introduction"], workspace),
        transitions=[_frame_from(element, workspace) for element in record["frame"]["transitions"]],
        conclusion=_frame_from(record["frame"]["conclusion"], workspace),
        topic=record.get("topic"),
        verdicts={
            note["chunk_id"]: {"verdict": note["verdict"], "reason": note["reason"], "judged_at": note["judged_at"]}
            for note in record["notes"] if note["verdict"]
        },
        removed={note["chunk_id"] for note in record["notes"] if note["sentences_removed"]},
        article_id=record["article_id"],
        created=record["created"],
    )


def saved_articles(out_dir: Path | None = None, document_id: str | None = None) -> list[dict]:
    """Saved articles, newest first: id, title, status, support counts. No article text."""
    out_dir = Path(out_dir or DEFAULT_OUT_DIR)
    rows = []
    for path in sorted(out_dir.glob("*/record.json"), reverse=True) if out_dir.exists() else []:
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("schema_version") != SCHEMA_VERSION:
            continue
        if document_id and record.get("document_id") != document_id:
            continue
        rows.append({"article_id": record["article_id"], "title": record["title"]["text"],
                     "status": record["status"], "support": record["support"], "folder": path.parent})
    return rows
