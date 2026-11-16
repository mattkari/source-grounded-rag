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

import difflib
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import ask
from article import assemble, checks, export as article_export, sentences, sources, terms, topics, voice
from article.assemble import GENERATED, RESEARCHER, SUGGESTED, VERDICTS, FrameElement, SectionDraft
from documents import Document, default_document

DEFAULT_OUT_DIR = Path(__file__).resolve().parent.parent / "output" / "articles"
SCHEMA_VERSION = 4
READABLE_SCHEMAS = (2, 3, 4)      # 2: before plans and step-by-step saving; read as finished
MIN_SECTIONS, MAX_SECTIONS = 3, 6
DRAFTING, DRAFT, REVIEWED = "drafting", "draft", "reviewed"
FRAME_ORIGINS = (RESEARCHER, GENERATED, "none")


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
    instructions, _ = checks.load_prompt(checks.SECTION_PROMPT)
    outcome, error = _attempt(
        lambda: ask.run_query(brief, workspace.sources.vectors, workspace.sources.chunks, None,
                              workspace.document, instructions=instructions)
    )
    return SectionDraft(heading.strip(), brief.strip(), outcome, error)


EXEMPLAR_WORDS = 300


def voice_example(text: str) -> str:
    """The opening of the researcher's own writing, to whole sentences, as much as the
    editor is shown: about `EXEMPLAR_WORDS` words. Enough to hear a voice; too little to
    be a source."""
    kept, words = [], 0
    for line in text.split("\n"):
        for sentence in sentences.split(" ".join(line.split())):
            if words and words + len(sentence.split()) > EXEMPLAR_WORDS:
                return " ".join(kept)
            kept.append(sentence)
            words += len(sentence.split())
    return " ".join(kept)


def edit_section(section: SectionDraft, exemplar: str = "") -> SectionDraft:
    """The optional editorial pass: one more call, through the same model call and
    the same validation, asking for the validated prose to be rewritten for flow.

    The rewrite replaces the original only if it preserves: the same markers in
    each paragraph, no new name, number or transliterated term, no em dash, and
    every usual check passed. Otherwise the original stands. Either way the
    outcome is recorded, and nothing is sent again (hard rule 9).
    """
    if not usable(section) or section.editorial is not None:
        return section
    original = section.outcome.result["answer"]
    prompt, digest = checks.load_prompt(checks.EDITORIAL_PROMPT)
    # The researcher's own prose, if they gave some, is shown for its voice alone (ADR 0010).
    # What a rewrite may add is still checked against the DRAFT only, so nothing of the
    # example's content can pass into the section.
    shown = voice_example(exemplar)
    example = f"\nVOICE EXAMPLE\n=============\n{shown}\n" if shown else ""
    instructions = f"{prompt}{example}\nDRAFT\n=====\n{original}"
    outcome, error = _attempt(lambda: ask.draft_from_evidence(section.brief, section.outcome.items, instructions=instructions))
    failures = [f"the pipeline failed: {error}"] if outcome is None else checks.editorial_failures(
        original, outcome.result, outcome.failures)
    rewrite = (outcome.result.get("answer") or "") if outcome else ""
    section.editorial = {
        "prompt": checks.EDITORIAL_PROMPT,
        "prompt_sha256_12": digest,
        "accepted": not failures,
        "rejected_because": failures,
        "result": outcome.result if outcome else None,
        "system_prompt_sha256_12": outcome.prompt_hash if outcome else None,
        "similarity_to_original": round(difflib.SequenceMatcher(None, original, rewrite, autojunk=False).ratio(), 3)
        if rewrite else None,
        # The example is the researcher's own text and stays out of this entry: its size and hash only.
        "voice_example": {"words": len(shown.split()),
                          "sha256_12": hashlib.sha256(shown.encode("utf-8")).hexdigest()[:12]} if shown else None,
        "voice_before": voice.measure(original),
        "voice_after": voice.measure(rewrite) if rewrite else None,
    }
    section.prose = rewrite if not failures else None
    return section


def em_dashes(draft: "Draft") -> dict[str, int]:
    """Em dashes in each section's prose as it is printed, by heading. Reported, never
    changed: a dash cannot be swapped for a comma or a semicolon without choosing how
    the sentence is read, and that choice is the researcher's (ADR 0006)."""
    counts = {}
    for section in draft.sections:
        if usable(section):
            found = len(voice.EM_DASH.findall(section.prose or section.outcome.result["answer"]))
            if found:
                counts[section.heading] = found
    return counts


def usable(section: SectionDraft) -> bool:
    return section.kept and not section.pending and assemble.block_reason(section.outcome, section.error) is None


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
    instructions, _ = checks.load_prompt(checks.SECTION_PROMPT)
    fresh = _rehandle(items)
    outcome, error = _attempt(lambda: ask.draft_from_evidence(brief, fresh, instructions=instructions))
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
    commentary: bool = False                            # print the model's commentary at all (off by default)
    # section index -> {"verdict": "accept" | "reject", "judged_at"}; the researcher's
    commentary_verdicts: dict[int, dict] = field(default_factory=dict)
    article_id: str | None = None
    created: str | None = None
    # The plan, fixed before the first call, so an interrupted draft can be resumed
    # from its record (ADR 0005). `frame_plan` maps introduction / transitions /
    # conclusion to "researcher", "generated" or "none".
    # Sentence by sentence (ADR 0008). An edit is {"text": str | None, "original": str,
    # "edited_at": iso}; text None means the researcher deleted the sentence.
    # "<sid>|<chunk id>" -> {"verdict", "reason", "judged_at", "judged_text"}: the researcher's
    # verdict on one sentence and one note it carries, and the text it was given on.
    pair_verdicts: dict[str, dict] = field(default_factory=dict)
    sentence_edits: dict[str, dict] = field(default_factory=dict)
    own_words: dict[str, dict] = field(default_factory=dict)     # sid -> {"kept_at": iso}: unnoted, kept as theirs
    # "introduction" | "conclusion" -> every suggestion asked for, newest last (ADR 0008)
    frame_suggestions: dict[str, list[dict]] = field(default_factory=dict)
    frame_plan: dict[str, str] = field(default_factory=dict)
    editorial: bool = False
    # The researcher's own prose, shown to the editorial pass as an example of voice. Kept
    # with the plan so an interrupted draft resumes with it; it is theirs, and stays local.
    voice_exemplar: str = ""
    frame_done: set[str] = field(default_factory=set)   # generated frame steps already made
    complete: bool = True                               # False while steps of the plan remain


def new_draft(title: str, outline: list[tuple[str, str]], *, topic: str | None = None,
              introduction: str = "none", transitions: str = "none", conclusion: str = "none",
              introduction_text: str = "", transitions_text: list[str] | None = None, conclusion_text: str = "",
              commentary: bool = False, editorial: bool = False, voice_exemplar: str = "") -> Draft:
    """A plan and nothing else: every section pending, no model called yet. Text the
    researcher wrote is placed at once; it needs no call."""
    check_outline(title, outline)
    plan = {"introduction": introduction, "transitions": transitions, "conclusion": conclusion}
    for part, origin in plan.items():
        if origin not in FRAME_ORIGINS:
            raise ArticleError(f"The {part} is one of: {', '.join(FRAME_ORIGINS)}.")
    gaps = len(outline) - 1
    typed = list(transitions_text or [])[:gaps] + [""] * max(gaps - len(transitions_text or []), 0)
    return Draft(
        title=title.strip(), topic=topic, commentary=commentary, editorial=editorial, frame_plan=plan, complete=False,
        voice_exemplar=voice_exemplar if editorial else "",
        sections=[SectionDraft(heading.strip(), brief.strip(), pending=True) for heading, brief in outline],
        introduction=written(introduction_text) if introduction == RESEARCHER else None,
        transitions=[written(text) if transitions == RESEARCHER else None for text in typed],
        conclusion=written(conclusion_text) if conclusion == RESEARCHER else None,
    )


def planned_calls(draft: Draft) -> dict[str, int]:
    """Model calls the plan still needs, counted without making any. The editorial
    and transition counts are upper bounds: neither is made for a blocked section."""
    pending = sum(1 for s in draft.sections if s.pending)
    plan = draft.frame_plan
    remaining = {
        "sections": pending,
        "editorial": sum(1 for s in draft.sections if s.pending or (usable(s) and s.editorial is None))
        if draft.editorial else 0,
        "introduction": int(plan.get("introduction") == GENERATED and "introduction" not in draft.frame_done),
        "transitions": sum(1 for n in range(len(draft.sections) - 1) if f"transition:{n}" not in draft.frame_done)
        if plan.get("transitions") == GENERATED else 0,
        "conclusion": int(plan.get("conclusion") == GENERATED and "conclusion" not in draft.frame_done),
    }
    remaining["model_calls"] = sum(remaining.values())
    remaining["embedding_calls"] = pending          # one question embedded per section
    return remaining


def run(workspace: Workspace, draft: Draft, out_dir: Path | None = None, reference_text: str = "",
        on_step=None) -> Draft:
    """Carry out what the plan still needs, saving the record after every step.

    A restart loses at most the step in flight. Called again on a reloaded draft
    it resumes: a section, rewrite or frame element already in the record is not
    sent again, whether it succeeded, was blocked or failed (hard rule 9).
    """
    def done(what: str) -> None:
        save(workspace, draft, out_dir, reference_text)
        if on_step:
            on_step(what)

    if draft.article_id is None:
        save(workspace, draft, out_dir, reference_text)        # the plan is on disk before any call
    for index, section in enumerate(draft.sections):
        if section.pending:
            drafted = draft_section(workspace, section.heading, section.brief)
            drafted.kept, drafted.state_gap = section.kept, section.state_gap
            draft.sections[index] = drafted
            done(f"section {index + 1}: {section.heading}")
    if draft.editorial:
        for index, section in enumerate(draft.sections):
            if usable(section) and section.editorial is None:
                edit_section(section, draft.voice_exemplar)
                done(f"editorial pass {index + 1}: {section.heading}")
    plan = draft.frame_plan
    if plan.get("introduction") == GENERATED and "introduction" not in draft.frame_done:
        draft.introduction = draft_introduction(draft.title, draft.sections)
        draft.frame_done.add("introduction")
        done("introduction")
    if plan.get("transitions") == GENERATED:
        draft.transitions += [None] * (len(draft.sections) - 1 - len(draft.transitions))
        for n, (before, after) in enumerate(zip(draft.sections, draft.sections[1:])):
            if f"transition:{n}" not in draft.frame_done:
                draft.transitions[n] = draft_transition(before, after)
                draft.frame_done.add(f"transition:{n}")
                done(f"transition {n + 1}")
    if plan.get("conclusion") == GENERATED and "conclusion" not in draft.frame_done:
        draft.conclusion = draft_conclusion(draft.title, draft.sections)
        draft.frame_done.add("conclusion")
        done("conclusion")
    if not draft.complete:
        draft.complete = True
        done("finished")
    return draft


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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
            reviewed=reviewed, removed=draft.removed, commentary=draft.commentary,
            commentary_rejected={i for i, v in draft.commentary_verdicts.items() if v["verdict"] == "reject"},
            edits=draft.sentence_edits, own_words=set(draft.own_words),
        )

    article = build(False)
    return build(True) if status(draft, article) == REVIEWED else article


def status(draft: Draft, article: assemble.Article) -> str:
    """Reviewed only when every note in the article has a verdict and none is *does not*,
    and every commentary paragraph printed in it has been accepted by the researcher.
    While steps of the plan remain it is still being drafted."""
    if not draft.complete:
        return DRAFTING
    if not article.pairs or article.held_back:
        return DRAFT                                      # a sentence with no note is still waiting for a decision
    for entry in article.commentary:
        if entry["printed"] and draft.commentary_verdicts.get(entry["section"], {}).get("verdict") != "accept":
            return DRAFT
    given = [(pair_verdict(draft, pair) or {}).get("verdict") for pair in article.pairs]
    return REVIEWED if all(v in VERDICTS and v != "does not" for v in given) else DRAFT


PREVIEW_PASSAGES = 3


def preview(workspace: Workspace, brief: str) -> dict:
    """What a section's question would draw on, from the embedding step alone: no
    generation, nothing paid for but one embedding. Pages come from stored provenance.

    The score is the retrieval similarity. It is a diagnostic, never a confidence
    (hard rule 4): a low best score is a reason to look at the question, and refuses
    nothing. `below_threshold` is None when no threshold is configured.
    """
    found = ask.retrieve(brief, workspace.sources.vectors, workspace.sources.chunks,
                         PREVIEW_PASSAGES, workspace.document)
    threshold = ask.settings.preview_min_score
    best = max((item.score for item in found), default=0.0)
    return {
        "brief": brief,
        "passages": [{"chunk_id": item.chunk["chunk_id"], "pages": ask.page_phrase(item.chunk),
                      "where": item.chunk.get("section") or item.chunk.get("chapter") or "",
                      "score": round(item.score, 3)} for item in found],
        "best_score": round(best, 3),
        "threshold": threshold,
        "below_threshold": None if threshold is None else best < threshold,
    }


def format_preview(previews: list[dict]) -> str:
    """The previews as plain text, for the command line and the view alike."""
    lines = ["RETRIEVAL PREVIEW (embedding only; scores are diagnostics, not confidence)"]
    for number, shown in enumerate(previews, start=1):
        lines.append(f"  {number}. {shown['brief']}")
        for passage in shown["passages"]:
            lines.append(f"       {passage['score']:.3f}  {passage['pages']:<14} {passage['where'][:60]}")
        if shown["below_threshold"]:
            lines.append(f"       LOOK: the best score, {shown['best_score']:.3f}, is below {shown['threshold']:.3f}. "
                         "The thesis may not cover this question.")
    if previews and previews[0]["threshold"] is None:
        lines.append("  No threshold is set (PREVIEW_MIN_SCORE), so no question is flagged.")
    return "\n".join(lines)


FRAME_KINDS = {"introduction": "an introduction to", "conclusion": "a conclusion for"}
_BRACKET = re.compile(r"\[[^\]]*\]")


def section_text(article: assemble.Article) -> str:
    """The article's own section prose, without its note markers: all that a frame
    suggestion is given, and all it may draw on."""
    parts = [text for kind, text in article.blocks if kind in ("heading", "paragraph")]
    return re.sub(r"\s+([.,;:])", r"\1", _BRACKET.sub("", "\n\n".join(parts)))


def suggest_frame(workspace: Workspace, draft: Draft, kind: str) -> dict:
    """Ask once for an introduction or a conclusion, from the article's own text.

    One model call, made when the researcher asks for it. Nothing is retrieved
    and no passage is shown: the model sees the section text and nothing else.
    The suggestion may add no name, number or transliterated term the sections
    do not hold, no bracket and no em dash; one that does is kept in the record
    as rejected and is not offered. It prints nothing by itself.
    """
    if kind not in FRAME_KINDS:
        raise ArticleError("A suggestion is for the introduction or the conclusion.")
    body = section_text(render(workspace, draft))
    if not body.strip():
        raise ArticleError("There is no section text yet to suggest from.")
    prompt, digest = checks.load_prompt(checks.FRAME_PROMPT)
    task = f"Write {FRAME_KINDS[kind]} the article titled “{draft.title}”."
    try:
        result, system_hash = ask.suggest_from_text(task, f"{prompt}\nARTICLE\n=======\n{body}")
        error = None
    except (Exception, SystemExit) as exc:  # recorded, never retried (hard rule 9)
        result, system_hash, error = {}, None, f"{type(exc).__name__}: {' '.join(str(exc).split())[:300]}"
    text = " ".join((result.get("answer") or "").split())
    problems = []
    if error:
        problems.append(f"the pipeline failed: {error}")
    elif not text:
        problems.append("no_text: the model returned nothing to suggest")
    else:
        added = checks.new_terms(f"{draft.title}\n{body}", text)
        if added:
            problems.append("new_terms: the suggestion adds " + ", ".join(f"“{term}”" for term in added[:8]))
        if _BRACKET.search(text):
            problems.append("brackets: the suggestion holds a bracket or a note marker")
        if ask.PAGE_CLAIM_RE.findall(text):
            problems.append("page_number: the suggestion holds a page number")
        if voice.EM_DASH.search(text):
            problems.append("em_dash: the suggestion uses an em dash")
        problems += checks.quotation_failures(text)
    suggestion = {
        "kind": kind, "prompt": checks.FRAME_PROMPT, "prompt_sha256_12": digest,
        "system_prompt_sha256_12": system_hash, "text": text or None, "rejected_because": problems,
        "suggested_at": _now(),
    }
    draft.frame_suggestions.setdefault(kind, []).append(suggestion)
    return suggestion


def offered(draft: Draft, kind: str) -> str | None:
    """The newest suggestion for this part, if it passed its checks."""
    latest = (draft.frame_suggestions.get(kind) or [None])[-1]
    return latest["text"] if latest and not latest["rejected_because"] else None


def set_frame(draft: Draft, kind: str, text: str) -> None:
    """Put the researcher's introduction or conclusion in the article. If it started
    from a suggestion that passed its checks, it is recorded as suggested by the model
    and accepted by the researcher, with what the model proposed kept beside it.
    Otherwise it is the researcher's own. Empty text takes the part out."""
    if kind not in FRAME_KINDS:
        raise ArticleError("This is for the introduction or the conclusion.")
    text, proposed = text.strip(), offered(draft, kind)
    element = None
    if text:
        element = (FrameElement(SUGGESTED, text=text, suggestion=proposed) if proposed
                   else FrameElement(RESEARCHER, text=text))
    setattr(draft, kind, element)


def export_blockers(draft: Draft, article: assemble.Article) -> list[str]:
    """What still stands between this article and its export, in words. Empty when it
    may be exported: every pair judged, no *does not* left, every sentence without a
    note resolved, every printed commentary accepted."""
    blockers = []
    if not draft.complete:
        blockers.append("the draft is not finished")
    if article.held_back:
        blockers.append(f"{len(article.held_back)} sentence(s) with no note are waiting to be deleted or kept as yours")
    given = [(pair_verdict(draft, pair) or {}).get("verdict") for pair in article.pairs]
    if not article.pairs:
        blockers.append("the article has no sourced sentence")
    if given.count(None):
        blockers.append(f"{given.count(None)} of {len(given)} sentences are not judged yet")
    if given.count("does not"):
        blockers.append(f"{given.count('does not')} sentence(s) judged “does not” are still in the article")
    waiting = sum(1 for entry in article.commentary if entry["printed"]
                  and draft.commentary_verdicts.get(entry["section"], {}).get("verdict") != "accept")
    if waiting:
        blockers.append(f"{waiting} commentary paragraph(s) are not accepted")
    return blockers


def export(workspace: Workspace, draft: Draft) -> dict[str, str]:
    """The article as it is published, as Markdown and as HTML. Refused while anything
    blocks it: what is exported is what the record shows as reviewed."""
    article = render(workspace, draft)
    blockers = export_blockers(draft, article)
    if blockers:
        raise ArticleError("This article cannot be exported yet: " + "; ".join(blockers) + ".")
    owner = ask.settings.owner_name
    return {"markdown": article_export.markdown(article, workspace.document, owner),
            "html": article_export.as_html(article, workspace.document, owner)}


def pair_key(pair: dict) -> str:
    return f"{pair['sid']}|{pair['chunk_id']}"


def pair_verdict(draft: Draft, pair: dict) -> dict | None:
    """The researcher's verdict on this sentence and this note, if it still stands.

    A verdict stands for the text it was given on: an edited sentence needs a
    fresh one. A verdict given per note, before sentences were judged one by one
    (ADR 0008), is carried over to every sentence of that note that has not been
    edited since, and is marked as carried over.
    """
    own = draft.pair_verdicts.get(pair_key(pair))
    if own is not None:
        return {**own, "carried_over": False} if own["judged_text"] == pair["raw"] else None
    legacy = draft.verdicts.get(pair["chunk_id"])
    if legacy and legacy.get("verdict") and not pair["edited"]:
        return {**legacy, "carried_over": True}
    return None


def set_pair_verdict(draft: Draft, pair: dict, verdict: str, reason: str = "") -> None:
    if verdict not in VERDICTS:
        raise ArticleError(f"A verdict is one of: {', '.join(VERDICTS)}.")
    draft.pair_verdicts[pair_key(pair)] = {
        "verdict": verdict, "reason": reason.strip(), "judged_at": _now(), "judged_text": pair["raw"]}


def pair_flags(workspace: Workspace, pair: dict) -> list[str]:
    """What is raised for the researcher on this pair. Today: reported speech in the
    passage sentence that best matches the drafted one."""
    matches = sentences.best_matches(pair["raw"], workspace.by_id[pair["chunk_id"]]["text"], limit=1)
    return checks.reported_speech_flags(pair["raw"], matches[0].text) if matches else []


def pairs_record(draft: Draft, article: assemble.Article, workspace: Workspace | None = None) -> list[dict]:
    """Every sentence-and-note pair the article has, with the researcher's verdict,
    and every pair it had: a sentence deleted after a verdict keeps that verdict here."""
    rows, current = [], set()
    for pair in article.pairs:
        given = pair_verdict(draft, pair) or {}
        current.add(pair_key(pair))
        rows.append({
            "sid": pair["sid"], "chunk_id": pair["chunk_id"], "n": pair["n"], "sentence": pair["sentence"],
            "verdict": given.get("verdict"), "reason": given.get("reason", ""), "judged_at": given.get("judged_at"),
            "judged_by": "researcher" if given else None, "carried_over": bool(given.get("carried_over")),
            "in_article": True,
            # the text the verdict was given on; None for a verdict carried over from a note
            "raw": None if given.get("carried_over") or not given else pair["raw"],
            "raised": pair_flags(workspace, pair) if workspace is not None else [],
        })
    for key, given in draft.pair_verdicts.items():
        sid, chunk_id = key.split("|", 1)
        if key not in current and draft.sentence_edits.get(sid, {}).get("text", "") is None:
            rows.append({"sid": sid, "chunk_id": chunk_id, "n": None, "sentence": given["judged_text"],
                         "verdict": given["verdict"], "reason": given["reason"], "judged_at": given["judged_at"],
                         "judged_by": "researcher", "carried_over": False, "in_article": False,
                         "sentence_deleted": True, "raw": given["judged_text"]})
    for chunk_id in sorted(draft.removed):                # removed under a per-note verdict, before ADR 0008
        given = draft.verdicts.get(chunk_id, {})
        rows.append({"sid": None, "chunk_id": chunk_id, "n": None, "sentence": None, "verdict": given.get("verdict"),
                     "reason": given.get("reason", ""), "judged_at": given.get("judged_at"),
                     "judged_by": "researcher" if given else None, "carried_over": True, "in_article": False,
                     "sentences_removed": True})
    return rows


def set_verdict(draft: Draft, chunk_id: str, verdict: str, reason: str = "") -> None:
    if verdict not in VERDICTS:
        raise ArticleError(f"A verdict is one of: {', '.join(VERDICTS)}.")
    draft.verdicts[chunk_id] = {
        "verdict": verdict,
        "reason": reason.strip(),
        "judged_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def _unit(draft: Draft, sid: str):
    section = draft.sections[int(sid.split(".")[0])]
    return next(unit for unit in sentences.units(int(sid.split(".")[0]), assemble.base_text(section)) if unit.sid == sid)


def delete_sentence(draft: Draft, sid: str) -> None:
    """Take a sentence out of the article. The record keeps what it said."""
    original = draft.sentence_edits.get(sid, {}).get("original", _unit(draft, sid).text)
    draft.sentence_edits[sid] = {"text": None, "original": original, "edited_at": _now()}
    draft.own_words.pop(sid, None)


def edit_sentence(draft: Draft, sid: str, text: str) -> None:
    """Replace a sentence with the researcher's wording of it.

    The edit keeps the sentence's notes: the same markers, no more and no fewer.
    It is checked as the model's text was: no page number, no joined marker, no
    marker used as a word, quotation within its limits. An edit that fails is
    refused with the reason and nothing is changed. The record keeps the
    original; the verdict given on the old wording no longer stands.
    """
    index = int(sid.split(".")[0])
    unit = _unit(draft, sid)
    text = " ".join(text.split())
    problems = []
    if not text:
        raise ArticleError("An edited sentence cannot be empty. Delete the sentence instead.")
    if sorted(sentences.handles(text)) != sorted(sentences.handles(unit.text)):
        kept = " ".join(f"[{handle}]" for handle in sentences.handles(unit.text)) or "no marker"
        problems.append(f"the sentence must keep its markers exactly ({kept})")
    if ask.malformed_handles(text):
        problems.append("one marker per bracket, written as [E1]")
    if ask.PAGE_CLAIM_RE.findall(text):
        problems.append("no page number: pages come from the notes")
    if checks.handle_as_subject(text):
        problems.append("a marker closes its clause and is never a word of the sentence")
    if sentences.handles(unit.text) and any(not sentences.handles(part) for part in sentences.split(text)):
        problems.append("every sentence of the edit needs a marker of its own")
    section = draft.sections[index]
    body = " ".join(
        text if other.sid == sid else (draft.sentence_edits.get(other.sid, {}).get("text", other.text) or "")
        for other in sentences.units(index, assemble.base_text(section))
    )
    problems += [failure.split(":")[0].replace("_", " ") for failure in checks.quotation_failures(body)]
    if problems:
        raise ArticleError("This edit was not saved: " + "; ".join(problems) + ".")
    if text == unit.text:
        draft.sentence_edits.pop(sid, None)               # back to what the model wrote
    else:
        draft.sentence_edits[sid] = {"text": text, "original": unit.text, "edited_at": _now()}


def keep_as_own_words(draft: Draft, sid: str) -> None:
    """A sentence with no note may stay only as the researcher's own words. It is
    printed without a note and recorded with origin "researcher": no claim of
    support is made for it."""
    unit = _unit(draft, sid)
    current = draft.sentence_edits.get(sid, {}).get("text", unit.text)
    if current is None or sentences.handles(current):
        raise ArticleError("Only a sentence that carries no note can be kept as your own words.")
    draft.own_words[sid] = {"kept_at": _now()}


COMMENTARY_VERDICTS = ("accept", "reject")


def set_commentary_verdict(draft: Draft, section: int, verdict: str) -> None:
    """Commentary is the model's own reading. It is never accepted without the
    researcher saying so; rejected, it leaves the article and stays in the record."""
    if verdict not in COMMENTARY_VERDICTS:
        raise ArticleError(f"A commentary verdict is one of: {', '.join(COMMENTARY_VERDICTS)}.")
    draft.commentary_verdicts[section] = {
        "verdict": verdict, "judged_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


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


def _outcome_record(outcome: ask.QueryOutcome | None, error: str | None, pending: bool = False) -> dict:
    if pending:
        return {"pending": True}
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
        "article_check_failures": checks.prose_failures(outcome.result),
    }


def _frame_record(element: FrameElement | None) -> dict | None:
    if element is None:
        return None
    if element.origin == RESEARCHER:
        # The researcher's own words: kept so the article can be rebuilt; outside the support rate.
        return {"origin": RESEARCHER, "text": element.text}
    if element.origin == SUGGESTED:
        return {"origin": SUGGESTED, "text": element.text, "suggestion": element.suggestion,
                "edited_by_researcher": element.text != element.suggestion}
    return {"origin": GENERATED, "brief": element.brief, **_outcome_record(element.outcome, element.error)}


def voice_columns(article: assemble.Article, reference_text: str = "") -> dict:
    """Surface counts for the draft, sourced prose and commentary apart (§10)."""
    body = article.markdown.split("## Sources")[0].splitlines()
    label = assemble.COMMENTARY_LABEL
    commentary = "\n".join(line[len(label):] for line in body if line.startswith(label))
    sourced = "\n".join(line for line in body if line and not line.startswith(("#", "*", "- ", label)))
    columns = {"your writing": voice.measure(reference_text)} if reference_text.strip() else {}
    columns["draft, whole"] = voice.measure(sourced + "\n" + commentary)
    columns["draft, sourced"] = voice.measure(sourced)
    columns["draft, commentary"] = voice.measure(commentary)
    return columns


def build_record(workspace: Workspace, draft: Draft, article: assemble.Article, reference_text: str = "") -> dict:
    cut = workspace.sources.removed
    notes = notes_record(draft, article)
    pairs = pairs_record(draft, article, workspace)
    commentary = {entry["section"]: entry for entry in article.commentary}

    def commentary_record(index: int) -> dict | None:
        entry = commentary.get(index)
        if entry is None:
            return None
        given = draft.commentary_verdicts.get(index, {})
        return {"printed": entry["printed"], "items_held_back": entry["held_back"], "raised": entry["flags"],
                "verdict": given.get("verdict"), "judged_at": given.get("judged_at"),
                "judged_by": "researcher" if given else None}

    def section_record(section: SectionDraft) -> dict:
        retrieved = [item.chunk["chunk_id"] for item in section.outcome.items] if section.outcome else []
        answer = (section.outcome.result.get("answer") or "") if section.outcome else ""
        return {
            "heading": section.heading,
            "brief": section.brief,
            "kept_by_researcher": section.kept,
            "gap_stated": section.state_gap,
            "blocked": None if section.pending else assemble.block_reason(section.outcome, section.error),
            # The one limit printed for this section, as printed; every limitation
            # and gap the model gave is in `result` below.
            "limitation_printed": article.limits_printed.get(section.heading),
            "commentary": commentary_record(draft.sections.index(section)),
            "editorial": section.editorial,
            "footnote_text_cut_from": [chunk_id for chunk_id in retrieved if chunk_id in cut],
            "voice": voice.measure(answer) if answer else None,
            **_outcome_record(section.outcome, section.error, section.pending),
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
        # Every prompt that shaped this article, by file and hash. The system prompt's
        # own hash is on each section, as on every answer.
        "prompts": {
            checks.SECTION_PROMPT: checks.load_prompt(checks.SECTION_PROMPT)[1],
            **({checks.EDITORIAL_PROMPT: checks.load_prompt(checks.EDITORIAL_PROMPT)[1]}
               if any(section.editorial for section in draft.sections) else {}),
            **({checks.FRAME_PROMPT: checks.load_prompt(checks.FRAME_PROMPT)[1]} if draft.frame_suggestions else {}),
        },
        "title": {"origin": RESEARCHER, "text": draft.title},
        "topic": draft.topic,
        "commentary_switched_on": draft.commentary,
        "plan": {"frame": draft.frame_plan, "editorial": draft.editorial, "voice_exemplar": draft.voice_exemplar},
        "drafting": {"complete": draft.complete, "frame_steps_done": sorted(draft.frame_done),
                     "model_calls_remaining": planned_calls(draft)["model_calls"]},
        "sections": [section_record(section) for section in draft.sections],
        "frame": {
            "introduction": _frame_record(draft.introduction),
            "transitions": [_frame_record(element) for element in draft.transitions],
            "conclusion": _frame_record(draft.conclusion),
        },
        "frame_suggestions": draft.frame_suggestions,
        "blocked": article.blocked,
        "frame_sentences_without_a_note": article.unnoted,
        "limitations_kept_in_record_only": article.limits_held_back,
        # Raised for the researcher to read side by side; nothing is decided from it (ADR 0009).
        "terms_used_in_more_than_one_section": terms.as_record(terms.shared_terms(article.pairs, article.own_words)),
        "export": {"ready": not export_blockers(draft, article), "blocked_by": export_blockers(draft, article)},
        "sentences": {
            "held_back_without_a_note": article.held_back,
            "kept_as_own_words": [{**entry, "origin": RESEARCHER, **draft.own_words[entry["sid"]]}
                                  for entry in article.own_words],
            "edits": {sid: {**edit, "edited_by": RESEARCHER} for sid, edit in draft.sentence_edits.items()},
        },
        "em_dashes_in_print": em_dashes(draft),
        "notes": notes,
        # One row per sentence and note it carries: the unit the researcher judges (ADR 0008).
        "pairs": pairs,
        # Verdicts are counted per pair; "notes" is how many distinct notes those pairs carry.
        "support": {**assemble.support_rate(pairs), "notes": len({row["chunk_id"] for row in pairs})},
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
    record = build_record(workspace, draft, article, reference_text)
    # Written beside the file and then moved into place, so a restart in the middle of
    # a save leaves the last whole record, never half of one.
    for name, text in (("article.md", article.markdown),
                       ("record.json", json.dumps(record, ensure_ascii=False, indent=1))):
        partial = folder / f"{name}.partial"
        partial.write_text(text, encoding="utf-8")
        partial.replace(folder / name)
    return folder


# ---------------------------------------------------------------------------
# Loading a saved draft back
# ---------------------------------------------------------------------------


def _outcome_from(record: dict, brief: str, workspace: Workspace) -> tuple[ask.QueryOutcome | None, str | None]:
    if record.get("pending"):
        return None, None
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
    if record["origin"] == SUGGESTED:
        return FrameElement(SUGGESTED, text=record.get("text", ""), suggestion=record.get("suggestion", ""))
    outcome, error = _outcome_from(record, record["brief"], workspace)
    return FrameElement(GENERATED, brief=record["brief"], outcome=outcome, error=error)


def load(folder: Path, workspace: Workspace) -> Draft:
    """Rebuild a draft from its record. No model is called."""
    record = json.loads((Path(folder) / "record.json").read_text(encoding="utf-8"))
    if record.get("schema_version") not in READABLE_SCHEMAS:
        raise ArticleError("This article was saved by an earlier version and cannot be reopened.")
    if record["document_id"] != workspace.document.document_id:
        raise ArticleError(f"This article was drafted from {record['document_id']}, not the thesis now open.")
    if record["corpus_text_sha256"] != workspace.manifest.get("corpus_text_sha256"):
        raise ArticleError("The index has changed since this article was drafted; its notes can no longer be trusted.")
    sections = []
    for entry in record["sections"]:
        outcome, error = _outcome_from(entry, entry["brief"], workspace)
        editorial = entry.get("editorial")
        sections.append(SectionDraft(
            entry["heading"], entry["brief"], outcome, error,
            kept=entry["kept_by_researcher"], state_gap=entry["gap_stated"], editorial=editorial,
            pending=bool(entry.get("pending")),
            prose=editorial["result"]["answer"] if editorial and editorial["accepted"] else None))
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
        pair_verdicts={
            f"{row['sid']}|{row['chunk_id']}": {"verdict": row["verdict"], "reason": row["reason"],
                                                "judged_at": row["judged_at"], "judged_text": row["raw"]}
            for row in record.get("pairs", []) if row.get("verdict") and row.get("raw") is not None
        },
        sentence_edits={sid: {key: edit[key] for key in ("text", "original", "edited_at")}
                        for sid, edit in record.get("sentences", {}).get("edits", {}).items()},
        own_words={entry["sid"]: {"kept_at": entry["kept_at"]}
                   for entry in record.get("sentences", {}).get("kept_as_own_words", [])},
        commentary=record.get("commentary_switched_on", False),
        commentary_verdicts={
            index: {"verdict": entry["commentary"]["verdict"], "judged_at": entry["commentary"]["judged_at"]}
            for index, entry in enumerate(record["sections"])
            if (entry.get("commentary") or {}).get("verdict")
        },
        article_id=record["article_id"],
        created=record["created"],
        frame_suggestions={kind: list(asked) for kind, asked in record.get("frame_suggestions", {}).items()},
        frame_plan=dict(record.get("plan", {}).get("frame", {})),
        editorial=record.get("plan", {}).get("editorial", False),
        voice_exemplar=record.get("plan", {}).get("voice_exemplar", ""),
        frame_done=set(record.get("drafting", {}).get("frame_steps_done", [])),
        complete=record.get("drafting", {}).get("complete", True),
    )


def saved_articles(out_dir: Path | None = None, document_id: str | None = None) -> list[dict]:
    """Saved articles, newest first: id, title, status, support counts. No article text."""
    out_dir = Path(out_dir or DEFAULT_OUT_DIR)
    rows = []
    for path in sorted(out_dir.glob("*/record.json"), reverse=True) if out_dir.exists() else []:
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("schema_version") not in READABLE_SCHEMAS:
            continue
        if document_id and record.get("document_id") != document_id:
            continue
        rows.append({"article_id": record["article_id"], "title": record["title"]["text"],
                     "status": record["status"], "support": record["support"], "folder": path.parent,
                     "model_calls_remaining": record.get("drafting", {}).get("model_calls_remaining", 0)})
    return rows
