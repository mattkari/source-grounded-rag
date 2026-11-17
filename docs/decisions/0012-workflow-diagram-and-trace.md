# ADR 0012 — A generated workflow diagram and an article trace, not a graph framework

Date: 16 November 2026. Status: proposed (awaiting the researcher's approval).

## The question

The article writer has grown to a dozen steps, and two things had become hard to see: what the
whole sequence is, and why one particular article came out as it did (a section left out, a rewrite
rejected, sentences held back). A node-and-edge tool such as LangGraph Studio shows both. Should
the project adopt one?

## Decision

No framework. Two small things instead, both plain code.

- **The workflows are written down once, as data** (`workflows.py`): asking a question, drafting an
  article, running the evaluation. Each step has a kind (researcher, model call, embedding call,
  check, no model) and names the functions that carry it out. `docs/workflows.md` is generated from
  it by `scripts/workflow_diagrams.py` as Mermaid diagrams, which GitHub draws without any tool.
- **An article has a trace** (`article/trace.py`): for each step, what went in, what came back, and
  why anything was blocked, rejected or held back. It is shown in the Finish step of the view and
  printed by `python write_article.py --trace <article-id>`. It is built from the saved draft and
  makes no call. Passages appear by page and score, never by text.

The module describes; it does not run anything. It is not an orchestration layer, and the pipeline
does not read it.

## Why not a graph framework

- A studio draws a graph by running it under its own runtime. The article writer would have to be
  rewritten as that runtime's nodes, and every drafted section would then take a second route
  beside `ask.run_query` — the second pipeline the project forbids.
- The frameworks exist to make loops, retries and model-chosen branches easy. This project refuses
  all three (hard rule 9; ADR 0005; ADR 0008). The value they add is the thing ruled out.
- It is infrastructure without a stated requirement (hard rule 10), and the hosted studio sends
  run data, which here includes thesis passages, to a third party.

## What keeps the picture honest

A drawing that nobody checks goes stale. Tests fail when:

- a step names a function that no longer exists;
- the committed `docs/workflows.md` differs from what `workflows.py` generates;
- a workflow gains a cycle, or a step is cut off from the rest;
- a model call is followed by a branch, which would mean the model chose the next step;
- the trace uses a step id the diagram does not have, prints passage text, or makes a call.

A step's kind is written in its words as well as its shape, so the diagram does not depend on
shape or colour alone (ADR 0004).

## Limits

- The description is checked against the names of functions, not their behaviour. A function that
  keeps its name and starts retrying would not be caught here; the pipeline's own tests cover that.
- The trace reads what the record holds. A step that failed before anything was saved leaves only
  its recorded error.
- The trace covers articles. A question's run is already one record in the run log.
- Not verified: the diagrams as GitHub draws them (they were rendered locally with Mermaid 10), and
  the trace on a phone.
