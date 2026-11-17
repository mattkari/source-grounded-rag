"""The exploring agent — PLAN_V7 §14, ADR 0014.

Given the researcher's topic, the model searches the workspace's sources in a
loop, choosing each next search itself, and ends by proposing a theme, an
outline and the passages for each section. That is all it does. It writes no
sentence of the article, no page number and no verdict, and the evaluation
never reaches it.

What the model chooses: which tool to call next, and with what words.
What code holds, and the model cannot change:

  * the tools: listing the sources and searching them are the existing
    retrieval over the filtered sources, nothing else;
  * the budget: a cap on model calls, a cap on searches, and a ceiling on
    tokens, all fixed before the first call;
  * the stop: a proposal, the budget, or a failure. Each is recorded; nothing
    is run again by itself (hard rule 9);
  * the check of the proposal: every passage it names must be one a search
    returned in this run;
  * the log: every step, its tool, its arguments and the ids of what came back.

The proposal is a proposal. `pipeline.approve` is where the researcher's edit
and approval turn it into an article's plan.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import ask
from article import checks

PROMPT = "explorer_v1.md"
PASSAGES_PER_SEARCH = 5
SECTION_PASSAGES = 5                 # the most passages one proposed section may carry
MIN_SECTIONS, MAX_SECTIONS = 3, 6
CHARS_PER_TOKEN = 4                  # a rough rule for prompt text; the provider's own count will differ

# How an exploration ended.
PROPOSED = "proposed"                # a proposal that passed the check
BLOCKED = "proposal blocked"         # a proposal that failed the check
CAPPED = "budget reached"            # the step cap or the token ceiling, with no proposal
STOPPED = "stopped without a proposal"
FAILED = "failed"                    # the provider raised, declined or cut the reply off

LIST_SOURCES, SEARCH, PROPOSE = "list_sources", "search", "propose"


def _strict(properties: dict) -> dict:
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


TOOLS = [
    {
        "name": LIST_SOURCES,
        "description": "List each source the researcher chose, with the chapters and sections it prints "
                       "and how many passages each holds. Call this first.",
        "input_schema": _strict({}),
        "strict": True,
    },
    {
        "name": SEARCH,
        "description": f"Find the {PASSAGES_PER_SEARCH} passages closest in meaning to a query. Each comes "
                       "back under a handle such as [P4], with the source and section it is from and its "
                       "full text. Write the query in the words a passage on the subject would use.",
        "input_schema": _strict({"query": {"type": "string", "description": "What to look for."}}),
        "strict": True,
    },
    {
        "name": PROPOSE,
        "description": "End the exploration with a proposal for the researcher: a theme, three to six "
                       "sections with the passages that answer each, and the gaps you found.",
        "input_schema": _strict({
            "theme": {"type": "string",
                      "description": "One sentence: what these sources together let the article say."},
            "sections": {
                "type": "array",
                "items": _strict({
                    "heading": {"type": "string"},
                    "question": {"type": "string",
                                 "description": "The question this section must answer from its passages."},
                    "passages": {"type": "array", "items": {"type": "string"},
                                 "description": "Handles of the passages for this section, strongest first, "
                                                f"at most {SECTION_PASSAGES}. For example [\"P2\", \"P7\"]."},
                }),
            },
            "gaps": {"type": "array", "items": {"type": "string"},
                     "description": "Parts of the topic you looked for and did not find."},
        }),
        "strict": True,
    },
]


def tools_for(workspace) -> list[dict]:
    """The tools as this workspace's agent is offered them. With several sources
    (PLAN_V7 §7) a search may be narrowed to one of them by its id."""
    if not workspace.several:
        return TOOLS
    ids = [document.document_id for document in workspace.documents]
    search = {
        **TOOLS[1],
        "description": TOOLS[1]["description"] + " Give `source` the id of one source to search only that "
                       "one, or null to search them all; from all, at most a few passages come from any one source.",
        "input_schema": _strict({
            "query": {"type": "string", "description": "What to look for."},
            "source": {"anyOf": [{"type": "string", "enum": ids}, {"type": "null"}],
                       "description": "A source id from list_sources, or null for every source."},
        }),
    }
    return [TOOLS[0], search, TOOLS[2]]


def tools_hash(tools: list[dict] | None = None) -> str:
    return hashlib.sha256(json.dumps(TOOLS if tools is None else tools, sort_keys=True).encode("utf-8")).hexdigest()[:12]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Exploration:
    topic: str
    document_id: str
    corpus_text_sha256: str | None
    max_steps: int
    token_ceiling: int
    started: str = field(default_factory=_now)
    finished: str | None = None
    stop: str | None = None
    stop_detail: str = ""
    # One entry per model call: {"step", "input_tokens", "output_tokens", "calls": [...]}.
    # A call is {"tool", "arguments", "returned": [handles], "error"}. No passage text.
    steps: list[dict] = field(default_factory=list)
    # handle -> {"chunk_id", "score", "step"}: every passage a search returned, once.
    passages: dict[str, dict] = field(default_factory=dict)
    # As checked: {"theme", "sections": [{"heading", "question", "passages": [chunk ids]}], "gaps"}.
    proposal: dict | None = None
    proposal_as_given: dict | None = None        # what the model sent, when it was blocked
    failures: list[str] = field(default_factory=list)
    prompt: str = PROMPT
    prompt_sha256_12: str = ""
    tools_sha256_12: str = ""
    model: str = ""
    provider: str = ""
    exploration_id: str | None = None
    # Every source searched, in order, and the hash of each one's index (PLAN_V7 §7).
    document_ids: list[str] = field(default_factory=list)
    corpora: dict[str, str | None] = field(default_factory=dict)

    @property
    def searches(self) -> int:
        return sum(1 for step in self.steps for call in step["calls"] if call["tool"] == SEARCH and not call["error"])

    @property
    def tokens(self) -> dict:
        return {"input": sum(step["input_tokens"] for step in self.steps),
                "output": sum(step["output_tokens"] for step in self.steps)}

    def as_record(self) -> dict:
        return {
            "exploration_id": self.exploration_id, "topic": self.topic, "document_id": self.document_id,
            "corpus_text_sha256": self.corpus_text_sha256,
            "document_ids": self.document_ids or [self.document_id],
            "corpora": self.corpora or {self.document_id: self.corpus_text_sha256},
            "started": self.started, "finished": self.finished,
            "model": self.model, "provider": self.provider,
            "prompt": self.prompt, "prompt_sha256_12": self.prompt_sha256_12, "tools_sha256_12": self.tools_sha256_12,
            "budget": {"max_steps": self.max_steps, "max_searches": self.max_steps, "token_ceiling": self.token_ceiling},
            "stop": self.stop, "stop_detail": self.stop_detail,
            "model_calls": len(self.steps), "searches": self.searches, "tokens": self.tokens,
            "steps": self.steps, "passages": self.passages,
            "proposal": self.proposal, "proposal_as_given": self.proposal_as_given, "failures": self.failures,
            "reproducible": False,     # the same topic can give another proposal; this is a record, not a recipe
        }

    @classmethod
    def from_record(cls, record: dict) -> "Exploration":
        return cls(
            topic=record["topic"], document_id=record["document_id"],
            corpus_text_sha256=record.get("corpus_text_sha256"),
            max_steps=record["budget"]["max_steps"], token_ceiling=record["budget"]["token_ceiling"],
            started=record["started"], finished=record["finished"], stop=record["stop"],
            stop_detail=record.get("stop_detail", ""), steps=record["steps"], passages=record["passages"],
            proposal=record["proposal"], proposal_as_given=record.get("proposal_as_given"),
            failures=record.get("failures", []), prompt=record["prompt"],
            prompt_sha256_12=record["prompt_sha256_12"], tools_sha256_12=record["tools_sha256_12"],
            model=record["model"], provider=record["provider"], exploration_id=record.get("exploration_id"),
            document_ids=record.get("document_ids") or [], corpora=record.get("corpora") or {},
        )


# ---------------------------------------------------------------------------
# The budget, counted before anything is sent
# ---------------------------------------------------------------------------


def estimate(workspace, max_steps: int | None = None) -> dict:
    """A ceiling on what one exploration can use. No call is made.

    Each step re-sends the conversation so far, so input grows with every search.
    The ceiling assumes every step is a search returning the largest passages in
    the index and that every reply is as long as it is allowed to be. A real run
    uses a fraction of it. The token ceiling is also enforced: an exploration
    that reaches it is stopped.
    """
    settings = ask.settings
    steps = max_steps or settings.explorer_max_steps
    prompt, _ = checks.load_prompt(PROMPT)
    fixed = (len(prompt) + len(json.dumps(tools_for(workspace)))) // CHARS_PER_TOKEN
    largest = sorted((chunk.get("token_count", 0) for chunk in workspace.by_id.values()), reverse=True)
    per_search = sum(largest[:PASSAGES_PER_SEARCH])
    per_step = per_search + settings.explorer_step_max_tokens
    tokens_in = sum(fixed + done * per_step for done in range(1, steps + 1))
    tokens_out = steps * settings.explorer_step_max_tokens
    price_in, price_out = settings.llm_price_input_per_mtok, settings.llm_price_output_per_mtok
    priced = price_in is not None and price_out is not None
    return {
        "model_calls_at_most": steps, "searches_at_most": steps, "embedding_calls_at_most": steps,
        "input_tokens_ceiling": tokens_in, "output_tokens_ceiling": tokens_out,
        "token_ceiling": tokens_in + tokens_out,
        "cost_ceiling_usd": round((tokens_in * price_in + tokens_out * price_out) / 1_000_000, 4) if priced else None,
    }


def format_estimate(numbers: dict) -> str:
    lines = [f"model calls, at most        {numbers['model_calls_at_most']}",
             f"searches, at most           {numbers['searches_at_most']}  (one embedding call each)",
             f"input tokens, ceiling       {numbers['input_tokens_ceiling']:,}",
             f"output tokens, ceiling      {numbers['output_tokens_ceiling']:,}"]
    if numbers["cost_ceiling_usd"] is None:
        lines.append("No price is configured (LLM_PRICE_INPUT_PER_MTOK, LLM_PRICE_OUTPUT_PER_MTOK), so no cost is shown.")
    else:
        lines.append(f"cost, ceiling               ${numbers['cost_ceiling_usd']:.4f}")
    lines.append("A ceiling, not a forecast. The exploration is stopped if it reaches the token ceiling.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# The tools: plain code over the filtered sources
# ---------------------------------------------------------------------------


def _list_sources(workspace) -> str:
    lines = []
    for member in workspace.members:
        document = member.document
        opening = len(lines)
        lines.append(f"SOURCE: {document.short_title} — {document.author} ({document.year}), {document.title}"
                     + (f" [id: {document.document_id}; {len(member.sources.chunks)} passages]" if workspace.several else ""))
        for topic in member.topics():
            lines.append(f"  Chapter: {topic.chapter} ({topic.passages} passages)")
            lines += [f"    Section: {section.title} ({section.passages} passages)" for section in topic.sections]
        if len(lines) == opening + 1:
            # A source with no chapters (an article): its sections, as it prints them.
            titles = list(dict.fromkeys(chunk["section"] for chunk in member.sources.chunks if chunk.get("section")))
            lines += [f"  Section: {title}" for title in titles] or ["  This source prints no chapters or sections. Search it directly."]
    return "\n".join(lines)


def _search(workspace, run: Exploration, step: int, query: str, source: str | None = None) -> tuple[str, list[str]]:
    """The existing retrieval over the filtered sources. Returns what the model is
    shown (verbatim passages under stable handles; no page, no score) and the handles.
    With several sources it is the collection retrieval, capped per source, or one
    source alone when the agent names it."""
    if workspace.several:
        members = workspace.collection([source] if source else None)
        found = ask.retrieve_collection(query, members, PASSAGES_PER_SEARCH,
                                        PASSAGES_PER_SEARCH if source else ask.settings.per_source_passages)
    else:
        found = ask.retrieve(query, workspace.sources.vectors, workspace.sources.chunks,
                             PASSAGES_PER_SEARCH, workspace.document)
    by_chunk = {entry["chunk_id"]: handle for handle, entry in run.passages.items()}
    shown = []
    for item in found:
        chunk_id = item.chunk["chunk_id"]
        if chunk_id not in by_chunk:
            by_chunk[chunk_id] = f"P{len(run.passages) + 1}"
            run.passages[by_chunk[chunk_id]] = {"chunk_id": chunk_id, "score": round(item.score, 3), "step": step}
        shown.append(ask.EvidenceItem(by_chunk[chunk_id], item.chunk, item.score, item.document))
    return ask.render_evidence_block(shown), [item.handle for item in shown]


def check_proposal(given: dict, passages: dict[str, dict]) -> tuple[dict | None, list[str]]:
    """Whether a proposal may be put to the researcher. Never repaired: a proposal
    that names a passage no search returned is blocked whole (ADR 0014)."""
    failures: list[str] = []
    theme = " ".join(str(given.get("theme") or "").split())
    if not theme:
        failures.append("the proposal has no theme")
    sections, gaps = [], [" ".join(str(gap).split()) for gap in given.get("gaps") or [] if str(gap).strip()]
    for number, entry in enumerate(given.get("sections") or [], start=1):
        heading = " ".join(str(entry.get("heading") or "").split())
        question = " ".join(str(entry.get("question") or "").split())
        handles = [str(handle).strip().strip("[]") for handle in entry.get("passages") or []]
        unknown = [handle for handle in handles if handle not in passages]
        if unknown:
            failures.append(f"section {number} names passages no search returned: {', '.join(unknown)}")
            continue
        if not heading or not question:
            failures.append(f"section {number} has no heading or no question")
            continue
        if len(handles) > SECTION_PASSAGES:
            failures.append(f"section {number} carries {len(handles)} passages; the most is {SECTION_PASSAGES}")
            continue
        chunk_ids = list(dict.fromkeys(passages[handle]["chunk_id"] for handle in handles))
        if not chunk_ids:
            gaps.append(f"{heading}: no passage was found for “{question}”")      # a gap, not a section
            continue
        sections.append({"heading": heading, "question": question, "passages": chunk_ids})
    written = " ".join([theme, *gaps, *(f"{s['heading']} {s['question']}" for s in sections)])
    if ask.PAGE_CLAIM_RE.search(written):
        failures.append("the proposal writes a page number; pages are resolved from stored records only")
    if not failures and not MIN_SECTIONS <= len(sections) <= MAX_SECTIONS:
        failures.append(f"{len(sections)} section(s) have passages; an article needs {MIN_SECTIONS} to {MAX_SECTIONS}")
    if failures:
        return None, failures
    return {"theme": theme, "sections": sections, "gaps": gaps}, []


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------


def _status(run: Exploration, step: int) -> str:
    left = run.max_steps - step
    searches_left = run.max_steps - run.searches
    line = (f"STATUS: step {step} of {run.max_steps} used; {run.searches} search(es) made, {searches_left} left; "
            f"{len(run.passages)} distinct passage(s) seen.")
    if left <= 1:
        line += " This is your last step: call propose now with what you have."
    return line


def explore(workspace, topic: str, max_steps: int | None = None, on_step=None) -> Exploration:
    """Run one exploration. Never raises for what the model or the provider does:
    every ending is a recorded stop."""
    topic = " ".join(topic.split())
    if not topic:
        raise ValueError("Give the exploration a topic. The topic is yours to write.")
    settings = ask.settings
    prompt, digest = checks.load_prompt(PROMPT)
    steps = max_steps or settings.explorer_max_steps
    run = Exploration(
        topic=topic, document_id=workspace.document.document_id,
        corpus_text_sha256=workspace.manifest.get("corpus_text_sha256"),
        max_steps=steps, token_ceiling=estimate(workspace, steps)["token_ceiling"],
        document_ids=[member.document.document_id for member in workspace.members],
        corpora={member.document.document_id: member.manifest.get("corpus_text_sha256") for member in workspace.members},
        prompt_sha256_12=digest, tools_sha256_12=tools_hash(tools_for(workspace)),
        model=settings.llm_model, provider=settings.llm_provider,
    )
    tools = tools_for(workspace)
    messages = [{"role": "user", "content":
                 f"TOPIC\n=====\n{topic}\n\nSTATUS: step 0 of {steps} used; 0 searches made, {steps} left."}]

    def end(stop: str, detail: str = "") -> Exploration:
        run.stop, run.stop_detail, run.finished = stop, detail, _now()
        return run

    for step in range(1, steps + 1):
        used = run.tokens
        if used["input"] + used["output"] >= run.token_ceiling:
            return end(CAPPED, "the token ceiling was reached")
        try:
            reply = ask.call_explorer(prompt, messages, tools)
        except (Exception, SystemExit) as exc:      # recorded, never retried (hard rule 9)
            return end(FAILED, f"{type(exc).__name__}: {' '.join(str(exc).split())[:300]}")
        entry = {"step": step, "input_tokens": reply["usage"]["input_tokens"],
                 "output_tokens": reply["usage"]["output_tokens"], "calls": []}
        run.steps.append(entry)
        calls = reply["tool_calls"]
        if not calls:
            if on_step:
                on_step(entry)
            if reply["stop_reason"] in ("refusal", "max_tokens"):
                return end(FAILED, f"the reply ended with stop reason “{reply['stop_reason']}”")
            return end(STOPPED, "the model replied without calling a tool")

        results, proposed = [], None
        for call in calls:
            name, arguments = call["name"], call["input"] if isinstance(call["input"], dict) else {}
            logged = {"tool": name, "arguments": arguments, "returned": [], "error": None}
            if name == LIST_SOURCES:
                text = _list_sources(workspace)
            elif name == SEARCH and not str(arguments.get("query") or "").strip():
                text = logged["error"] = "a search needs a query"
            elif name == SEARCH and run.searches >= run.max_steps:
                text = logged["error"] = "the search budget is used; call propose with what you have"
            elif name == SEARCH and arguments.get("source") and arguments["source"] not in run.document_ids:
                text = logged["error"] = f"there is no source with the id {arguments['source']}"
            elif name == SEARCH:
                text, logged["returned"] = _search(workspace, run, step, str(arguments["query"]).strip(),
                                                   arguments.get("source") or None)
            elif name == PROPOSE:
                proposed = arguments
                logged["arguments"] = {"sections": len(arguments.get("sections") or []),
                                       "gaps": len(arguments.get("gaps") or [])}
                text = "The proposal was received."
            else:
                text = logged["error"] = f"there is no tool named {name}"
            entry["calls"].append(logged)
            results.append({"type": "tool_result", "tool_use_id": call["id"], "content": text,
                            **({"is_error": True} if logged["error"] else {})})
        if on_step:
            on_step(entry)
        if proposed is not None:
            run.proposal, run.failures = check_proposal(proposed, run.passages)
            if run.proposal is None:
                run.proposal_as_given = proposed
                return end(BLOCKED, "; ".join(run.failures))
            return end(PROPOSED)
        messages.append({"role": "assistant", "content": reply["content"]})
        messages.append({"role": "user", "content": results + [{"type": "text", "text": _status(run, step)}]})
    return end(CAPPED, f"{steps} steps were used without a proposal")


# ---------------------------------------------------------------------------
# Reading an exploration back
# ---------------------------------------------------------------------------


def format_proposal(workspace, run: Exploration) -> str:
    """The proposal for the researcher: pages come from stored provenance."""
    if run.proposal is None:
        return f"No proposal: {run.stop}" + (f" ({run.stop_detail})" if run.stop_detail else "") + "."
    lines = [f"THEME  {run.proposal['theme']}", ""]
    for number, section in enumerate(run.proposal["sections"], start=1):
        lines += [f"{number}. {section['heading']}", f"   {section['question']}"]
        for chunk_id in section["passages"]:
            chunk = workspace.by_id[chunk_id]
            where = chunk.get("section") or chunk.get("chapter") or ""
            who = workspace.document_of(chunk_id)
            lines.append(f"     {ask.page_phrase(chunk):<14} " + (f"{who.author} ({who.year}) — " if workspace.several else "") + where)
    if run.proposal["gaps"]:
        lines += ["", "GAPS, as the agent reported them"] + [f"  - {gap}" for gap in run.proposal["gaps"]]
    return "\n".join(lines)


def overlap(runs: list[Exploration]) -> dict:
    """How far several explorations of one topic agree on passages. An exploration
    is not reproducible (ADR 0014); this says by how much, as counts."""
    proposed = [{chunk_id for section in run.proposal["sections"] for chunk_id in section["passages"]}
                for run in runs if run.proposal]
    union = set().union(*proposed) if proposed else set()
    shared = set.intersection(*proposed) if proposed else set()
    return {"runs": len(runs), "with_a_proposal": len(proposed), "passages_in_any": len(union),
            "passages_in_all": len(shared), "per_run": [len(found) for found in proposed]}


DEFAULT_DIR = Path(__file__).resolve().parent.parent / "output" / "explorations"


def save(run: Exploration, out_dir: Path | None = None) -> Path:
    """Write the exploration's record. It holds ids, arguments and counts: no passage text."""
    out_dir = Path(out_dir or DEFAULT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    if run.exploration_id is None:
        base = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_exploration"
        candidate, attempt = base, 1
        while (out_dir / f"{candidate}.json").exists():
            attempt += 1
            candidate = f"{base}_{attempt}"
        run.exploration_id = candidate
    path = out_dir / f"{run.exploration_id}.json"
    partial = path.with_suffix(".json.partial")
    partial.write_text(json.dumps(run.as_record(), ensure_ascii=False, indent=1), encoding="utf-8")
    partial.replace(path)
    return path


def load(path: Path) -> Exploration:
    return Exploration.from_record(json.loads(Path(path).read_text(encoding="utf-8")))
