"""The three workflows of this project, written down once — ADR 0012.

Asking a question, drafting an article and running the evaluation are each a
fixed sequence of steps. None has a loop, a retry, or a step where a model
decides what happens next. One step, exploring, is a bounded agent: inside it
the model chooses its own searches, and its output is a proposal (ADR 0014). This module states those sequences as data, and
`docs/workflows.md` is generated from it by `scripts/workflow_diagrams.py`.

It is a description, kept honest by tests rather than by hand: every step names
the functions that carry it out, and a test fails if one of them no longer
exists, if the committed diagram differs from what this module generates, or if
a workflow gains a cycle. The article trace (`article/trace.py`) reports its
steps under the ids used here, so the picture and the trace cannot drift apart.

Nothing here runs anything. It is not an orchestration layer.
"""

from __future__ import annotations

from dataclasses import dataclass

RESEARCHER, MODEL, EMBEDDING, CHECK, PLAIN = "researcher", "model call", "embedding call", "check", "no model"
# One step inside which the model chooses its own next search, up to a budget that code holds
# (ADR 0014). The workflow around it still has no loop: the step has one way in and one way out.
AGENT = "agent, bounded"
KINDS = (RESEARCHER, MODEL, EMBEDDING, CHECK, PLAIN, AGENT)


@dataclass(frozen=True)
class Step:
    id: str
    label: str
    kind: str
    code: tuple[str, ...] = ()            # the functions that carry the step out
    then: tuple[tuple[str, str], ...] = ()  # (next step id, what leads there); empty label = always
    optional: bool = False


ASK = (
    Step("question", "The researcher asks a question", RESEARCHER, (), (("embed", ""),)),
    Step("embed", "Embed the question", EMBEDDING, ("embeddings.embed_texts",), (("retrieve", ""),)),
    Step("retrieve", "Rank the passages by similarity", PLAIN, ("ask.retrieve",), (("generate", ""),)),
    Step("generate", "Answer from the passages, citing handles", MODEL, ("ask.call_model",), (("validate", ""),)),
    Step("validate", "Validate the answer", CHECK, ("ask.validate",),
         (("render", "passed"), ("ungrounded", "failed"))),
    Step("ungrounded", "Shown as not grounded; recorded, not retried", PLAIN, (), (("log", ""),)),
    Step("render", "Render: pages from stored provenance", PLAIN, ("ask.render", "ask.page_phrase"), (("log", ""),)),
    Step("log", "Record the run", PLAIN, ("runs.append",)),
)

ARTICLE = (
    Step("explore", "Explore the sources and propose a theme, an outline and passages", AGENT,
         ("article.explorer.explore", "article.explorer.check_proposal"), (("outline", ""),), optional=True),
    Step("outline", "Title and outline: written, or a proposal edited and approved", RESEARCHER,
         ("article.topics.outline", "article.pipeline.approve", "article.pipeline.new_draft"),
         (("preview", ""),)),
    Step("preview", "Retrieval preview", EMBEDDING, ("article.pipeline.preview",), (("sources", ""),), optional=True),
    Step("sources", "Source filter: no footnotes, no reference list", PLAIN, ("article.sources.open_sources",),
         (("section", ""),)),
    Step("section", "Draft each section through the Ask pipeline, or from approved passages", MODEL,
         ("article.pipeline.draft_section", "ask.run_query", "ask.draft_from_evidence"), (("checks", ""),)),
    Step("checks", "Validation and checks of form", CHECK, ("ask.validate", "article.checks.prose_failures"),
         (("editorial", "passed"), ("blocked", "failed"))),
    Step("blocked", "Section left out; reason shown, not retried", PLAIN, ("article.assemble.block_reason",)),
    Step("editorial", "Editorial pass: kept only if it preserves", MODEL,
         ("article.pipeline.edit_section", "article.checks.editorial_failures"), (("sentences", ""),), optional=True),
    Step("sentences", "Sentence by sentence: hold back the unnoted", CHECK, ("article.assemble.assemble",),
         (("review", ""),)),
    Step("review", "Verdict on each sentence and note; edit or delete", RESEARCHER,
         ("article.pipeline.set_pair_verdict", "article.pipeline.edit_sentence", "article.pipeline.delete_sentence",
          "article.pipeline.keep_as_own_words"), (("raised", ""), ("frame", ""))),
    Step("raised", "Raised to read: reported speech, shared terms; a second opinion on request (one model call)", CHECK,
         ("article.checks.reported_speech_flags", "article.terms.shared_terms", "article.pipeline.second_opinion"),
         optional=True),
    Step("frame", "Introduction and conclusion: written, or a suggestion edited", RESEARCHER,
         ("article.pipeline.suggest_frame", "article.pipeline.set_frame"), (("export", ""),), optional=True),
    Step("export", "Export, only when every sentence is judged", PLAIN,
         ("article.pipeline.export_blockers", "article.pipeline.export")),
)

EVALUATION = (
    Step("questions", "The researcher writes the questions and gold pages", RESEARCHER, (), (("gold", ""),)),
    Step("gold", "Check the gold pages against the printed labels", CHECK, ("scripts.check_gold.main",),
         (("run", "passed"),)),
    Step("run", "Each question through the Ask pipeline", MODEL, ("evaluate.evaluate_question", "ask.run_query"),
         (("baseline", ""), ("metrics", ""))),
    Step("baseline", "The same questions with retrieval switched off", MODEL, ("evaluate.run",),
         (("metrics", ""),), optional=True),
    Step("metrics", "Count: n of N, never an average alone", PLAIN, ("evaluation.metrics.summarise",),
         (("rating", ""),)),
    Step("rating", "The researcher rates the answers", RESEARCHER, ("evaluate.write_rating_sheet",),
         (("tables", ""),)),
    Step("tables", "Results tables for the paper", PLAIN, ("scripts.results_tables.main",)),
)

WORKFLOWS = {"Asking a question": ASK, "Drafting an article": ARTICLE, "Running the evaluation": EVALUATION}
# Where one workflow uses another: (from workflow, step id, to workflow).
SHARED = (("Drafting an article", "section", "Asking a question"),
          ("Running the evaluation", "run", "Asking a question"))

_SHAPES = {RESEARCHER: ('(["', '"])'), MODEL: ('{{"', '"}}'), EMBEDDING: ('[/"', '"/]'), CHECK: ('[["', '"]]'),
           PLAIN: ('["', '"]'), AGENT: ('>"', '"]')}


def mermaid(steps: tuple[Step, ...]) -> str:
    """One workflow as a Mermaid flowchart. A step's kind is in its shape and in its words."""
    lines = ["flowchart TD"]
    for step in steps:
        opening, closing = _SHAPES[step.kind]
        tail = ", optional" if step.optional else ""
        lines.append(f"    {step.id}{opening}{step.label}<br/><i>{step.kind}{tail}</i>{closing}")
    for step in steps:
        for target, label in step.then:
            lines.append(f"    {step.id} -->|{label}| {target}" if label else f"    {step.id} --> {target}")
    return "\n".join(lines)


def document() -> str:
    """`docs/workflows.md`, whole."""
    out = [
        "# The three workflows",
        "",
        "Generated by `python scripts/workflow_diagrams.py` from `workflows.py`. Do not edit by hand:",
        "a test fails if this file and that module disagree, or if a function a step names no longer exists.",
        "",
        "Each workflow is a fixed sequence. None has a loop or a retry, and no step lets a model decide",
        "what happens next. The one exception is inside a single step: while exploring, the model chooses",
        "its own next search, up to a budget that code holds, and what it produces is a proposal the",
        "researcher approves. A step's kind is written in it:",
        "",
        "| Kind | Shape | Meaning |",
        "|---|---|---|",
        "| researcher | rounded | a person decides or writes |",
        "| model call | hexagon | the generation model is called, and credit is spent |",
        "| embedding call | slanted | the embedding provider is called |",
        "| check | double-edged box | plain code that passes, blocks or raises; never a model's verdict |",
        "| no model | rectangle | plain code |",
        "| agent, bounded | flag | the model chooses its own searches inside this step, up to a fixed budget; "
        "every call is recorded |",
        "",
    ]
    for name, steps in WORKFLOWS.items():
        out += [f"## {name}", "", "```mermaid", mermaid(steps), "```", ""]
        out += ["| Step | Kind | Carried out by |", "|---|---|---|"]
        out += [f"| {step.label} | {step.kind}{' (optional)' if step.optional else ''} | "
                + (", ".join(f"`{code}`" for code in step.code) or "the researcher") + " |" for step in steps]
        out.append("")
    out += ["## How they connect", "",
            "There is one pipeline. Drafting and evaluating both send their questions through it; neither",
            "has a retrieval or citation path of its own.", "", "```mermaid", "flowchart LR"]
    for number, name in enumerate(WORKFLOWS):
        out.append(f'    w{number}["{name}"]')
    names = list(WORKFLOWS)
    for source, step_id, target in SHARED:
        label = next(step.label for step in WORKFLOWS[source] if step.id == step_id)
        out.append(f"    w{names.index(source)} -->|{label}| w{names.index(target)}")
    out += ["```", ""]
    return "\n".join(out)
