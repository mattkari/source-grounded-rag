# Retrieval-Augmented Generation (RAG) for Source-Grounded Scholarly Research and Literature Reviews

A research prototype investigating whether Retrieval-Augmented Generation can support scholarly
research and literature reviews while reducing — and helping researchers detect — AI-generated
hallucination. The system is a **scholarly research assistant, not a general-purpose chatbot**: it
answers questions using evidence retrieved from an authorised research collection (initially one
doctoral thesis by Melih Sönmez and one selected academic article, English only), preserves
attribution and qualification, presents disagreement rather than resolving it, labels its own
interpretation as interpretation, and provides citations traceable to a specific page. Its central
commitment is **source-grounded refusal**: when the collection does not contain sufficient evidence,
the system says so instead of filling the gap from general model knowledge. The AI analyses; the
researcher decides.

The corpus is intentionally small for a conference demonstration, but the architecture is
corpus-agnostic — another researcher should be able to replace the documents with a different
scholar's thesis, articles, books, or policy documents without rewriting the core RAG pipeline.

**Full architecture and implementation plan:** [`docs/plans/PLAN_V2.md`](docs/plans/PLAN_V2.md)

**Status:** Demo vertical slice implemented and running end to end — PDF ingestion, chunking with
page-accurate provenance, embeddings, brute-force retrieval, and grounded generation with refusal.
An interactive CLI (`main.py`) is implemented and on `main`. The full Sprint 1–7 structure in
`PLAN_V2.md` remains outstanding.

**Commands:**

```bash
python ingest.py                      # build index/ from data/thesis.pdf
python ask.py "<question>"            # single question
python ask.py --verbose-provenance "<question>"   # + chunk ids and verbatim passages
python main.py                        # interactive question loop
```

## Presentations

| File | Venue |
|---|---|
| [`docs/presentations/ITCC-2026-Source-Grounded-Research-Assistant.pptx`](docs/presentations/ITCC-2026-Source-Grounded-Research-Assistant.pptx) | 28th International Turkish Cooperative Congress (ITCC-2026), 14 August 2026 — 20-minute online session |
| [`docs/presentations/ITCC-2026-speaker-notes.md`](docs/presentations/ITCC-2026-speaker-notes.md) | The same speaker notes, exported as a run sheet with timings |

Sixteen slides covering the problem, the grounding and refusal design, the three demonstration
questions, the evaluator view, and current status. Three things to know before reusing it:

- The title and closing slides carry `[ Affiliation ]` and `[ email ]` placeholders.
- The interface screenshots come from the Streamlit web UI, which is not on `main` yet — it is on
  the `claude/streamlit-web-ui-eyheeg` branch.
- Those screenshots were captured with the model call stubbed. Page numbers, citations, section
  titles and retrieval scores in them are real — read from the index — but the generated prose is
  representative rather than a recorded model output.

## Task Log

Chronological record of completed and approved work. Rows are appended after each sprint is
implemented and approved — existing rows are never removed or reordered.

| Date | Sprint | Task | Status | Files Touched |
|---|---|---|---|---|
| 2026-08-11 | — (Planning) | Produce architecture and Agile implementation plan for the source-grounded RAG prototype | Planning complete — awaiting human approval | `docs/plans/PLAN_V2.md`, `README.md`, `CLAUDE.md` |
| 2026-08-11 | — (Demo slice) | Build the minimum end-to-end vertical slice: PyMuPDF extraction with printed-page and running-header provenance, chapter/section-bounded chunking (~700 tokens, 15% overlap), `text-embedding-3-large` embeddings, brute-force cosine retrieval (k=5), grounded generation with opaque `[En]` handles resolved to page-numbered footnotes by the renderer, refusal path, and blocking post-generation validation. 320 pages → 249 chunks. | Implemented and committed to `main` (`9577d6e`) | `config.py`, `embeddings.py`, `ingest.py`, `ask.py`, `prompts/system_grounded_v1.md`, `index/`, `data/canonical/` |
| 2026-08-12 | — (Demo slice) | Add `main.py` interactive CLI wrapper. Refactored `ask.py`'s core into a shared `run_query()` returning a `QueryOutcome`, so the single-question and interactive entry points call one pipeline; cached the Anthropic client and system prompt, and load the index once per session. Clean exit on `exit`/`quit`/`q`, Ctrl+C and Ctrl+D. All three demo questions re-run through both entry points: retrieval diagnostics and sufficiency labels byte-identical, generated prose varies (model nondeterminism). | Implemented; committed to `main` (`91ad972`) | `main.py`, `ask.py`, `README.md` |
| 2026-08-12 | — (Dissemination) | Prepare the 20-minute ITCC-2026 conference deck: 16 slides in English covering the hallucination and audit-trail problem, relevance to cooperative governance, the grounding pipeline, the opaque-handle mechanism that makes a fabricated page reference structurally impossible, the three outcome types, the three demonstration questions as UI screenshots, the evaluator view, and current status including what is not yet done. Speaker notes with per-slide timings on every slide, plus anticipated questions; notes also exported as a standalone run sheet. Screenshots captured from the web UI with the model call stubbed — provenance, citations and retrieval diagnostics in them are read from the real index. | Committed to `claude/itcc-2026-deck` | `docs/presentations/ITCC-2026-Source-Grounded-Research-Assistant.pptx`, `docs/presentations/ITCC-2026-speaker-notes.md`, `README.md` |
