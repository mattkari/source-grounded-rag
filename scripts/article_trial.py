"""Sprint W0 trial of the article writer — PLAN_V6 §12. Command line only.

    python scripts/article_trial.py --topics
    python scripts/article_trial.py --chapter 9 --title "My title" --reference my_post.md

`--topics` lists what the built-in thesis covers, from its index, with no model
call. With `--chapter` and `--title` it drafts ONE assembled article of three
sections with its frame, so it can be read as a whole article, and prints:

  * the voice measures of the draft beside those of your own writing
    (`--reference`, one or more files of your published prose);
  * how many of the passages it drew on contain footnote text;
  * what was blocked, and why.

Drafting spends API credit: one embedding call and one model call per section,
plus one model call for each generated frame element. Nothing is retried.

Writes `output/articles/<id>/article.md` and `record.json`. `output/` is ignored
by git. This is a trial: the article is marked DRAFT and nothing is published.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import ask  # noqa: E402
from article import assemble, footnotes, topics, voice  # noqa: E402
from article.assemble import GENERATED, RESEARCHER, FrameElement, SectionDraft  # noqa: E402
from documents import default_document  # noqa: E402

DEFAULT_OUT_DIR = ROOT / "output" / "articles"
SECTIONS = 3


def _cited(outcome: ask.QueryOutcome) -> list[ask.EvidenceItem]:
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


def _draft(call, *args) -> tuple[ask.QueryOutcome | None, str | None]:
    try:
        return call(*args), None
    except (Exception, SystemExit) as exc:  # recorded, never retried (hard rule 9)
        return None, f"{type(exc).__name__}: {' '.join(str(exc).split())[:300]}"


def _generated(brief: str, items: list[ask.EvidenceItem]) -> FrameElement:
    if not items:
        return FrameElement(GENERATED, brief=brief, error="no cited passages to draw on")
    outcome, error = _draft(ask.draft_from_evidence, brief, _rehandle(items))
    return FrameElement(GENERATED, brief=brief, outcome=outcome, error=error)


def _outcome_record(outcome: ask.QueryOutcome | None, error: str | None) -> dict:
    if outcome is None:
        return {"error": error}
    return {
        "prompt_sha256_12": outcome.prompt_hash,
        "evidence": [{"handle": i.handle, "chunk_id": i.chunk["chunk_id"]} for i in outcome.items],
        "result": outcome.result,
        "validation_failures": list(outcome.failures),
    }


def run_trial(*, chapter: int, title: str, briefs: list[str], headings: list[str] | None, frame: str,
              references: list[Path], out_dir: Path, stream=None) -> int:
    stream = stream or sys.stdout
    document = default_document(ask.settings)
    vectors, chunks, manifest = ask.load_index(document)
    listed = topics.list_topics(chunks)
    if not 1 <= chapter <= len(listed):
        print(f"There is no chapter {chapter}. Run with --topics to see the list.", file=stream)
        return 2
    topic = listed[chapter - 1]

    if not briefs:
        briefs = topics.default_briefs(topic, SECTIONS)
        ranked = sorted(topic.sections, key=lambda s: -s.passages)[:SECTIONS]
        headings = [s.title for s in topic.sections if s in ranked]
    if len(briefs) != SECTIONS:
        print(f"The trial drafts exactly {SECTIONS} sections; {len(briefs)} brief(s) were given "
              f"(this chapter has {len(topic.sections)} printed sections).", file=stream)
        return 2
    headings = headings or [brief.rstrip("?") for brief in briefs]

    print(f"Topic: {topic.chapter} ({topic.passages} passages, {topic.pages})", file=stream)
    sections: list[SectionDraft] = []
    for heading, brief in zip(headings, briefs):
        outcome, error = _draft(ask.run_query, brief, vectors, chunks, None, document)
        sections.append(SectionDraft(heading, brief, outcome, error))
        state = assemble.block_reason(outcome, error) or "drafted"
        print(f"  section: {heading} -> {state}", file=stream)

    usable = [s for s in sections if not assemble.block_reason(s.outcome, s.error)]
    introduction = conclusion = None
    transitions: list[FrameElement | None] = [None] * (len(sections) - 1)
    if frame == GENERATED and usable:
        everything = [item for s in usable for item in _cited(s.outcome)]
        introduction = _generated(
            f"In two or three sentences for a general reader, introduce what these passages together "
            f"show about: {title}. Use only what the passages say.", everything)
        for index in range(1, len(sections)):
            before, after = sections[index - 1], sections[index]
            if before in usable and after in usable:
                transitions[index - 1] = _generated(
                    f"In one sentence, connect “{before.heading}” to “{after.heading}”, "
                    "using only what the passages say.",
                    _cited(before.outcome) + _cited(after.outcome))
        conclusion = _generated(
            f"In two or three sentences, say what these passages together establish about: {title}, "
            "and what they leave open. Use only what the passages say.", everything)

    article = assemble.assemble(title=title, document=document, sections=sections,
                                introduction=introduction, transitions=transitions, conclusion=conclusion)

    # --- footnote text in what was drawn on (PLAN_V6 §7; counted here, filtered in W1) ---
    footnote_map = footnotes.build(document) if document.pdf_path.exists() else None
    retrieved = {i.chunk["chunk_id"]: i.chunk for s in sections if s.outcome for i in s.outcome.items}
    cited_ids = {note["chunk_id"] for note in article.notes}
    footnote_report = None
    if footnote_map is not None:
        touched = set(footnotes.touched(list(retrieved.values()), footnote_map))
        footnote_report = {
            "footnotes_in_document": footnote_map.count,
            "unclear_foot_blocks": footnote_map.unclear,
            "passages_retrieved": len(retrieved),
            "retrieved_containing_footnote_text": len(touched),
            "passages_cited": len(cited_ids),
            "cited_containing_footnote_text": len(touched & cited_ids),
        }

    # --- voice (PLAN_V6 §10) ---
    columns = {}
    if references:
        columns["your writing"] = voice.measure("\n".join(p.read_text(encoding="utf-8") for p in references))
    body = article.markdown.split("## Sources")[0].splitlines()
    commentary = "\n".join(l[len(assemble.COMMENTARY_LABEL):] for l in body if l.startswith(assemble.COMMENTARY_LABEL))
    sourced = "\n".join(l for l in body if l and not l.startswith(("#", "*", assemble.COMMENTARY_LABEL)))
    columns["draft, whole"] = voice.measure(sourced + "\n" + commentary)
    columns["draft, sourced"] = voice.measure(sourced)
    columns["draft, commentary"] = voice.measure(commentary)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    folder, attempt = out_dir / f"trial_{stamp}", 1
    while folder.exists():                      # a second trial in the same second: never overwrite
        attempt += 1
        folder = out_dir / f"trial_{stamp}_{attempt}"
    folder.mkdir(parents=True)
    (folder / "article.md").write_text(article.markdown, encoding="utf-8")

    def frame_record(element: FrameElement | None) -> dict | None:
        if element is None:
            return None
        if element.origin == RESEARCHER:
            return {"origin": RESEARCHER}
        return {"origin": GENERATED, "brief": element.brief, **_outcome_record(element.outcome, element.error)}

    record = {
        "schema_version": 1,
        "kind": "w0_trial",
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": "draft",
        "document_id": document.document_id,
        "corpus_text_sha256": manifest.get("corpus_text_sha256"),
        "model": ask.settings.llm_model,
        "provider": ask.settings.llm_provider,
        "title": {"origin": RESEARCHER, "text": title},
        "topic": {"chapter": topic.chapter, "passages": topic.passages, "pages": topic.pages},
        "sections": [
            {"heading": s.heading, "brief": s.brief, "blocked": assemble.block_reason(s.outcome, s.error),
             **_outcome_record(s.outcome, s.error)}
            for s in sections
        ],
        "frame": {"introduction": frame_record(introduction),
                  "transitions": [frame_record(t) for t in transitions],
                  "conclusion": frame_record(conclusion)},
        "blocked": article.blocked,
        "notes": article.notes,
        "support": assemble.support_rate(article.notes),
        "footnotes": footnote_report,
        "voice": columns,
    }
    (folder / "record.json").write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\nArticle : {folder / 'article.md'}", file=stream)
    print(f"Record  : {folder / 'record.json'}", file=stream)
    if article.blocked:
        print("\nBLOCKED (left out of the article; nothing was retried)", file=stream)
        for item in article.blocked:
            print(f"  - {item['what']}: {item['reason']}", file=stream)
    if footnote_report:
        print(f"\nFOOTNOTE TEXT (not yet filtered — that is Sprint W1)\n"
              f"  passages cited that contain footnote text : "
              f"{footnote_report['cited_containing_footnote_text']}/{footnote_report['passages_cited']}\n"
              f"  passages retrieved that contain it        : "
              f"{footnote_report['retrieved_containing_footnote_text']}/{footnote_report['passages_retrieved']}",
              file=stream)
    print("\nVOICE (surface counts; no score, no verdict)", file=stream)
    print(voice.format_comparison(columns), file=stream)
    if not references:
        print("  No --reference file was given, so there is nothing of yours to compare with.", file=stream)
    print(f"\nNotes to check: {len(article.notes)}. Read the article as a whole before judging it.", file=stream)
    return 0 if len(usable) == len(sections) else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="W0 trial of the article writer (PLAN_V6).")
    parser.add_argument("--topics", action="store_true", help="list what the thesis covers; no model call")
    parser.add_argument("--chapter", type=int, help="number of the chapter to write about, from --topics")
    parser.add_argument("--title", help="the article's title, in your words")
    parser.add_argument("--brief", action="append", default=[], metavar="QUESTION",
                        help="a section brief; give three, or none to use the chapter's own section titles")
    parser.add_argument("--frame", choices=[GENERATED, "none"], default=GENERATED,
                        help="generate the introduction, transitions and conclusion as labelled commentary, or leave them out")
    parser.add_argument("--reference", action="append", default=[], type=Path, metavar="FILE",
                        help="a file of your own published writing, for the voice comparison")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args(argv)

    if args.topics:
        document = default_document(ask.settings)
        _, chunks, _ = ask.load_index(document)
        print(topics.format_topics(topics.list_topics(chunks)))
        return 0
    if args.chapter is None or not args.title:
        parser.error("give --topics, or both --chapter and --title")
    missing = [str(p) for p in args.reference if not p.exists()]
    if missing:
        print(f"No such reference file: {', '.join(missing)}", file=sys.stderr)
        return 2
    return run_trial(chapter=args.chapter, title=args.title, briefs=args.brief, headings=None,
                     frame=args.frame, references=args.reference, out_dir=args.out_dir)


if __name__ == "__main__":
    raise SystemExit(main())
