# ADR 0014 — An exploring agent that proposes, behind a human gate

Date: 17 November 2026. Status: proposed (scope chosen by the researcher; see `PLAN_V7.md` §14).
Amends decision 1 of ADR 0013, and narrows "a workflow, not an agent" in ADR 0005 and ADR 0008 to
drafting, checking and judging.

## The question

ADR 0013 kept everything a fixed workflow. The researcher then asked for an agent, built on what
the tools used by research institutions actually do. What is the smallest agent that carries what
those tools have shown to work, without giving up what this project's runs are for?

## What was read

Figures are the authors' own; none was reproduced.

| System | What it is | Source |
|---|---|---|
| PaperQA2 (FutureHouse) | A true agent: the model picks among paper search, gather evidence, citation traversal and answer | arXiv:2409.13740; github.com/Future-House/paper-qa |
| Anthropic Research | A true agent: a lead agent, parallel subagents, a separate citation agent | anthropic.com/engineering/built-multi-agent-research-system |
| Google AI co-scientist | Several agents under a supervisor; the scientist sets and refines the goal | arXiv:2502.18864 |
| Ai2 Scholar QA | A fixed pipeline: quotes are extracted, an outline is planned with quotes assigned to sections, then sections are written | arXiv:2504.10861 |
| OpenScholar | A fixed pipeline with a rerank and a citation check | arXiv:2411.14199 |
| STORM, Co-STORM (Stanford) | Scripted; Co-STORM lets the user take a turn at any time | arXiv:2402.14207, 2408.15232 |
| Elicit systematic review | Fixed stages with a human gate at each | Elicit's support pages |
| Argonne AISAC | A bounded planner; the user fixes the allowed tools and sources | arXiv:2511.14043 |

What they show:

- **Where an agent helped.** PaperQA2 with its agent was more accurate than the same parts in a
  hard-coded order (p = 0.015). The authors credit re-searching. It averaged 1.26 searches a
  question, on open literature.
- **A budget, and a status line.** PaperQA2 gives the agent a running count of evidence and cost
  and a timeout. Anthropic writes effort rules into the prompt after early runs spawned far too
  many subagents and searched endlessly for sources that did not exist.
- **Evidence chosen before writing.** Scholar QA assigns quotes to sections before any section is
  written. PaperQA2's writer may cite only what was gathered. Removing PaperQA2's per-passage
  relevance scoring lowered accuracy; doing it with a weak model was worse than not doing it.
- **A person approves a plan.** Elicit, Co-STORM and the co-scientist each put a person before the
  costly or consequential step. None of them has a verdict on every sentence; this project does.
- **Simple is not worse.** On AstaBench (arXiv:2510.21652), commercial literature agents did not
  do significantly better than a plain tool loop; weak models took more steps and cost twice as much.
- **What remains.** STORM still left about 15% of sentences unsupported by their citation.

Not found: a primary account of the design of FutureHouse's platform agents, Consensus, Undermind
or scite; any documented literature agent at CERN, Oxford, MIT or Lawrence Berkeley.

## Decision

A single agent, no subagents, that **explores and proposes**:

1. The model chooses searches over the researcher's chosen sources, in a loop, with three tools
   that are plain code: list the sources, search, propose.
2. Code holds the budget: a step cap and a cost ceiling accepted beforehand.
3. The agent's only output is a proposal: theme, outline, passages per section, gaps. Code checks
   that every passage named was really returned by a search in that run.
4. The researcher edits and approves the proposal before anything is drafted.
5. Sections are drafted only from approved passages, by the existing call and validation.
6. Every step is recorded and shown in the trace.
7. The fixed path stays and is the baseline.

This takes from the institutions' tools the loop (PaperQA2), the budget and status line (PaperQA2,
Anthropic), evidence assigned before writing (Scholar QA), the writer confined to that evidence
(PaperQA2) and the human gate (Elicit).

## What stays deterministic, and why this does not break the project's rules

- Retrieval, ranking, the footnote and reference filter, page resolution, validation, the checks
  of form, the budget, the log and the refusal are code. The model never writes a page number
  (hard rule 2), sees no similarity score (hard rule 4), and is shown only verbatim passages
  (hard rule 5).
- The loop is not a retry. Each step is a recorded search the researcher can read; a failure ends
  the run and is shown (hard rule 9).
- The agent proposes; the researcher decides the theme, the outline and the evidence, and still
  judges every sentence. "The AI analyses, the researcher decides" holds.
- The evaluation does not use it. The RAG and no-RAG conditions still differ in one variable.
- Drafting, checking and judging remain a workflow, as ADR 0005 and 0008 require. Those ADRs are
  narrowed, not reversed: the model still never decides what happens to a drafted sentence.
- It is a stated requirement from the researcher (hard rule 10), and it adds no framework.

## Not adopted, and why

- **Per-passage relevance scoring by the model.** It helped PaperQA2, but it multiplies calls, and
  a model's relevance score would sit close to a model's verdict. Left for a later decision.
- **Subagents and a citation agent.** For a few dozen PDFs they buy nothing; citations here are
  resolved by code already.
- **Write-and-revise loops.** OpenScholar's feedback loop made answers worse about a fifth of the
  time, and it would put the model's judgement where the researcher's verdict is.

## Limits

- No evidence yet that the agent finds more than the coverage map on a closed collection. The
  sprint's acceptance is a trial of exactly that, with three runs to show how much they differ.
- An exploration cannot be reproduced; only recorded.
- A proposal may be approved without being read closely. The record shows what was changed before
  approval, which is the only trace of how carefully it was read.

## As built in Sprint A1

- The loop, tools, budget and check are `article/explorer.py`; the one model boundary is
  `ask.call_explorer`. The request offers the tools with `tool_choice` left to the model and strict
  schemas. No fallback to another model is configured: a refusal ends the run and is recorded, so
  the model named in the record is the model that ran.
- The budget is two caps and a ceiling: at most `EXPLORER_MAX_STEPS` model calls, as many searches
  (a search past it is refused and logged), and a token ceiling computed before the first call.
- A blocked proposal is not sent back to the model to correct. That would be a repair loop; the
  researcher can explore again.
- `search` takes a query only. A `source` argument arrives with several sources (Sprint M3).
- In the view the researcher can reword, drop a section and drop a passage. Adding a passage of
  their own choosing waits for the coverage map (Sprint M3); `pipeline.approve` already accepts and
  counts such additions.
- The article record moved to schema 5 here, earlier than `PLAN_V7.md` §7 said.
