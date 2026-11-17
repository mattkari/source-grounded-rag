"""What happened to one article, step by step — ADR 0012.

A trace answers "why does my article look like this?" without opening
`record.json`: for each step of the workflow, what went in, what came back,
and why anything was blocked, rejected or held back. It is built from the same
draft and article the record is built from, and it makes no call.

Steps are reported under the ids of `workflows.ARTICLE`, so the trace and the
diagram name the same things. Passages appear by page and score, never by text.
"""

from __future__ import annotations

import ask
import workflows
from article import assemble, checks, pipeline, sentences, terms

DONE, WAITING, BLOCKED, REJECTED, SKIPPED, FAILED = "done", "waiting", "blocked", "rejected", "not used", "failed"
_LABELS = {step.id: step for step in workflows.ARTICLE}


def _row(step: str, status: str, summary: str, details: list[str] | None = None, where: str = "") -> dict:
    return {"step": step, "label": _LABELS[step].label, "kind": _LABELS[step].kind, "where": where,
            "status": status, "summary": summary, "details": details or []}


def _section_rows(workspace, draft, article, index: int, section) -> list[dict]:
    where = section.heading
    if section.pending:
        return [_row("section", WAITING, "not sent to the model yet", [f"question: {section.brief}"], where)]
    if section.outcome is None:
        return [_row("section", FAILED, f"the call failed: {section.error}", [f"question: {section.brief}"], where)]
    outcome, result = section.outcome, section.outcome.result
    passages = [f"{item.handle}  {ask.page_phrase(item.chunk):<14} score {item.score:.3f}"
                + ("  (footnote text cut)" if item.chunk["chunk_id"] in workspace.sources.removed else "")
                for item in outcome.items]
    rows = [_row("section", DONE,
                 f"answered “{result.get('evidence_sufficiency')}”, citing {len(result.get('citations_used', []))} of "
                 f"{len(outcome.items)} passages",
                 [f"question: {section.brief}", f"system prompt {outcome.prompt_hash}; rules of form {checks.SECTION_PROMPT}",
                  "passages shown to the model (scores are diagnostics, not confidence):", *[f"  {p}" for p in passages]],
                 where)]
    reason = assemble.block_reason(outcome, section.error)
    if reason:
        rows.append(_row("checks", BLOCKED, reason, where=where))
        rows.append(_row("blocked", DONE, "left out of the article; not sent again"
                         + ("; the gap is stated under its heading" if section.state_gap else ""), where=where))
        return rows
    rows.append(_row("checks", DONE, "validation and the checks of form passed", where=where))
    edit = section.editorial
    if edit is None:
        rows.append(_row("editorial", SKIPPED, "no editorial pass was asked for", where=where))
    else:
        voice = ([f"connectives per 1,000 words {edit['voice_before']['connectives_per_1000_words']} -> "
                  f"{edit['voice_after']['connectives_per_1000_words']}; em dashes "
                  f"{edit['voice_before']['em_dashes']} -> {edit['voice_after']['em_dashes']}"]
                 if edit.get("voice_after") else [])
        example = [f"voice example shown: {edit['voice_example']['words']} words"] if edit.get("voice_example") else []
        if edit["accepted"]:
            rows.append(_row("editorial", DONE, "the rewrite was kept", voice + example, where))
        else:
            rows.append(_row("editorial", REJECTED, "the rewrite was rejected; the original stands",
                             [*edit["rejected_because"], *voice, *example], where))
    units = sentences.units(index, assemble.base_text(section))
    held = [h for h in article.held_back if h["section"] == index]
    own = [o for o in article.own_words if o["section"] == index]
    edits = [e for sid, e in draft.sentence_edits.items() if sid.split(".")[0] == str(index)]
    details = [f"{sum(1 for e in edits if e['text'] is None)} deleted by the researcher",
               f"{sum(1 for e in edits if e['text'] is not None)} edited by the researcher",
               f"{len(own)} kept as the researcher's own words"]
    if not section.kept:
        rows.append(_row("sentences", SKIPPED, "the researcher dropped this section", where=where))
    elif held:
        rows.append(_row("sentences", WAITING, f"{len(held)} of {len(units)} sentences carry no note and are held back",
                         details, where))
    else:
        rows.append(_row("sentences", DONE, f"{len(units)} sentences, each with a note or kept as the researcher's",
                         details, where))
    return rows


def trace(workspace: pipeline.Workspace, draft: pipeline.Draft) -> list[dict]:
    """Every step this article has been through, in order. No call is made."""
    article = pipeline.render(workspace, draft)
    rows = [_row("outline", DONE, f"“{draft.title}”, {len(draft.sections)} sections",
                 [f"{n}. {s.heading}: {s.brief}" for n, s in enumerate(draft.sections, start=1)])]
    rows.append(_row("sources", DONE,
                     f"{workspace.sources.report.passages_available} of {workspace.sources.report.passages_in_index} "
                     "passages may be drafted from", workspace.sources.report.lines()))
    for index, section in enumerate(draft.sections):
        rows += _section_rows(workspace, draft, article, index, section)

    pairs = pipeline.pairs_record(draft, article, workspace)
    current = [row for row in pairs if row["in_article"]]
    counts = assemble.support_rate(pairs)
    judged = sum(1 for row in current if row["verdict"])
    if not current:
        rows.append(_row("review", WAITING, "there is no sourced sentence to judge yet"))
    else:
        rows.append(_row("review", DONE if judged == len(current) else WAITING,
                         f"{judged} of {len(current)} sentences judged",
                         [f"supports {counts['supports']}, partly {counts['partly']}, does not {counts['does not']}, "
                          f"not judged {counts['not judged']}",
                          f"{sum(1 for row in current if row['carried_over'])} verdicts carried over from a per-note verdict"]))
    flagged = sum(1 for row in current if row["raised"])
    shared = terms.shared_terms(article.pairs, article.own_words)
    opinions = [row for row in current if row.get("second_opinion") and row["second_opinion"]["opinion"]]
    differing = sum(1 for row in opinions if row["second_opinion"]["opinion"] != row["verdict"])
    rows.append(_row("raised", DONE if flagged or shared or opinions else SKIPPED,
                     f"{flagged} sentence(s) flagged for reported speech; {len(shared)} term(s) in more than one section; "
                     f"{len(opinions)} second opinion(s), {differing} differing from the verdict",
                     [f"term: {term.term} (in {term.sections} sections)" for term in shared]))
    frame = []
    for kind in ("introduction", "conclusion"):
        element, asked = getattr(draft, kind), draft.frame_suggestions.get(kind, [])
        origin = element.origin if element is not None else "none"
        refused = sum(1 for suggestion in asked if suggestion["rejected_because"])
        frame.append(f"{kind}: {origin}; {len(asked)} suggestion(s) asked for, {refused} not offered")
    used = [kind for kind in ("introduction", "conclusion") if getattr(draft, kind) is not None]
    rows.append(_row("frame", DONE if used else SKIPPED,
                     ("in the article: " + " and ".join(used)) if used else "no introduction or conclusion", frame))
    blockers = pipeline.export_blockers(draft, article)
    rows.append(_row("export", WAITING if blockers else DONE,
                     "locked" if blockers else "ready: every sentence is judged", blockers))
    return rows


def format_trace(rows: list[dict]) -> str:
    """The trace as plain text, for the command line and the view alike."""
    lines = []
    for row in rows:
        where = f" [{row['where']}]" if row["where"] else ""
        lines.append(f"{row['status'].upper():<9} {row['label']}{where} ({row['kind']})")
        lines.append(f"          {row['summary']}")
        lines += [f"            {detail}" for detail in row["details"]]
    return "\n".join(lines)
