# CLAUDE.md

Routing file for AI assistants working in this repository. It says **what** this project is, **why**
it exists, and **how** to work in it. It deliberately does not duplicate architectural detail —
that lives in [`docs/plans/PLAN_V2.md`](docs/plans/PLAN_V2.md), which is authoritative.

---

## WHAT

**A source-grounded RAG research assistant for scholarly literature review** — it answers questions
from an authorised research collection and refuses when that collection lacks sufficient evidence.

**Tech stack, as built:** Python 3.11, plain scripts at the repository root (no package, no Typer
CLI), PyMuPDF extraction, a NumPy index of dense vectors with cosine ranking, Streamlit for the web
UI, and configurable embedding and generation providers. `PLAN_V2.md` also describes hybrid
dense/BM25 retrieval and a SQLite index; **those are planned, not built**. Where the plan and the
code differ, the code and the later plans (`PLAN_V3`–`V6`) and ADRs say what exists.

**Folder map** (what exists today):

```
config.py               the one settings object; the only place that reads the environment
ask.py                  the pipeline: retrieve, call_model, validate, render, run_query
ingest.py, layout.py    extraction and chunking; layout measurement for uploaded theses
upload.py, audit.py, identity.py, documents.py   the thesis library (PLAN_V4)
app.py, main.py         shells: Streamlit web UI, interactive loop
evaluate.py, evaluation/   the evaluation harness and its metrics (PLAN_V3, PLAN_V5)
article/, write_article.py   the article writer and its command line (PLAN_V6); article/explorer.py is
                        the exploring agent (PLAN_V7 §14, ADR 0014)
runs.py                 the query run log
scripts/                check_gold.py, results_tables.py, measure_thesis.py
prompts/                versioned prompt files, hashed into every run and article record
footnote_maps/          per-document footnote spans: ids and offsets, no thesis text
index/, data/canonical/ the built-in thesis's index and extraction — frozen, never rewritten
tests/                  the offline suite
docs/plans/             PLAN_V2 (architecture) to PLAN_V6; docs/decisions/ holds the ADRs
runs/, library/, output/   run records, uploaded theses, drafted articles — local, gitignored
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

The Typer CLI planned in `PLAN_V2.md` (`ingest`, `index`, `query`, `evaluate`, `baseline`) does not
exist. Today's entry points are plain scripts at the repository root:

```bash
python ingest.py                 # build index/ from the configured PDF (needs pymupdf, tiktoken)
python ask.py "<question>"       # single question; --json, --verbose-provenance, -k N
python main.py                   # interactive question loop
streamlit run app.py             # web chat UI

pip install -r requirements.txt -r requirements-dev.txt
python scripts/check_gold.py     # validate evaluation/questions_v1.yaml; no API call
pytest                           # offline suite; no API key, no network
python evaluate.py               # live evaluation run; spends API credit on both providers
python write_article.py --dry-run --title "<t>" --outline outline.txt   # planned article calls; sends nothing
```

`ask.py`, `main.py`, `app.py`, `evaluate.py` and the article writer (`article/`, `write_article.py`)
all go through `ask.run_query()`. Never add a second
pipeline. Tests replace the generation model at `ask.call_model`, and the exploring agent's model at
`ask.call_explorer`, and nowhere else; they never make a live call.

The exploring agent (`article/explorer.py`) is the one place a model chooses its own next step: which
search to make, up to a budget that code holds. It proposes a theme, an outline and passages; the
researcher approves before anything is drafted. It never writes article prose, a page number or a
verdict, and it is never used by `ask.py`, `main.py` or `evaluate.py`. Drafting, checking and judging
stay a fixed workflow: do not add a loop, a retry, or a model-chosen branch there.

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
