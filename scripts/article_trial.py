"""Draft an article from the command line — PLAN_V6, Sprints W0 and W1.

    python scripts/article_trial.py --topics
    python scripts/article_trial.py --sources
    python scripts/article_trial.py --chapter 9 --title "My title" --reference my_post.md

`--topics` lists what the built-in thesis covers and `--sources` shows what the
footnote and reference filter leaves to draft from. Neither calls a model.

With `--chapter` and `--title` it drafts ONE assembled article, sections and
frame, to be read as a whole article, and prints:

  * the voice measures of the draft beside those of your own writing
    (`--reference`, one or more files of your published prose);
  * what the source filter removed, and what was blocked and why.

Drafting spends API credit: one embedding call and one model call per section,
plus one model call for each generated frame element. Nothing is retried.

Writes `output/articles/<id>/article.md` and `record.json`. `output/` is ignored
by git. The article is marked DRAFT until every note has been judged, which is
done in the web app's "Write an article" view. Nothing is published.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from article import assemble, pipeline, sources, topics, voice  # noqa: E402
from article.assemble import GENERATED  # noqa: E402

DEFAULT_SECTIONS = 3


def _open(stream) -> pipeline.Workspace | None:
    try:
        return pipeline.open_workspace()
    except sources.NoFootnoteMap as exc:
        print(str(exc), file=stream)
        return None


def run_trial(*, chapter: int, title: str, briefs: list[str], headings: list[str] | None, frame: str,
              references: list[Path], out_dir: Path, stream=None) -> int:
    stream = stream or sys.stdout
    workspace = _open(stream)
    if workspace is None:
        return 2
    listed = workspace.topics()
    if not 1 <= chapter <= len(listed):
        print(f"There is no chapter {chapter}. Run with --topics to see the list.", file=stream)
        return 2
    topic = listed[chapter - 1]

    if not briefs:
        briefs = topics.default_briefs(topic, DEFAULT_SECTIONS)
        ranked = sorted(topic.sections, key=lambda s: -s.passages)[:DEFAULT_SECTIONS]
        headings = [s.title for s in topic.sections if s in ranked]
    headings = headings or [brief.rstrip("?") for brief in briefs]
    try:
        pipeline.check_outline(title, list(zip(headings, briefs)))
    except pipeline.ArticleError as exc:
        print(f"{exc} (This chapter has {len(topic.sections)} printed sections.)", file=stream)
        return 2

    print(f"Topic: {topic.chapter} ({topic.passages} passages, {topic.pages})", file=stream)
    drafted = []
    for heading, brief in zip(headings, briefs):
        section = pipeline.draft_section(workspace, heading, brief)
        drafted.append(section)
        print(f"  section: {heading} -> {assemble.block_reason(section.outcome, section.error) or 'drafted'}",
              file=stream)

    draft = pipeline.Draft(title=title, sections=drafted, topic=topic.chapter,
                           transitions=[None] * (len(drafted) - 1))
    if frame == GENERATED and any(pipeline.usable(s) for s in drafted):
        draft.introduction = pipeline.draft_introduction(title, drafted)
        draft.transitions = [pipeline.draft_transition(a, b) for a, b in zip(drafted, drafted[1:])]
        draft.conclusion = pipeline.draft_conclusion(title, drafted)

    reference_text = "\n".join(path.read_text(encoding="utf-8") for path in references)
    folder = pipeline.save(workspace, draft, out_dir, reference_text)
    article = pipeline.render(workspace, draft)

    print(f"\nArticle : {folder / 'article.md'}", file=stream)
    print(f"Record  : {folder / 'record.json'}", file=stream)
    if article.blocked:
        print("\nBLOCKED (left out of the article; nothing was retried)", file=stream)
        for item in article.blocked:
            print(f"  - {item['what']}: {item['reason']}", file=stream)
    for item in article.unnoted:
        print(f"\nCHECK: the generated {item['what']} has {item['sentences']} sentence(s) with no note. "
              "Make sure they add no fact of their own.", file=stream)
    print("\nSOURCE FILTER (footnotes and the reference list are never drafted from)", file=stream)
    for line in workspace.sources.report.lines():
        print(f"  {line}", file=stream)
    print("\nVOICE (surface counts; no score, no verdict)", file=stream)
    print(voice.format_comparison(pipeline.voice_columns(article, reference_text)), file=stream)
    if not references:
        print("  No --reference file was given, so there is nothing of yours to compare with.", file=stream)
    print(f"\nNotes to check: {len(article.notes)}. Read the article as a whole before judging it.", file=stream)
    return 0 if all(pipeline.usable(s) for s in drafted) else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Draft an article from the built-in thesis (PLAN_V6).")
    parser.add_argument("--topics", action="store_true", help="list what the thesis covers; no model call")
    parser.add_argument("--sources", action="store_true",
                        help="show what the footnote and reference filter leaves to draft from; no model call")
    parser.add_argument("--chapter", type=int, help="number of the chapter to write about, from --topics")
    parser.add_argument("--title", help="the article's title, in your words")
    parser.add_argument("--brief", action="append", default=[], metavar="QUESTION",
                        help=f"a section brief; give {pipeline.MIN_SECTIONS} to {pipeline.MAX_SECTIONS}, "
                             "or none to use the chapter's own section titles")
    parser.add_argument("--frame", choices=[GENERATED, "none"], default=GENERATED,
                        help="generate the introduction, transitions and conclusion as labelled commentary, or leave them out")
    parser.add_argument("--reference", action="append", default=[], type=Path, metavar="FILE",
                        help="a file of your own published writing, for the voice comparison")
    parser.add_argument("--out-dir", type=Path, default=pipeline.DEFAULT_OUT_DIR)
    args = parser.parse_args(argv)

    if args.topics or args.sources:
        workspace = _open(sys.stdout)
        if workspace is None:
            return 2
        print(topics.format_topics(workspace.topics()) if args.topics
              else "\n".join(workspace.sources.report.lines()))
        return 0
    if args.chapter is None or not args.title:
        parser.error("give --topics, --sources, or both --chapter and --title")
    missing = [str(p) for p in args.reference if not p.exists()]
    if missing:
        print(f"No such reference file: {', '.join(missing)}", file=sys.stderr)
        return 2
    return run_trial(chapter=args.chapter, title=args.title, briefs=args.brief, headings=None,
                     frame=args.frame, references=args.reference, out_dir=args.out_dir)


if __name__ == "__main__":
    raise SystemExit(main())
