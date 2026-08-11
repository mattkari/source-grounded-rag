# CLAUDE.md

Routing file for AI assistants working in this repository. It says **what** this project is, **why**
it exists, and **how** to work in it. It deliberately does not duplicate architectural detail —
that lives in [`docs/plans/PLAN_V2.md`](docs/plans/PLAN_V2.md), which is authoritative.

---

## WHAT

**A source-grounded RAG research assistant for scholarly literature review** — it answers questions
from an authorised research collection and refuses when that collection lacks sufficient evidence.

**Tech stack:** not yet chosen in code. The plan recommends Python 3.11+ with a Typer CLI, PyMuPDF
extraction, a NumPy + SQLite index, hybrid dense/BM25 retrieval, and configurable embedding and
generation providers. **Nothing is installed and no source code exists.** Treat the stack as
proposed, not decided, until Sprint 1 is approved.

**Folder map** (planned; only the starred entries exist today):

```
docs/plans/PLAN_V2.md   ★ authoritative architecture + sprint plan
README.md               ★ overview + Task Log (append a row after each approved sprint)
CLAUDE.md               ★ this file
corpus.yaml               declares the authorised research collection
prompts/                  versioned prompt files, hashed into every run record
src/sgrag/                config, models, ingestion, chunking, providers, index,
                          retrieval, generation, citation, evaluation, runs, cli
tests/                    unit, provenance, contract, golden, integration
data/                     raw / canonical / index / runs  — all gitignored
```

---

## WHY

The project investigates whether source-grounded retrieval reduces unsupported claims and improves
traceability, compared to the same model answering from parametric knowledge alone. The software is
therefore **experimental apparatus as much as it is a product**. Two consequences shape everything:

- **Runs are evidence.** Every run must be fully recorded and reproducible.
- **The RAG and no-RAG conditions must differ in exactly one variable** — the presence of retrieved
  evidence. Anything that introduces a second difference invalidates the comparison.

**Guiding principle: the AI analyses, the researcher decides.** The system may retrieve, ground,
attribute, qualify, surface disagreement, and flag its own uncertainty. It may not adjudicate
scholarly questions, resolve contradictions on the author's behalf, or present its inference as the
author's published position.

---

## HOW

### Commands

None yet — no code exists. Commands will be added here as sprints are approved and implemented.
The planned CLI surface is `ingest`, `index`, `query`, `evaluate`, `baseline`.

### Environment variables

Configuration is read **once**, at startup, into a single validated settings object. Never call
`os.getenv` from application code. `.env` is never committed; `.env.example` documents every
variable. Embedding and generation are two independent model roles:

```bash
EMBEDDING_PROVIDER=...     # which embedding vendor/backend
EMBEDDING_MODEL=...        # which embedding model
LLM_PROVIDER=anthropic     # which generation vendor
LLM_MODEL=...              # which generation model
ANTHROPIC_API_KEY=...      # credentials, always from the environment
OPENAI_API_KEY=...
```

Note that Anthropic offers no embeddings endpoint, so `LLM_PROVIDER=anthropic` necessarily implies a
different embedding provider. That is a real constraint, not an oversight.

### Hard rules

1. **Never hard-code model names.** A vendor model string may appear only in `providers/` and
   `.env.example`. Not in retrieval, generation, evaluation, tests, or the CLI.
2. **Never invent page numbers.** The generation model emits opaque evidence handles (`[E3]`), never
   page numbers. The citation renderer resolves pages from stored provenance. A page number that is
   not present in the canonical extraction must never reach the output.
3. **Never hard-code credentials.** Environment or secret store only. Nothing key-shaped in source,
   prompts, logs, run records, or commits.
4. **Never treat similarity as confidence.** Retrieval scores are diagnostics. They are never
   rendered as a confidence figure and never the sole basis for a refusal.
5. **Never cite a derived field.** Chapter summaries, major findings, and extracted concepts may aid
   retrieval; only the verbatim source passage is admissible evidence.
6. **Never silently invent structure or metadata.** If a chapter boundary, author, or year cannot be
   resolved confidently, leave it null and flag it for human verification.
7. **The canonical extraction is immutable.** Once written, per-page extracted text is never
   rewritten by a downstream stage. A generated summary never replaces the original source.
8. **Never let a chunk cross a chapter boundary.** A chunk spanning two chapters produces a citation
   that is false at one end.
9. **Never silently retry or swallow a failure.** Malformed model output, unresolvable citations,
   and provider errors are recorded outcomes, not conditions to hide. A validation failure is a
   research result.
10. **Never add infrastructure without a stated requirement.** The corpus is two documents. Prefer
    simple, transparent, reproducible, portable.
11. **Refusals are statements about the collection, not about the world.** Phrase them that way.
12. **Do not treat a heuristic as proof.** Synthetic-consensus and quality flags raise cases for
    human review; the reported verdict is always the human's.

### Working process

Sprints run **PLAN → IMPLEMENT → TEST → REVIEW → APPROVE → NEXT SPRINT**. Human approval is required
before each significant implementation step.

- Do not begin a sprint that has not been approved.
- Do not implement ahead of the current sprint's scope, even when the next step seems obvious.
- After a sprint is implemented **and approved**, append one row to the `## Task Log` table in
  `README.md` (`Date | Sprint | Task | Status | Files Touched`). Append only — never remove or
  reorder existing rows.
- Architectural decisions taken between plans are recorded as short ADRs in `docs/decisions/`.
- Approved plans are not edited in place; a new phase gets a new `docs/plans/PLAN_V<n>.md`.

### Where to look

| Question | Go to |
|---|---|
| Architecture, components, data flow | `PLAN_V2.md` §2–§3 |
| PDF ingestion and why not plain Markdown | `PLAN_V2.md` §4 |
| Document model, metadata, chunking | `PLAN_V2.md` §5–§7 |
| Embedding and retrieval strategy | `PLAN_V2.md` §8–§10 |
| Provenance invariants and citations | `PLAN_V2.md` §11–§12 |
| Grounded generation, refusal, partial, conflict, interpretation | `PLAN_V2.md` §13–§17 |
| Evaluation, synthetic consensus, RAG/no-RAG baseline | `PLAN_V2.md` §17, §19–§20 |
| Provider abstractions, env vars, security | `PLAN_V2.md` §21–§24 |
| Testing and reproducibility | `PLAN_V2.md` §25–§26 |
| Sprint definitions and acceptance criteria | `PLAN_V2.md` §30 |
| Risks, open decisions, assumptions | `PLAN_V2.md` §31–§33 |
