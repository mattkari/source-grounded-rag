"""Draft an article from a thesis, from the command line — PLAN_V6, ADR 0005.

    python write_article.py --topics
    python write_article.py --title "My title" --outline outline.txt --dry-run
    python write_article.py --title "My title" --outline outline.txt
    python write_article.py --title "My title" --outline outline.txt --editorial --frame generate
    python write_article.py --resume <article-id>
    python write_article.py --list

The outline file has one section per line: `Heading | the question the section
must answer`. Three to six sections.

This is a shell, not a pipeline. It plans a draft and hands it to
`article.pipeline.run`, the same code the web app's "Write an article" view
uses, and it writes the same `output/articles/<id>/article.md` and
`record.json`. The record is saved after every step, so an interrupted draft
can be finished with `--resume`: completed sections are not sent again.

`--dry-run` calls no model and embeds nothing. It prints the calls the plan
would make and an upper estimate of their tokens, and a cost only if the prices
are configured (`LLM_PRICE_INPUT_PER_MTOK`, `LLM_PRICE_OUTPUT_PER_MTOK`).

The article is a DRAFT until every note has the researcher's verdict, which is
given in the web app. Nothing is published.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import ask
import upload
from article import assemble, checks, pipeline, sources, topics, voice

GENERATE, NONE = "generate", "none"
CHARS_PER_TOKEN = 4          # a rough rule for prompt text; the provider's own count will differ


def parse_outline(text: str) -> list[tuple[str, str]]:
    outline = []
    for line in text.splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            heading, _, brief = line.partition("|")
            outline.append((heading.strip(), brief.strip()))
    return outline


def _origin(choice: str, text_file: Path | None) -> tuple[str, str]:
    if text_file is not None:
        return pipeline.RESEARCHER, text_file.read_text(encoding="utf-8")
    return (pipeline.GENERATED if choice == GENERATE else "none"), ""


def estimate(workspace: pipeline.Workspace, draft: pipeline.Draft) -> dict:
    """Calls the plan still needs, and an upper estimate of their tokens. No call is made."""
    calls = pipeline.planned_calls(draft)
    settings = ask.settings
    prompt_tokens = len(ask._get_prompt()[0]) // CHARS_PER_TOKEN
    rules_tokens = len(checks.load_prompt(checks.SECTION_PROMPT)[0]) // CHARS_PER_TOKEN
    editor_tokens = len(checks.load_prompt(checks.EDITORIAL_PROMPT)[0]) // CHARS_PER_TOKEN
    largest = sorted((chunk.get("token_count", 0) for chunk in workspace.sources.chunks), reverse=True)
    evidence_tokens = sum(largest[: settings.top_k])
    per_call = prompt_tokens + evidence_tokens + max(rules_tokens, editor_tokens) + settings.llm_max_tokens // 8
    tokens_in, tokens_out = calls["model_calls"] * per_call, calls["model_calls"] * settings.llm_max_tokens
    price_in, price_out = settings.llm_price_input_per_mtok, settings.llm_price_output_per_mtok
    priced = price_in is not None and price_out is not None
    return {
        **calls,
        "input_tokens_upper_estimate": tokens_in,
        "output_tokens_upper_bound": tokens_out,
        "cost_upper_estimate_usd": round((tokens_in * price_in + tokens_out * price_out) / 1_000_000, 4) if priced else None,
    }


def print_estimate(numbers: dict, stream) -> None:
    print("PLANNED CALLS (nothing has been sent)", file=stream)
    for label, key in (("sections", "sections"), ("editorial rewrites, at most", "editorial"),
                       ("introduction", "introduction"), ("transitions, at most", "transitions"),
                       ("conclusion", "conclusion")):
        print(f"  {label:<28} {numbers[key]}", file=stream)
    print(f"  {'model calls in all':<28} {numbers['model_calls']}", file=stream)
    print(f"  {'embedding calls':<28} {numbers['embedding_calls']}  (one question each)", file=stream)
    print(f"  {'input tokens, upper estimate':<28} {numbers['input_tokens_upper_estimate']:,}", file=stream)
    print(f"  {'output tokens, upper bound':<28} {numbers['output_tokens_upper_bound']:,}", file=stream)
    if numbers["cost_upper_estimate_usd"] is None:
        print("  No price is configured (LLM_PRICE_INPUT_PER_MTOK, LLM_PRICE_OUTPUT_PER_MTOK), so no cost is shown.",
              file=stream)
    else:
        print(f"  {'cost, upper estimate':<28} ${numbers['cost_upper_estimate_usd']:.4f}", file=stream)
    print("  These are ceilings, not forecasts: a real section uses far fewer output tokens.", file=stream)


def report(workspace: pipeline.Workspace, draft: pipeline.Draft, folder: Path, reference_text: str, stream) -> int:
    article = pipeline.render(workspace, draft)
    print(f"\nArticle : {folder / 'article.md'}", file=stream)
    print(f"Record  : {folder / 'record.json'}", file=stream)
    if article.blocked:
        print("\nBLOCKED (left out of the article; nothing was sent again)", file=stream)
        for item in article.blocked:
            print(f"  - {item['what']}: {item['reason']}", file=stream)
    edited = [section for section in draft.sections if section.editorial]
    if edited:
        print("\nEDITORIAL PASS", file=stream)
        for section in edited:
            outcome = section.editorial
            print(f"  - {section.heading}: " + ("rewrite kept" if outcome["accepted"]
                                               else "rewrite REJECTED, the original stands"), file=stream)
            for reason in outcome["rejected_because"]:
                print(f"      {reason}", file=stream)
            if outcome["voice_after"]:
                before, after = outcome["voice_before"], outcome["voice_after"]
                print(f"      connectives per 1,000 words {before['connectives_per_1000_words']} -> "
                      f"{after['connectives_per_1000_words']}; em dashes {before['em_dashes']} -> {after['em_dashes']}",
                      file=stream)
    for item in article.unnoted:
        print(f"\nCHECK: the generated {item['what']} has {item['sentences']} sentence(s) with no note.", file=stream)
    for entry in article.commentary:
        for flag in entry["flags"]:
            print(f"\nCHECK who acts in the commentary of “{entry['heading']}”: it {flag}.", file=stream)
    if article.limits_held_back:
        print(f"\n{article.limits_held_back} limitation line(s) are kept in the record only.", file=stream)
    for heading, count in pipeline.em_dashes(draft).items():
        print(f"\nEM DASHES: “{heading}” prints {count} (target 0). They are left as written; "
              "replace them by hand if you wish.", file=stream)
    columns = pipeline.voice_columns(article, reference_text)
    print("\nVOICE (plain counts; no score)", file=stream)
    print(voice.format_comparison(columns), file=stream)
    for check in voice.profile_checks(columns["draft, sourced"]):
        print(f"  {check['check']}: {check['value']} (target {check['target']}) -> "
              f"{'met' if check['met'] else 'NOT met'}", file=stream)
    print(f"\nNotes to check in the web app: {len(article.notes)}. The article is a DRAFT until they are judged.",
          file=stream)
    return 0 if all(pipeline.usable(section) for section in draft.sections if section.kept) else 1


def main(argv: list[str] | None = None, stream=None) -> int:
    stream = stream or sys.stdout
    parser = argparse.ArgumentParser(description="Draft an article from a thesis (PLAN_V6).")
    parser.add_argument("--topics", action="store_true", help="list what the thesis covers; no model call")
    parser.add_argument("--sources", action="store_true", help="show what the footnote filter leaves; no model call")
    parser.add_argument("--list", action="store_true", help="list saved articles and whether they are finished")
    parser.add_argument("--export", metavar="ARTICLE_ID",
                        help="write the reviewed article as medium.md and medium.html; no model call. Refused, with "
                             "the reasons, until every sentence is judged")
    parser.add_argument("--resume", metavar="ARTICLE_ID", help="finish an interrupted draft; finished steps are not sent again")
    parser.add_argument("--title", help="the article's title, in your words")
    parser.add_argument("--outline", type=Path, metavar="FILE", help="one section per line: Heading | question")
    parser.add_argument("--from-record", type=Path, metavar="RECORD_JSON",
                        help="take the title and outline from an earlier article's record.json")
    parser.add_argument("--frame", choices=[GENERATE, NONE], default=NONE,
                        help="introduction, transitions and conclusion: generate as labelled commentary, or leave out (default)")
    parser.add_argument("--introduction-file", type=Path, metavar="FILE", help="your own introduction")
    parser.add_argument("--conclusion-file", type=Path, metavar="FILE", help="your own conclusion")
    parser.add_argument("--commentary", action="store_true", help="print the model's commentary (one paragraph a section; needs your verdict)")
    parser.add_argument("--editorial", action="store_true", help="one more call per section to rewrite it for flow; kept only if it preserves")
    parser.add_argument("--reference", action="append", default=[], type=Path, metavar="FILE",
                        help="a file of your own published writing, for the voice comparison")
    parser.add_argument("--document", metavar="ID", help="an approved uploaded thesis; default is the built-in one")
    parser.add_argument("--preview", action="store_true",
                        help="show which passages each section's question would draw on, with pages and scores; "
                             "one embedding call per section and no model call")
    parser.add_argument("--dry-run", action="store_true", help="print the planned calls and their cost ceiling; send nothing")
    parser.add_argument("--out-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    out_dir = args.out_dir or pipeline.DEFAULT_OUT_DIR

    if args.list:
        for row in pipeline.saved_articles(out_dir):
            state = (f"unfinished, {row['model_calls_remaining']} model call(s) left"
                     if row["status"] == pipeline.DRAFTING else row["status"])
            print(f"{row['article_id']}  {state}  {row['title']}", file=stream)
        return 0

    try:
        # The built-in thesis comes from the one settings object; an upload from the library.
        workspace = pipeline.open_workspace(upload.find_document(args.document) if args.document else None)
    except (sources.NoFootnoteMap, upload.UploadRefused) as exc:
        print(str(exc), file=stream)
        return 2
    if args.topics or args.sources:
        print(topics.format_topics(workspace.topics()) if args.topics
              else "\n".join(workspace.sources.report.lines()), file=stream)
        return 0

    if args.export:
        folder = out_dir / args.export
        if not (folder / "record.json").exists():
            print(f"There is no saved article {args.export}. Run with --list to see them.", file=stream)
            return 2
        try:
            exported = pipeline.export(workspace, pipeline.load(folder, workspace))
        except pipeline.ArticleError as exc:
            print(str(exc), file=stream)
            return 1
        (folder / "medium.md").write_text(exported["markdown"], encoding="utf-8")
        (folder / "medium.html").write_text(exported["html"], encoding="utf-8")
        print(f"Markdown: {folder / 'medium.md'}\nHTML    : {folder / 'medium.html'}", file=stream)
        return 0

    missing = [str(path) for path in [args.outline, args.from_record, args.introduction_file, args.conclusion_file,
                                      *args.reference] if path is not None and not path.exists()]
    if missing:
        print(f"No such file: {', '.join(missing)}", file=stream)
        return 2
    reference_text = "\n".join(path.read_text(encoding="utf-8") for path in args.reference)

    try:
        if args.resume:
            folder = out_dir / args.resume
            if not (folder / "record.json").exists():
                print(f"There is no saved article {args.resume}. Run with --list to see them.", file=stream)
                return 2
            draft = pipeline.load(folder, workspace)
        else:
            title, outline = args.title, parse_outline(args.outline.read_text(encoding="utf-8")) if args.outline else []
            if args.from_record:
                earlier = json.loads(args.from_record.read_text(encoding="utf-8"))
                title = title or earlier["title"]["text"]
                outline = outline or [(section["heading"], section["brief"]) for section in earlier["sections"]]
            if not title or not outline:
                parser.error("give --title and --outline, or --from-record, or --resume")
            introduction, introduction_text = _origin(args.frame, args.introduction_file)
            conclusion, conclusion_text = _origin(args.frame, args.conclusion_file)
            draft = pipeline.new_draft(
                title, outline, commentary=args.commentary, editorial=args.editorial,
                introduction=introduction, introduction_text=introduction_text,
                transitions=pipeline.GENERATED if args.frame == GENERATE else "none",
                conclusion=conclusion, conclusion_text=conclusion_text,
            )
    except pipeline.ArticleError as exc:
        print(str(exc), file=stream)
        return 2

    print(f"Title   : {draft.title}", file=stream)
    for number, section in enumerate(draft.sections, start=1):
        print(f"  {number}. {section.heading}" + ("" if section.pending else "  (already drafted)"), file=stream)
    print_estimate(estimate(workspace, draft), stream)
    if args.preview:
        pending = [section.brief for section in draft.sections if section.pending]
        print("\n" + pipeline.format_preview([pipeline.preview(workspace, brief) for brief in pending]), file=stream)
    if args.dry_run:
        return 0

    print("\nDRAFTING (each finished step is saved)", file=stream)
    pipeline.run(workspace, draft, out_dir, reference_text, on_step=lambda what: print(f"  saved: {what}", file=stream))
    return report(workspace, draft, out_dir / draft.article_id, reference_text, stream)


if __name__ == "__main__":
    raise SystemExit(main())
