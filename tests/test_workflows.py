"""The workflow description, its diagram and the article trace — ADR 0012.

`workflows.py` describes; it runs nothing. These tests are what keep the
description true: a step that names a function which no longer exists fails
here, as does a committed diagram that differs from the one generated, a cycle,
or a trace that reports a step the diagram does not have.
"""

from __future__ import annotations

import importlib
import io
import json
import re
from pathlib import Path

import pytest

import ask
import workflows
import write_article
from article import pipeline, trace
from test_article import BRIEFS, REFUSAL, SCRIPT, Scripted, payload, trial  # noqa: F401  (trial is a fixture)
from test_article_quality import Editor, ORIGINAL

ROOT = Path(ask.__file__).resolve().parent


def resolve(dotted: str):
    parts = dotted.split(".")
    for cut in range(len(parts) - 1, 0, -1):
        try:
            target = importlib.import_module(".".join(parts[:cut]))
        except ModuleNotFoundError:
            continue
        for name in parts[cut:]:
            target = getattr(target, name)
        return target
    raise AssertionError(f"{dotted} names no module")


@pytest.mark.parametrize("name", list(workflows.WORKFLOWS))
def test_every_step_names_functions_that_exist(name):
    for step in workflows.WORKFLOWS[name]:
        assert step.kind in workflows.KINDS, step.id
        for dotted in step.code:
            assert callable(resolve(dotted)), f"{name} / {step.id}: {dotted}"
        if step.kind != workflows.RESEARCHER:
            assert step.code or step.id in ("ungrounded",), f"{step.id} names no code"


@pytest.mark.parametrize("name", list(workflows.WORKFLOWS))
def test_a_workflow_is_a_fixed_sequence_with_no_loop(name):
    steps = workflows.WORKFLOWS[name]
    ids = [step.id for step in steps]
    order = {step_id: position for position, step_id in enumerate(ids)}

    assert len(set(ids)) == len(ids)
    for step in steps:
        for target, _ in step.then:
            assert target in order, f"{step.id} leads to an unknown step {target}"
            assert order[target] > order[step.id], f"{step.id} leads back to {target}: a loop"       # no loop, no retry
    reached = {ids[0]} | {target for step in steps for target, _ in step.then}
    assert reached == set(ids)                                          # nothing is left unconnected


def test_no_step_lets_a_model_choose_what_happens_next():
    """A branch may follow a check, which is plain code, or a person. Never a model call."""
    for name, steps in workflows.WORKFLOWS.items():
        for step in steps:
            outcomes = {label for _, label in step.then if label}
            if outcomes:
                assert step.kind in (workflows.CHECK, workflows.RESEARCHER), f"{name} / {step.id} branches on a {step.kind}"


def test_the_committed_diagram_is_the_one_the_description_generates():
    committed = (ROOT / "docs" / "workflows.md").read_text(encoding="utf-8")

    assert committed == workflows.document()
    assert committed.count("```mermaid") == len(workflows.WORKFLOWS) + 1
    for name in workflows.WORKFLOWS:
        assert f"## {name}" in committed
    for source, step_id, target in workflows.SHARED:
        assert target in workflows.WORKFLOWS and any(s.id == step_id for s in workflows.WORKFLOWS[source])
        assert "ask.run_query" in next(s for s in workflows.WORKFLOWS[source] if s.id == step_id).code     # the one pipeline


def test_a_steps_kind_is_in_its_words_as_well_as_its_shape():
    drawn = workflows.mermaid(workflows.ARTICLE)

    assert 'section{{"Draft each section through the Ask pipeline, or from approved passages<br/><i>model call</i>"}}' in drawn
    assert 'explore>"Explore the sources and propose a theme, an outline and passages<br/><i>agent, bounded, optional</i>"]' in drawn
    assert 'review(["Verdict on each sentence and note; edit or delete<br/><i>researcher</i>"])' in drawn
    assert "<i>model call, optional</i>" in drawn and "checks -->|failed| blocked" in drawn
    assert not re.search(r"-->.*\bsection\b\s*$", "\n".join(l for l in drawn.splitlines() if l.strip().startswith("blocked")))


# --- the trace -----------------------------------------------------------------------------


@pytest.fixture
def workspace(trial):
    return pipeline.open_workspace()


def by_step(rows, step, where=None):
    return [row for row in rows if row["step"] == step and (where is None or row["where"] == where)]


def test_the_trace_reports_every_step_under_the_ids_of_the_diagram_and_makes_no_call(workspace, monkeypatch):
    monkeypatch.setattr(ask, "call_model", Scripted({
        **SCRIPT, "orchard": payload("[E1] states that rootstock is listed [E2].", cites=["E1", "E2"]),
        "tramway": payload("FIXTURE the timetable changed [E1]. FIXTURE and so the town grew.", cites=["E1"])}))
    draft = pipeline.new_draft("FIXTURE harbour title", [(f"FIXTURE heading {n + 1}", b) for n, b in enumerate(BRIEFS)])
    draft.sections[0] = pipeline.draft_section(workspace, "FIXTURE heading 1", BRIEFS[0])
    draft.sections[1] = pipeline.draft_section(workspace, "FIXTURE heading 2", BRIEFS[1])
    draft.sections[2] = pipeline.draft_section(workspace, "FIXTURE heading 3", BRIEFS[2])
    monkeypatch.setattr(ask, "call_model", lambda *a, **k: pytest.fail("the trace called the model"))
    monkeypatch.setattr(ask, "embed_texts", lambda *a, **k: pytest.fail("the trace embedded something"))

    rows = trace.trace(workspace, draft)
    text = trace.format_trace(rows)

    assert {row["step"] for row in rows} <= {step.id for step in workflows.ARTICLE}      # the diagram's own steps
    assert [row["step"] for row in rows][:2] == ["outline", "sources"] and rows[-1]["step"] == "export"
    first = by_step(rows, "section", "FIXTURE heading 1")[0]
    assert first["status"] == "done" and first["summary"].startswith("answered “sufficient”, citing 1 of ")
    assert any(re.fullmatch(r"  E1  p\. 3 +score \d\.\d{3}", detail) for detail in first["details"])    # page and score
    assert by_step(rows, "checks", "FIXTURE heading 2")[0]["status"] == "blocked"
    assert "handle_used_as_subject" in by_step(rows, "checks", "FIXTURE heading 2")[0]["summary"]
    assert by_step(rows, "blocked", "FIXTURE heading 2")[0]["summary"].startswith("left out of the article; not sent again")
    assert not by_step(rows, "sentences", "FIXTURE heading 2")          # a blocked section goes no further
    held = by_step(rows, "sentences", "FIXTURE heading 3")[0]
    assert (held["status"], held["summary"]) == ("waiting", "1 of 2 sentences carry no note and are held back")
    assert by_step(rows, "editorial", "FIXTURE heading 1")[0]["status"] == "not used"
    assert by_step(rows, "review")[0]["summary"] == "0 of 2 sentences judged"
    assert rows[-1]["status"] == "waiting" and "2 of 2 sentences are not judged yet" in rows[-1]["details"]
    assert "FIXTURE passage:" not in text                               # passages by page and score, never by text
    assert "BLOCKED   Validation and checks of form [FIXTURE heading 2] (check)" in text


def test_the_trace_shows_a_rejected_rewrite_a_pending_section_and_a_ready_export(workspace, monkeypatch):
    rewrite = payload("FIXTURE Harland logged the lamp oil [E1]. FIXTURE it came in winter [E2].", cites=["E1", "E2"])
    monkeypatch.setattr(ask, "call_model", Editor(ORIGINAL, rewrite))
    draft = pipeline.new_draft("FIXTURE harbour title", [(f"FIXTURE heading {n + 1}", b) for n, b in enumerate(BRIEFS)],
                               editorial=True)
    draft.sections[0] = pipeline.edit_section(pipeline.draft_section(workspace, "FIXTURE heading 1", BRIEFS[0]))
    rows = trace.trace(workspace, draft)

    edit = by_step(rows, "editorial", "FIXTURE heading 1")[0]
    assert edit["status"] == "rejected" and edit["details"][0] == "new_terms: the rewrite adds “Harland”"
    assert any(detail.startswith("connectives per 1,000 words ") for detail in edit["details"])
    assert by_step(rows, "section", "FIXTURE heading 2")[0]["status"] == "waiting"
    assert "the draft is not finished" in rows[-1]["details"]

    draft.sections, draft.complete = draft.sections[:1], True
    for pair in pipeline.render(workspace, draft).pairs:
        pipeline.set_pair_verdict(draft, pair, "supports")
    done = trace.trace(workspace, draft)
    assert (done[-1]["status"], done[-1]["summary"]) == ("done", "ready: every sentence is judged")
    assert by_step(done, "review")[0]["status"] == "done"


def test_the_command_line_prints_the_trace_of_a_saved_article(trial, tmp_path, monkeypatch):
    monkeypatch.setattr(ask, "call_model", Scripted({**SCRIPT, "orchard": REFUSAL}))
    outline = tmp_path / "outline.txt"
    outline.write_text("\n".join(f"FIXTURE heading {n + 1} | {b}" for n, b in enumerate(BRIEFS)), encoding="utf-8")
    out = tmp_path / "articles"
    write_article.main(["--title", "FIXTURE harbour title", "--outline", str(outline), "--out-dir", str(out)], io.StringIO())
    (folder,) = out.iterdir()
    monkeypatch.setattr(ask, "call_model", lambda *a, **k: pytest.fail("the trace called the model"))
    stream = io.StringIO()

    assert write_article.main(["--trace", folder.name, "--out-dir", str(out)], stream) == 0
    printed = stream.getvalue()
    assert "DONE      Title and outline: written, or a proposal edited and approved (researcher)" in printed
    assert "BLOCKED   Validation and checks of form [FIXTURE heading 2] (check)" in printed
    assert "the thesis does not hold enough evidence for this" in printed
    assert write_article.main(["--trace", "no-such-article", "--out-dir", str(out)], io.StringIO()) == 2


def test_an_agent_step_has_one_way_out_and_it_leads_to_a_person():
    """Inside an agent step the model chooses its searches (ADR 0014). Around it the
    workflow is unchanged: one way out, unlabelled, to a step where the researcher decides."""
    for name, steps in workflows.WORKFLOWS.items():
        by_id = {step.id: step for step in steps}
        for step in steps:
            if step.kind == workflows.AGENT:
                assert name == "Drafting an article", "only the article writer has an agent step"
                assert len(step.then) == 1 and step.then[0][1] == ""
                assert by_id[step.then[0][0]].kind == workflows.RESEARCHER
    assert not any(step.kind == workflows.AGENT for step in workflows.ASK + workflows.EVALUATION)
