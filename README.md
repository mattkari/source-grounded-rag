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
An interactive CLI (`main.py`) is implemented and on `main`; a Streamlit web UI (`app.py`) for the
conference demo is on `claude/streamlit-web-ui-eyheeg`. The full Sprint 1–7 structure in
`PLAN_V2.md` remains outstanding.

**Commands:**

```bash
python ingest.py                      # build index/ from data/thesis.pdf
python ask.py "<question>"            # single question
python ask.py --verbose-provenance "<question>"   # + chunk ids and verbatim passages
python main.py                        # interactive question loop
streamlit run app.py                  # web chat UI (conference demo)
```

`ask.py`, `main.py` and `app.py` are three shells over one pipeline — `ask.run_query()`. Retrieval,
grounded generation, validation and citation resolution exist in exactly one place; the entry points
differ only in how they present the result.

## Running the web interface

A minimal Streamlit chat UI for demonstrating the assistant to a non-technical audience. It runs
locally on the presenter's machine: no authentication, no deployment configuration, and no
persistence beyond the browser session.

**Prerequisites** — the index must already be built (`python ingest.py`), and both model roles need
credentials in the environment, since the UI embeds the question and calls the generation model on
every turn:

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install streamlit anthropic openai numpy python-dotenv
```

```bash
# .env (never committed) or exported in the shell
OPENAI_API_KEY=...        # embedding role — the index is built with text-embedding-3-large
ANTHROPIC_API_KEY=...     # generation role
```

**Start it:**

```bash
streamlit run app.py                            # opens http://localhost:8501
streamlit run app.py --server.port 8080         # if 8501 is taken
streamlit run app.py --server.headless true     # start without opening a browser
```

Stop the server with `Ctrl+C`. Conversation history lives in the browser session — reloading the
page clears it. The index is loaded once per server process, so the first question is slower than
the rest.

**What the interface shows.** The answer renders as ordinary prose with superscript reference
markers and a `Sources:` line resolved to printed page numbers from stored provenance. Full
chapter/section/page citations sit behind *Show full citation details*. When the collection lacks
evidence the assistant refuses in a plain, non-alarming notice — a refusal is correct behaviour, not
a failure. Passages that are the assistant's own inference rather than the author's stated position
appear in a separate, labelled *AI interpretation* callout. Retrieval similarity scores are
diagnostics, never a confidence measure, and are collapsed into *Technical details (for
evaluators)*. Provider, network and validation failures are reported in plain language, with the
technical detail one click away rather than as a traceback.

## Task Log

Chronological record of completed and approved work. Rows are appended after each sprint is
implemented and approved — existing rows are never removed or reordered.

| Date | Sprint | Task | Status | Files Touched |
|---|---|---|---|---|
| 2026-08-11 | — (Planning) | Produce architecture and Agile implementation plan for the source-grounded RAG prototype | Planning complete — awaiting human approval | `docs/plans/PLAN_V2.md`, `README.md`, `CLAUDE.md` |
| 2026-08-11 | — (Demo slice) | Build the minimum end-to-end vertical slice: PyMuPDF extraction with printed-page and running-header provenance, chapter/section-bounded chunking (~700 tokens, 15% overlap), `text-embedding-3-large` embeddings, brute-force cosine retrieval (k=5), grounded generation with opaque `[En]` handles resolved to page-numbered footnotes by the renderer, refusal path, and blocking post-generation validation. 320 pages → 249 chunks. | Implemented and committed to `main` (`9577d6e`) | `config.py`, `embeddings.py`, `ingest.py`, `ask.py`, `prompts/system_grounded_v1.md`, `index/`, `data/canonical/` |
| 2026-08-12 | — (Demo slice) | Add `main.py` interactive CLI wrapper. Refactored `ask.py`'s core into a shared `run_query()` returning a `QueryOutcome`, so the single-question and interactive entry points call one pipeline; cached the Anthropic client and system prompt, and load the index once per session. Clean exit on `exit`/`quit`/`q`, Ctrl+C and Ctrl+D. All three demo questions re-run through both entry points: retrieval diagnostics and sufficiency labels byte-identical, generated prose varies (model nondeterminism). | Implemented; committed to `main` (`91ad972`) | `main.py`, `ask.py`, `README.md` |
| 2026-08-12 | — (Demo slice) | Add `app.py`, a Streamlit web chat UI for the conference demo — the third shell over `ask.run_query()`, adding no retrieval, generation, citation or validation logic of its own. Index loaded once per process (`st.cache_resource`); conversation history in `st.session_state` only. Renders a sufficient answer as prose with a `Sources:` line and collapsible full citations, a refusal as a plain non-alarming notice, `[AI INTERPRETATION]` as a distinct labelled callout, and retrieval scores collapsed into "Technical details (for evaluators)" captioned as diagnostics rather than confidence. Provider/auth/network errors and validation failures are reported in plain language, never as a traceback. Verified: the real index loads and the provider-failure path renders correctly; the three demo questions were exercised through the real provenance, citation and validation code with the model call stubbed — **the live end-to-end run against the API is still outstanding and must be done before the demo**. | Implemented; pushed to `claude/streamlit-web-ui-eyheeg` (`3d5b62f`) — awaiting review | `app.py`, `README.md` |
