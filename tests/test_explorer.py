"""The exploring agent — `article/explorer.py`, PLAN_V7 §14, ADR 0014.

Offline. The agent's model is replaced at `ask.call_explorer`, the drafting model
at `ask.call_model`, and nowhere else: the tools, the budget, the check of the
proposal, approval, drafting, validation and the record are the real code. Every
passage, topic and query here is synthetic and says so.
"""

from __future__ import annotations

import copy
import dataclasses
import io
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

import ask
import write_article
from article import explorer, pipeline, trace
from test_article import Scripted, payload, trial  # noqa: F401  (trial is a fixture)

ROOT = Path(ask.__file__).resolve().parent
TOPIC = "FIXTURE: what the harbour records keep"


def reply(*calls, stop="tool_use", tokens=(100, 20)):
    """One scripted turn of the agent: the tool calls it makes."""
    reply.count = getattr(reply, "count", 0)
    content, listed = [], []
    for name, arguments in calls:
        reply.count += 1
        content.append({"type": "tool_use", "id": f"toolu_{reply.count}", "name": name, "input": arguments})
        listed.append({"id": f"toolu_{reply.count}", "name": name, "input": arguments})
    return {"stop_reason": stop, "content": content, "tool_calls": listed,
            "usage": {"input_tokens": tokens[0], "output_tokens": tokens[1]}}


def shown(messages) -> str:
    """Everything the agent has been shown so far, as one text."""
    parts = []
    for message in messages:
        blocks = message["content"] if isinstance(message["content"], list) else [{"type": "text", "text": message["content"]}]
        for block in blocks:
            if isinstance(block, dict):
                parts.append(str(block.get("text") or block.get("content") or ""))
    return "\n".join(parts)


def handle(messages, words: str) -> str:
    """The handle under which the agent was shown the passage holding `words`."""
    found = re.findall(r'\[(P\d+)\][^\n]*\n"([^"]*)"', shown(messages))
    return next(name for name, text in found if words in text)


class Agent:
    """Stands in for `ask.call_explorer`. A turn is a reply, or a function of the
    conversation so far that returns one."""

    def __init__(self, *turns, forever=None):
        self.turns, self.forever, self.seen, self.tools = list(turns), forever, [], None

    def __call__(self, system_prompt, messages, tools):
        self.seen.append(copy.deepcopy(messages))
        self.system, self.tools = system_prompt, tools
        turn = self.turns[len(self.seen) - 1] if len(self.seen) <= len(self.turns) else self.forever
        return turn(messages) if callable(turn) else turn


def proposal(messages, **overrides):
    given = {
        "theme": "FIXTURE: the harbour kept three kinds of record.",
        "sections": [
            {"heading": "FIXTURE lamp oil", "question": "FIXTURE: what was logged about lamp oil?",
             "passages": [handle(messages, "lamp oil")]},
            {"heading": "FIXTURE grafting", "question": "FIXTURE: what does the calendar list?",
             "passages": [handle(messages, "rootstock"), handle(messages, "lamp oil")]},
            {"heading": "FIXTURE tramway", "question": "FIXTURE: when did the timetable change?",
             "passages": [handle(messages, "viaduct")]},
        ],
        "gaps": ["FIXTURE: nothing on glaciers"],
    }
    given.update(overrides)
    return reply((explorer.PROPOSE, given))


def good_run():
    return Agent(
        reply((explorer.LIST_SOURCES, {})),
        reply((explorer.SEARCH, {"query": "FIXTURE lighthouse keeper lamp oil"})),
        reply((explorer.SEARCH, {"query": "FIXTURE tramway timetable viaduct"})),
        proposal,
    )


@pytest.fixture
def workspace(trial):
    return pipeline.open_workspace()


def chunk_id(n: int) -> str:
    return f"fixture-document::{n:05d}::fixture"


# --- the loop ------------------------------------------------------------------------


def test_an_exploration_searches_the_filtered_sources_and_ends_with_a_checked_proposal(workspace, monkeypatch):
    agent = good_run()
    monkeypatch.setattr(ask, "call_explorer", agent)
    monkeypatch.setattr(ask, "call_model", lambda *a, **k: pytest.fail("exploring drafted something"))

    run = explorer.explore(workspace, TOPIC)

    assert (run.stop, run.failures) == (explorer.PROPOSED, [])
    assert len(agent.seen) == 4 == len(run.steps) and run.searches == 2
    assert [call["tool"] for step in run.steps for call in step["calls"]] == [
        explorer.LIST_SOURCES, explorer.SEARCH, explorer.SEARCH, explorer.PROPOSE]
    # the proposal holds chunk ids resolved by code from the handles the agent was shown
    assert [section["passages"] for section in run.proposal["sections"]] == [
        [chunk_id(0)], [chunk_id(1), chunk_id(0)], [chunk_id(2)]]
    assert run.proposal["gaps"] == ["FIXTURE: nothing on glaciers"]
    assert run.steps[1]["calls"][0]["arguments"] == {"query": "FIXTURE lighthouse keeper lamp oil"}
    assert run.steps[1]["calls"][0]["returned"][0] == "P1" and len(run.passages) == 5
    assert run.tokens == {"input": 400, "output": 80}


def test_the_agent_is_shown_verbatim_passages_and_never_a_page_a_score_or_the_reference_list(workspace, monkeypatch):
    agent = good_run()
    monkeypatch.setattr(ask, "call_explorer", agent)
    explorer.explore(workspace, TOPIC)
    seen = shown(agent.seen[-1])

    assert "FIXTURE passage: the lighthouse keeper logged lamp oil deliveries every winter." in seen
    assert "Section: FIXTURE lamp oil ledger" in seen and "Chapter: FIXTURE chapter (5 passages)" in seen
    assert not ask.PAGE_CLAIM_RE.search(seen) and "pdf" not in seen.lower()
    assert not re.search(r"\b0\.\d{3}\b", seen) and "score" not in seen.lower()
    assert "beekeeping" not in seen and "Bibliography" not in seen            # reference apparatus is not a source
    assert seen.startswith(f"TOPIC\n=====\n{TOPIC}") and "STATUS: step 3 of 12 used; 2 search(es) made, 10 left" in seen
    assert [tool["name"] for tool in agent.tools] == [explorer.LIST_SOURCES, explorer.SEARCH, explorer.PROPOSE]
    assert agent.system == (ROOT / "prompts" / explorer.PROMPT).read_text(encoding="utf-8")


def test_the_step_cap_is_held_by_code_and_reaching_it_is_a_recorded_outcome(workspace, monkeypatch):
    agent = Agent(forever=lambda messages: reply((explorer.SEARCH, {"query": "FIXTURE canal survey locks"})))
    monkeypatch.setattr(ask, "call_explorer", agent)

    run = explorer.explore(workspace, TOPIC, max_steps=3)

    assert (run.stop, run.proposal) == (explorer.CAPPED, None)
    assert run.stop_detail == "3 steps were used without a proposal"
    assert len(agent.seen) == 3                                               # not one call more
    assert "This is your last step: call propose now" in shown(agent.seen[2])


def test_searches_past_the_budget_are_refused_and_recorded(workspace, monkeypatch):
    three = reply(*[(explorer.SEARCH, {"query": f"FIXTURE query {n}"}) for n in range(3)])
    agent = Agent(three, proposal)
    monkeypatch.setattr(ask, "call_explorer", agent)

    run = explorer.explore(workspace, TOPIC, max_steps=2)

    calls = run.steps[0]["calls"]
    assert [bool(call["error"]) for call in calls] == [False, False, True] and run.searches == 2
    assert calls[2]["error"] == "the search budget is used; call propose with what you have"
    refused = agent.seen[1][-1]["content"][2]
    assert refused["is_error"] is True and refused["tool_use_id"] == three["tool_calls"][2]["id"]


def test_the_token_ceiling_stops_an_exploration(workspace, monkeypatch):
    ceiling = explorer.estimate(workspace, 4)["token_ceiling"]
    agent = Agent(forever=lambda messages: reply((explorer.SEARCH, {"query": "FIXTURE canal"}), tokens=(ceiling, 1)))
    monkeypatch.setattr(ask, "call_explorer", agent)

    run = explorer.explore(workspace, TOPIC, max_steps=4)

    assert (run.stop, run.stop_detail) == (explorer.CAPPED, "the token ceiling was reached")
    assert len(agent.seen) == 1


def test_a_provider_failure_ends_the_exploration_and_nothing_is_sent_again(workspace, monkeypatch):
    calls = []

    def failing(*args):
        calls.append(1)
        raise RuntimeError("FIXTURE: the provider is down")

    monkeypatch.setattr(ask, "call_explorer", failing)
    run = explorer.explore(workspace, TOPIC)

    assert (run.stop, run.stop_detail) == (explorer.FAILED, "RuntimeError: FIXTURE: the provider is down")
    assert len(calls) == 1 and run.proposal is None and run.finished


def test_a_reply_without_a_tool_call_or_a_refusal_is_a_recorded_stop(workspace, monkeypatch):
    monkeypatch.setattr(ask, "call_explorer", Agent(reply(stop="end_turn")))
    assert explorer.explore(workspace, TOPIC).stop == explorer.STOPPED
    monkeypatch.setattr(ask, "call_explorer", Agent(reply(stop="refusal")))
    declined = explorer.explore(workspace, TOPIC)
    assert (declined.stop, declined.stop_detail) == (explorer.FAILED, "the reply ended with stop reason “refusal”")


def test_a_provider_without_tool_use_is_refused_in_plain_words(workspace, monkeypatch):
    monkeypatch.setattr(ask, "settings", dataclasses.replace(ask.settings, llm_provider="ollama"))
    with pytest.raises(ask.ExplorerUnavailable, match="needs a provider with tool use"):
        ask.call_explorer("FIXTURE", [], explorer.TOOLS)
    run = explorer.explore(workspace, TOPIC)                                   # the real boundary, no network
    assert run.stop == explorer.FAILED and "ExplorerUnavailable" in run.stop_detail


def test_the_real_boundary_makes_one_request_with_the_configured_model_and_the_tools(monkeypatch):
    sent = []

    class Messages:
        def create(self, **kwargs):
            sent.append(kwargs)
            block = SimpleNamespace(type="tool_use", id="toolu_fixture", name=explorer.SEARCH, input={"query": "FIXTURE"})
            return SimpleNamespace(stop_reason="tool_use", content=[SimpleNamespace(type="text", text="FIXTURE"), block],
                                   usage=SimpleNamespace(input_tokens=10, output_tokens=5, cache_read_input_tokens=30,
                                                         cache_creation_input_tokens=None))

    monkeypatch.setattr(ask, "_get_client", lambda: SimpleNamespace(messages=Messages()))
    got = ask.call_explorer("FIXTURE system", [{"role": "user", "content": "FIXTURE"}], explorer.TOOLS)

    assert len(sent) == 1
    assert sent[0]["model"] == ask.settings.llm_model and sent[0]["tools"] == explorer.TOOLS
    assert sent[0]["max_tokens"] == ask.settings.explorer_step_max_tokens
    assert "tool_choice" not in sent[0] and "output_config" not in sent[0]
    assert got["tool_calls"] == [{"id": "toolu_fixture", "name": explorer.SEARCH, "input": {"query": "FIXTURE"}}]
    assert got["usage"] == {"input_tokens": 40, "output_tokens": 5} and len(got["content"]) == 2


# --- the check of the proposal -------------------------------------------------------


def test_a_proposal_naming_a_passage_no_search_returned_is_blocked_whole_and_not_repaired(workspace, monkeypatch):
    def invented(messages):
        given = proposal(messages)["tool_calls"][0]["input"]
        given["sections"][1]["passages"].append("P99")
        return reply((explorer.PROPOSE, given))

    monkeypatch.setattr(ask, "call_explorer", Agent(reply((explorer.SEARCH, {"query": "FIXTURE lamp oil"})), invented))
    run = explorer.explore(workspace, TOPIC)

    assert (run.stop, run.proposal) == (explorer.BLOCKED, None)
    assert run.failures == ["section 2 names passages no search returned: P99"]
    assert run.proposal_as_given["sections"][1]["passages"][-1] == "P99"        # kept as sent, for the record


def test_a_proposal_that_writes_a_page_number_is_blocked(workspace, monkeypatch):
    monkeypatch.setattr(ask, "call_explorer", Agent(
        reply((explorer.SEARCH, {"query": "FIXTURE lamp oil"})),
        lambda messages: proposal(messages, theme="FIXTURE: the ledger on p. 3 shows deliveries.")))
    run = explorer.explore(workspace, TOPIC)

    assert run.stop == explorer.BLOCKED
    assert run.failures == ["the proposal writes a page number; pages are resolved from stored records only"]


def test_a_section_with_no_passage_becomes_a_gap_and_too_few_sections_block_the_proposal():
    seen = {"P1": {"chunk_id": chunk_id(0)}, "P2": {"chunk_id": chunk_id(1)}, "P3": {"chunk_id": chunk_id(2)}}
    section = lambda n, handles: {"heading": f"FIXTURE {n}", "question": f"FIXTURE: q{n}?", "passages": handles}

    checked, failures = explorer.check_proposal(
        {"theme": "FIXTURE theme.", "gaps": [],
         "sections": [section(1, ["P1"]), section(2, ["[P2]", "P2"]), section(3, ["P3"]), section(4, [])]}, seen)
    assert failures == [] and [s["heading"] for s in checked["sections"]] == ["FIXTURE 1", "FIXTURE 2", "FIXTURE 3"]
    assert checked["sections"][1]["passages"] == [chunk_id(1)]                 # one passage once
    assert checked["gaps"] == ["FIXTURE 4: no passage was found for “FIXTURE: q4?”"]

    none, failures = explorer.check_proposal(
        {"theme": "FIXTURE theme.", "gaps": [], "sections": [section(1, ["P1"]), section(2, [])]}, seen)
    assert none is None and failures == ["1 section(s) have passages; an article needs 3 to 6"]
    crowded = section(1, ["P1", "P2", "P3", "P1", "P2", "P3"])
    assert explorer.check_proposal({"theme": "FIXTURE.", "sections": [crowded], "gaps": []}, seen)[1] == [
        "section 1 carries 6 passages; the most is 5"]


# --- the budget, before anything is sent ---------------------------------------------


def test_the_cost_ceiling_is_counted_without_a_call_and_a_price_is_never_assumed(workspace, monkeypatch):
    monkeypatch.setattr(ask, "call_explorer", lambda *a: pytest.fail("the estimate called the model"))
    monkeypatch.setattr(ask, "embed_texts", lambda *a, **k: pytest.fail("the estimate embedded something"))
    unpriced = dataclasses.replace(ask.settings, llm_price_input_per_mtok=None, llm_price_output_per_mtok=None)
    monkeypatch.setattr(ask, "settings", unpriced)

    small, large = explorer.estimate(workspace, 2), explorer.estimate(workspace, 12)
    assert small["model_calls_at_most"] == 2 and large["token_ceiling"] > small["token_ceiling"]
    assert large["cost_ceiling_usd"] is None and "No price is configured" in explorer.format_estimate(large)
    assert explorer.estimate(workspace)["model_calls_at_most"] == ask.settings.explorer_max_steps

    monkeypatch.setattr(ask, "settings", dataclasses.replace(unpriced, llm_price_input_per_mtok=2.0, llm_price_output_per_mtok=10.0))
    priced = explorer.estimate(workspace, 2)
    assert priced["cost_ceiling_usd"] == round(
        (priced["input_tokens_ceiling"] * 2.0 + priced["output_tokens_ceiling"] * 10.0) / 1_000_000, 4)


# --- approval, and drafting from approved passages -----------------------------------


@pytest.fixture
def explored(workspace, monkeypatch):
    monkeypatch.setattr(ask, "call_explorer", good_run())
    run = explorer.explore(workspace, TOPIC)
    monkeypatch.setattr(ask, "call_explorer", lambda *a: pytest.fail("the agent was called again"))
    return run


class Recording(Scripted):
    """The drafting model, scripted, remembering which passages each call was shown."""

    def __init__(self, script):
        super().__init__(script)
        self.shown = []

    def __call__(self, question, items, instructions=None):
        self.shown.append([item.chunk["chunk_id"] for item in items])
        return super().__call__(question, items, instructions)


DRAFTS = {"lamp oil": payload("FIXTURE the keeper logged lamp oil [E1].", cites=["E1"]),
          "calendar": payload("FIXTURE the calendar lists rootstock [E1]. FIXTURE oil again [E2].", cites=["E1", "E2"]),
          "timetable": payload("FIXTURE the timetable changed [E1].", cites=["E1"])}


def test_nothing_is_drafted_before_approval_and_each_section_is_drafted_from_exactly_its_approved_passages(
        workspace, explored, trial, monkeypatch):
    model = Recording(DRAFTS)
    monkeypatch.setattr(ask, "call_model", model)
    assert model.shown == []                                                   # exploring and proposing drafted nothing

    approved = pipeline.approve(workspace, explored.as_record())
    draft = pipeline.new_draft("FIXTURE harbour title",
                               [(s["heading"], s["question"]) for s in approved["approval"]["sections"]],
                               exploration=approved)
    assert model.shown == [] and all(section.pending for section in draft.sections)
    assert pipeline.planned_calls(draft)["embedding_calls"] == 0               # nothing is retrieved for these
    monkeypatch.setattr(ask, "embed_texts", lambda *a, **k: pytest.fail("an approved section retrieved something"))

    pipeline.run(workspace, draft, trial.out_dir)

    assert model.shown == [[chunk_id(0)], [chunk_id(1), chunk_id(0)], [chunk_id(2)]]
    assert all(pipeline.usable(section) for section in draft.sections)
    record = json.loads((trial.out_dir / draft.article_id / "record.json").read_text(encoding="utf-8"))
    assert [s["evidence_origin"] for s in record["sections"]] == ["approved from an exploration"] * 3
    assert record["sections"][1]["approved_passages"] == [chunk_id(1), chunk_id(0)]
    assert record["exploration"]["approval"]["approved_by"] == "researcher"
    assert record["exploration"]["reproducible"] is False
    assert record["prompts"][explorer.PROMPT] == explored.prompt_sha256_12
    article = pipeline.render(workspace, draft)
    assert "FIXTURE the keeper logged lamp oil [1]." in article.markdown and "p. 3." in article.markdown


def test_a_handle_outside_the_approved_passages_fails_validation_as_always(workspace, explored, monkeypatch):
    monkeypatch.setattr(ask, "call_model", Scripted({**DRAFTS, "lamp oil": payload("FIXTURE oil [E2].", cites=["E2"])}))
    approved = pipeline.approve(workspace, explored.as_record())
    first = approved["approval"]["sections"][0]

    section = pipeline.draft_section(workspace, first["heading"], first["question"], first["passages"])

    assert not pipeline.usable(section)
    assert any("E2" in str(failure) for failure in section.outcome.failures)


def test_approval_records_what_the_researcher_changed_and_refuses_what_cannot_be_drafted(workspace, explored):
    record = explored.as_record()
    unchanged = pipeline.approve(workspace, record)["approval"]["changes"]
    assert (unchanged["sections_approved"], unchanged["passages_dropped"], unchanged["headings_reworded"]) == (3, 0, 0)

    edited = copy.deepcopy(record["proposal"]["sections"])
    edited[0]["heading"] = "FIXTURE my own heading"
    edited[1]["passages"] = [chunk_id(1)]                                      # one passage dropped from one section
    edited[2]["passages"] = [chunk_id(2), chunk_id(5)]                         # one the agent did not propose
    changes = pipeline.approve(workspace, record, edited)["approval"]["changes"]
    assert changes["headings_reworded"] == 1 and changes["questions_reworded"] == 0
    assert changes["passages_added_by_researcher"] == 1 and changes["passages_dropped"] == 0

    with pytest.raises(pipeline.ArticleError, match="does not hold"):
        pipeline.approve(workspace, record, [{**edited[0], "passages": ["fixture-document::99999::nope"]}, *edited[1:]])
    with pytest.raises(pipeline.ArticleError, match="no passage left"):
        pipeline.approve(workspace, record, [{**edited[0], "passages": []}, *edited[1:]])
    with pytest.raises(pipeline.ArticleError, match="3 to 6 sections"):
        pipeline.approve(workspace, record, edited[:2])
    with pytest.raises(pipeline.ArticleError, match="nothing to approve"):
        pipeline.approve(workspace, {**record, "proposal": None})
    with pytest.raises(pipeline.ArticleError, match="index has changed"):
        pipeline.approve(workspace, {**record, "corpus_text_sha256": "another-hash"})


def test_an_article_drafted_from_a_proposal_reopens_with_its_exploration_and_resumes_without_retrieving(
        workspace, explored, trial, monkeypatch):
    monkeypatch.setattr(ask, "call_model", Scripted(DRAFTS))
    approved = pipeline.approve(workspace, explored.as_record())
    draft = pipeline.new_draft("FIXTURE harbour title",
                               [(s["heading"], s["question"]) for s in approved["approval"]["sections"]],
                               exploration=approved)
    folder = pipeline.save(workspace, draft, trial.out_dir)                    # the plan only: nothing drafted

    reopened = pipeline.load(folder, workspace)
    assert [section.approved for section in reopened.sections] == [s["passages"] for s in approved["approval"]["sections"]]
    assert reopened.exploration["approval"]["sections"] == approved["approval"]["sections"]
    monkeypatch.setattr(ask, "embed_texts", lambda *a, **k: pytest.fail("a resumed approved section retrieved"))
    pipeline.run(workspace, reopened, trial.out_dir)
    assert reopened.complete and all(pipeline.usable(section) for section in reopened.sections)


def test_an_outline_line_the_researcher_rewrote_is_drafted_by_retrieval_as_before(workspace, explored, monkeypatch):
    approved = pipeline.approve(workspace, explored.as_record())
    outline = [(s["heading"], s["question"]) for s in approved["approval"]["sections"]]
    outline[2] = (outline[2][0], "FIXTURE: a question of my own about the tramway")

    draft = pipeline.new_draft("FIXTURE harbour title", outline, exploration=approved)

    assert [bool(section.approved) for section in draft.sections] == [True, True, False]
    assert pipeline.planned_calls(draft)["embedding_calls"] == 1


# --- the record, the trace and the command line --------------------------------------


def test_an_explorations_record_and_trace_hold_ids_and_pages_and_no_passage_text(workspace, explored, tmp_path, monkeypatch):
    path = explorer.save(explored, tmp_path / "explorations")
    again = explorer.save(explored, tmp_path / "explorations")
    stored = path.read_text(encoding="utf-8")

    assert path == again and "FIXTURE passage:" not in stored                  # one file per exploration; no thesis text
    assert explorer.load(path).as_record() == explored.as_record()
    monkeypatch.setattr(ask, "embed_texts", lambda *a, **k: pytest.fail("the trace embedded something"))
    rows = trace.exploration_rows(workspace, explored.as_record())
    text = trace.format_trace(rows)

    assert rows[0]["step"] == "explore" and rows[0]["status"] == "waiting"
    assert "WAITING   Explore the sources and propose a theme, an outline and passages (agent, bounded)" in text
    assert "step 2: search “FIXTURE lighthouse keeper lamp oil” -> p. 3; " in text
    assert "used: 4 model call(s), 2 search(es), 400 input and 80 output tokens" in text
    assert "an exploration is not reproducible" in text and "FIXTURE passage:" not in text

    approved = pipeline.approve(workspace, explored.as_record())
    done = trace.exploration_rows(workspace, approved)[0]
    assert done["status"] == "done" and done["summary"] == (
        "proposed 3 sections with 3 passages; the researcher approved 3 with 3")


def test_the_articles_trace_begins_with_its_exploration_and_says_where_the_passages_came_from(
        workspace, explored, trial, monkeypatch):
    monkeypatch.setattr(ask, "call_model", Scripted(DRAFTS))
    approved = pipeline.approve(workspace, explored.as_record())
    draft = pipeline.new_draft("FIXTURE harbour title",
                               [(s["heading"], s["question"]) for s in approved["approval"]["sections"]],
                               exploration=approved)
    pipeline.run(workspace, draft, trial.out_dir)

    rows = trace.trace(workspace, draft)

    assert [row["step"] for row in rows][:3] == ["explore", "outline", "sources"]
    section = next(row for row in rows if row["step"] == "section")
    assert any(detail.startswith("passages approved by the researcher from the exploration") for detail in section["details"])


def test_agreement_between_runs_is_reported_as_counts():
    def run(*sections):
        made = explorer.Exploration("FIXTURE", "fixture-document", None, 3, 10)
        made.proposal = {"theme": "FIXTURE", "gaps": [], "sections": [{"heading": "h", "question": "q", "passages": list(p)}
                                                                      for p in sections]} if sections else None
        return made

    shared = explorer.overlap([run(["a", "b"], ["c"]), run(["a"], ["c", "d"]), run()])
    assert shared == {"runs": 3, "with_a_proposal": 2, "passages_in_any": 4, "passages_in_all": 2, "per_run": [3, 3]}


def test_the_command_line_explores_saves_the_record_and_drafts_from_it(trial, monkeypatch):
    out, articles = io.StringIO(), trial.out_dir
    monkeypatch.setattr(ask, "call_explorer", lambda *a: pytest.fail("a dry run called the model"))
    assert write_article.main(["--explore", TOPIC, "--dry-run", "--out-dir", str(articles)], stream=out) == 0
    assert "EXPLORATION BUDGET (nothing has been sent)" in out.getvalue() and "model calls, at most        12" in out.getvalue()

    monkeypatch.setattr(ask, "call_explorer", good_run())
    out = io.StringIO()
    assert write_article.main(["--explore", TOPIC, "--out-dir", str(articles)], stream=out) == 0
    printed = out.getvalue()
    saved = list((articles.parent / "explorations").glob("*.json"))
    assert len(saved) == 1 and "THEME  FIXTURE: the harbour kept three kinds of record." in printed
    assert "  step 2: search “FIXTURE lighthouse keeper lamp oil”" in printed
    assert re.search(r"1\. FIXTURE lamp oil\n   FIXTURE: what was logged about lamp oil\?\n     p\. 3 +FIXTURE lamp oil ledger", printed)
    assert "FIXTURE passage:" not in printed                                   # pages and places, not the text

    monkeypatch.setattr(ask, "call_explorer", lambda *a: pytest.fail("drafting called the agent"))
    monkeypatch.setattr(ask, "call_model", Scripted(DRAFTS))
    out = io.StringIO()
    code = write_article.main(["--from-exploration", str(saved[0]), "--title", "FIXTURE harbour title",
                               "--out-dir", str(articles)], stream=out)
    assert code == 0 and "  2. FIXTURE grafting  (from 2 approved passage(s))" in out.getvalue()
    record = json.loads(next(articles.glob("*/record.json")).read_text(encoding="utf-8"))
    assert record["exploration"]["approval"]["changes"]["sections_approved"] == 3


def test_the_command_line_reports_how_far_repeated_explorations_agree(trial, monkeypatch):
    turns = iter([*good_run().turns, *good_run().turns])
    monkeypatch.setattr(ask, "call_explorer", lambda system, messages, tools: (
        lambda turn: turn(messages) if callable(turn) else turn)(next(turns)))
    out = io.StringIO()

    assert write_article.main(["--explore", TOPIC, "--explore-repeat", "2", "--out-dir", str(trial.out_dir)], stream=out) == 0
    assert "passages in every proposal  3 of 3 proposed in any" in out.getvalue()
    assert len(list((trial.out_dir.parent / "explorations").glob("*.json"))) == 2


# --- what the agent cannot reach -----------------------------------------------------


def test_a_question_and_the_evaluation_never_reach_the_agent(fixture_index, monkeypatch):
    monkeypatch.setattr(ask, "call_explorer", lambda *a: pytest.fail("a question reached the agent"))
    sent = []
    monkeypatch.setattr(ask, "call_model", lambda question, items: (sent.append(question), (payload(
        "FIXTURE oil [E1].", cites=["E1"]), "fixturehash"))[1])
    vectors, chunks, _ = ask.load_index()

    ask.run_query("FIXTURE: lamp oil?", vectors, chunks)

    assert sent == ["FIXTURE: lamp oil?"]                                      # sent exactly as before, no instructions
    for name in ("evaluate.py", "main.py", "ask.py"):
        source = (ROOT / name).read_text(encoding="utf-8")
        assert "explorer" not in source.replace("call_explorer", "").replace("ExplorerUnavailable", "").replace(
            "explorer_step_max_tokens", "").replace("article/explorer.py", "") or name == "ask.py"
    assert "call_explorer" not in (ROOT / "evaluate.py").read_text(encoding="utf-8")
    assert "explorer" not in (ROOT / "evaluate.py").read_text(encoding="utf-8")
