# Retrieval-Augmented Generation (RAG) for Source-Grounded Scholarly Research and Literature Reviews

A research prototype investigating whether Retrieval-Augmented Generation can support scholarly
research and literature reviews while reducing — and helping researchers detect — AI-generated
hallucination. The system is a **scholarly research assistant, not a general-purpose chatbot**: it
answers questions using evidence retrieved from an authorised research collection (currently one
doctoral thesis — Karimov (2017), *The Qur’anic Concept of Justice (al-ʿAdl) from a Nursian
Perspective*, Durham — English only), preserves
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
All three entry points are on `main`: the single-question CLI (`ask.py`), the interactive CLI
(`main.py`) and the Streamlit web UI (`app.py`, merged in PR #1). The full Sprint 1–7 structure in
`PLAN_V2.md` remains outstanding.

The corpus is swappable: which document is indexed, and the measured layout constants needed to
extract it, are a profile in `config.py` — see [`docs/decisions/`](docs/decisions/). A second
calibrated corpus (Leung (2019), *Who Will Govern Artificial Intelligence?*) is kept on
`feature/swap-corpus-leung` as a working fallback.

**Command reference:**

```bash
python ingest.py                                  # build index/ from the configured PDF (run once)
streamlit run app.py                              # web chat UI (conference demo)
python main.py                                    # interactive question loop
python ask.py "<question>"                        # single question
python ask.py --verbose-provenance "<question>"   # + chunk ids and verbatim passages
python ask.py --json "<question>"                 # raw run record for evaluation
```

`ask.py`, `main.py` and `app.py` are three shells over one pipeline — `ask.run_query()`. Retrieval,
grounded generation, validation and citation resolution exist in exactly one place; the entry points
differ only in how they present the result. The same question therefore produces the same retrieval
diagnostics and the same sufficiency verdict in all three, whatever the surface.

---

## Getting started

Steps 1–3 are needed once, whichever interface you intend to use.

### 1. Install the dependencies

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install streamlit anthropic openai numpy python-dotenv pymupdf tiktoken
```

Python 3.11+. `pymupdf` and `tiktoken` are used by ingestion only; the three query entry points need
the rest.

### 2. Provide credentials

Two independent model roles, so two keys. Put them in a `.env` file at the repository root (never
committed) or export them in the shell:

```bash
# .env
OPENAI_API_KEY=...        # embedding role — the index is built with text-embedding-3-large
ANTHROPIC_API_KEY=...     # generation role
```

Anthropic offers no embeddings endpoint, so the two roles necessarily use different vendors. Both
keys are read at startup, from the environment only; nothing key-shaped is ever written to source,
prompts, logs or run records.

### 3. Build the index

```bash
python ingest.py
```

Reads the PDF named by `pdf_path` in `config.py`, writes the canonical per-page extraction to
`data/canonical/` and the index to `index/` (`vectors.npy`, `chunks.json`, `manifest.json`). It
prints what it found — pages, chapters, section segments, chunk count — and flags any page whose
printed number could not be resolved rather than guessing it. Embedding is batched (64 chunks per
API call), so this is the one step that takes a noticeable while; the current run is 288 pages →
266 chunks.

Run this once. Re-run it only after changing the PDF, the chunking parameters or the embedding
model — the query entry points refuse to start if the index was built with a different embedding
model than the one currently configured.

### 4. Ask a question

Pick whichever interface fits the audience: the web UI for a live demonstration, the interactive CLI
for a working session, `ask.py` for a scripted or single question.

---

## Using the web chat UI (`app.py`)

A minimal Streamlit chat interface for demonstrating the assistant to a non-technical audience. It
runs locally on the presenter's machine: no authentication, no deployment configuration, and no
persistence beyond the browser session.

**Step 1 — check the prerequisites.** `index/` must exist (step 3 above) and both API keys must be
in the environment (step 2). The UI embeds your question and calls the generation model on every
turn, so it is not usable offline.

**Step 2 — start the server.**

```bash
streamlit run app.py                            # opens http://localhost:8501
streamlit run app.py --server.port 8080         # if 8501 is already taken
streamlit run app.py --server.headless true     # start without opening a browser
```

Streamlit prints a Local URL and a Network URL. The Network URL works from another device on the
same network — useful for driving the demo from a phone or a second laptop.

**Step 3 — confirm the collection loaded.** The page header shows the document short title and the
number of indexed passages (`Karimov (2017), Qur’anic Concept of Justice thesis — 266 indexed
passages`). If the
index is missing or was built with a different embedding model you get a plain notice saying no
questions can be answered yet, with the technical reason under *Technical details (for evaluators)*.
Fix the index, then reload the page.

**Step 4 — ask.** Type into the chat box at the bottom and press Enter. The first question is slower
than the rest — the index is loaded once per server process and cached, not once per question. A
typical grounded answer takes a few tens of seconds, most of it generation.

**Step 5 — read the answer.** The default view carries the answer and its sources; the technical
material is one click away rather than hidden:

- **The answer** renders as ordinary prose with superscript reference markers, followed by a
  `Sources:` line resolved to printed page numbers (`Sources: [1] pp. 28–29, [2] pp. 30–31`).
  Every page number comes from stored provenance — the generation model never emits one.
- **Show full citation details** expands each reference to author, year, chapter, section and pages.
- **Reference-list sources are labelled.** The bibliography is indexed so that questions about what
  the thesis *cites* can be answered, but it is tagged as apparatus: the model is told it supports
  only bibliographic claims, and any citation drawn from it is marked *(reference list)*. A cited
  title is never treated as evidence of its own contents.
- **Limits of this answer** and **Not covered by the collection** state what the retrieved evidence
  does and does not support.
- **AI interpretation** appears as a separate labelled callout when the assistant draws its own
  inference. That is the assistant reasoning, not the author's published position, and it is marked
  as such rather than blended into the prose.
- **A refusal** appears as a plain, non-alarming notice when the collection lacks sufficient
  evidence. This is correct behaviour, not a failure — and it is phrased as a statement about the
  collection, not about the world. Worth demonstrating deliberately: ask something the thesis does
  not cover.
- **Technical details (for evaluators)** holds the retrieval table (evidence handle, similarity
  score, pages, chapter/section), the evidence-sufficiency verdict, the generation model, the prompt
  hash and the passage count. Similarity scores are diagnostics; they are never a confidence
  measure, and never the sole basis for a refusal.
- **A validation failure** is reported in plain language above the technical section, with the
  specific failed checks listed inside it. Provider, authentication and network errors are reported
  the same way — a short sentence, with the exception text one click away rather than a traceback.

**Step 6 — stop the server** with `Ctrl+C`. Conversation history lives in the browser session, so
reloading the page clears it; that is the quickest way to start a demo from a clean slate.

## Using the interactive CLI (`main.py`)

A question loop over the same pipeline, for a working session rather than a presentation.

```bash
python main.py                              # start the session
python main.py --verbose-provenance         # start with chunk ids and verbatim passages shown
python main.py -k 8                         # retrieve 8 passages per question instead of 5
```

The banner confirms the collection, passage count, embedding model and vector dimension. Then type a
question at the `>` prompt. In-session commands:

| Input | Effect |
|---|---|
| `help`, `?`, `\h` | list the commands |
| `verbose` | toggle chunk ids and verbatim passages under each footnote |
| `exit`, `quit`, `q`, `:q`, `\q` | end the session |
| anything else | treated as a question against the collection |

`Ctrl+C` cancels the question in flight, `Ctrl+D` ends the session — both cleanly, without a stack
trace. The index is loaded once for the whole session, so only the first question pays that cost.
On exit the session reports how many questions were asked.

## Asking a single question (`ask.py`)

For scripted use, evaluation runs and quick checks.

```bash
python ask.py "What does the thesis say about the role of transparency in corporate governance?"
python ask.py --verbose-provenance "<question>"   # chunk ids + verbatim passages under each footnote
python ask.py -k 8 "<question>"                   # retrieve 8 passages instead of the default 5
python ask.py --json "<question>"                 # raw run record instead of prose
```

The default output is the rendered answer with numbered footnotes resolving to chapter, section and
printed pages. `--verbose-provenance` adds the chunk id and the verbatim retrieved passage under
each footnote — use it when you need to check an answer against the source by eye.

`--json` emits the full run record: question, generation model, embedding model, prompt hash, corpus
text hash, every retrieved handle with its chunk id and score, the structured result and any
validation failures. That is the form to keep as evidence of a run.

**Exit codes:** `0` when the answer passed validation, `1` when it did not. A validation failure is
a recorded research result, never a silent retry — the failed checks are printed under a
`VALIDATION FAILED` banner, and the answer is not certified as source-grounded.

## Running it continuously (Docker)

For hosting the web UI permanently — on a Raspberry Pi or any other always-on machine:

```bash
cp .env.example .env && chmod 600 .env    # then fill in the two API keys
docker compose up -d --build
```

Full guide, including the 64-bit-OS requirement and how to reach the service safely:
[`docs/deployment/raspberry-pi.md`](docs/deployment/raspberry-pi.md).

Two things worth knowing before deploying:

- **It binds to `127.0.0.1` by default.** The app has no authentication and every question spends
  money on two APIs, so it is not published to the network until you change `BIND_ADDRESS`.
- **Credentials never enter the image.** They are read at run time from `.env` on the host, because
  anything set with `ENV` or `ARG` in a Dockerfile is readable via `docker history`.

The container needs neither the source PDF nor the ingestion dependencies: `index/` is committed, so
a deployed container queries it directly and never re-ingests.

## Evaluation

Sprint E1 (`docs/plans/PLAN_V3.md`) adds the harness that measures what the demo could only show
anecdotally: how often the system answers, cites the right page, and refuses when it should.

**Results: pending the first recorded run.** No number appears in this section until it has been
measured, recorded in `runs/`, and rated. The question set is still being written by the researcher.

### Method

1. **Question set** — `evaluation/questions_v1.yaml`, 30 slots with a target of 15 ANSWERABLE,
   5 PARTIAL, 7 UNANSWERABLE and 3 ADVERSARIAL. Every question and every gold label is written by
   the researcher from knowledge of the thesis. Nothing in the set is generated by a model: a
   model-written test set would be graded by the thing it tests. Gold labels are **printed page
   labels**, the same labels the citation renderer resolves from stored provenance. The file holds
   no thesis text.
2. **Gold check** — `python scripts/check_gold.py` validates the file against
   `data/canonical/pages.jsonl` and prints a pass/fail table of ids, categories and page labels. It
   never prints the question, the notes, or any thesis text. A blank slot is reported as "not
   written yet", not as an error, and every failure says what to do about it. A label that is not
   printed on exactly one page is rejected: the
   roman labels i–vii are printed twice (front matter and appendix), and printed 43 and 44 do not
   exist in the extraction because PDF pages 66 and 67 carry no printed number.
3. **Run** — `python evaluate.py` sends every written question through `ask.run_query()`, the same
   single pipeline the CLI and the web UI use. It refuses to start when no question is written or
   the gold check fails. Each question produces one record in `runs/eval_<timestamp>.jsonl` with
   the model string, embedding model, prompt hash and top-k read from configuration, the retrieved
   page labels with their rank, the cited page labels, and every validation failure.
4. **Failures are outcomes** — a provider error or malformed model output is written down as that
   question's result. It is never retried, and it stays in every denominator.
5. **Automatic metrics** — written to `runs/eval_<timestamp>.md`, each as a count `n/N` over a
   stated population: refusal correctness, false refusal (case B), retrieval recall@k, rank of the
   first gold page, citation hit, contract violations by type, and partial discipline. None of them
   is called accuracy, and no retrieval similarity score is reported as a result.
6. **Human rating** — `evaluation/rating_sheet_v1.csv` gets one row per answered question with
   three blank columns: `supported`, `faithful_qualification`, `attribution`. Whether an answer is
   correct is the rater's verdict, never the harness's. A sheet that already holds a rating is
   never overwritten.

```bash
pip install -r requirements.txt -r requirements-dev.txt
python scripts/check_gold.py     # validate the question file; no API call
pytest                           # offline suite; no API key, no network
python evaluate.py               # live run; spends API credit on both providers
python scripts/results_tables.py runs/eval_<timestamp>.jsonl   # Markdown + LaTeX tables from a recorded run
```

The offline suite replaces the generation model at `ask.call_model` and the embedding provider with
a deterministic stand-in; retrieval ranking, validation, citation resolution and rendering run as
real code. The CI workflow from PLAN_V3 §7 runs the same suite on every push once it is added
under `.github/workflows/`; until then the suite is run locally. The live run is never in CI.

### Repeated runs and the no-retrieval baseline (Sprint E2)

`docs/plans/PLAN_V5.md` adds the two things a single grounded run cannot give: a comparison, and a
sense of how much one run varies from the next. **No results yet**: both need the question set.

```bash
python evaluate.py --repeat 3            # three runs under one run group; each metric per run, with min and max
python evaluate.py --baseline no-rag     # the same questions with retrieval switched off
```

- **The baseline changes one thing.** It is the same model and the same prompt file, byte for
  byte, with an empty evidence block, sent through the same `ask.run_query`. Because that prompt
  tells the model to answer only from evidence, most baseline answers are expected to be refusals;
  that is what this design measures, and it is not what the model would say if simply asked.
- **Page numbers the model writes are checked** against the thesis's printed page labels. A number
  the thesis does not print is counted as a fabricated citation. A number it does print is not
  thereby correct; that remains a human rating.
- **A baseline answer is an evaluation record only.** Every record, summary and rating sheet is
  labelled `baseline_no_rag`, it is never rendered as a cited answer, and no interface can ask for it.
- **Repeats report the spread, not an average.** With a handful of runs a mean would mislead.

### Limits

- **One document.** Results will describe this thesis and this index, not RAG in general.
- **About 30 questions.** Each count is small; a difference of one or two questions is not a finding.
- **One rater, who is also the author** of the thesis and the builder of the system. This is a
  disclosed bias, not a controlled one.
- **One run is a sample.** Generation is nondeterministic. E1 reports a single run; repeat runs and
  the RAG / no-RAG baseline are planned for E2.
- **Page-level gold.** A gold page counts as retrieved or cited when it lies in a passage's stored
  page range. That shows the right page was reached, not that the right sentence was used.

## Presentations

| File | Venue |
|---|---|
| [`docs/presentations/ITCC-2026-Source-Grounded-Research-Assistant.pptx`](docs/presentations/ITCC-2026-Source-Grounded-Research-Assistant.pptx) | 28th International Turkish Cooperative Congress (ITCC-2026), 14 August 2026 — 20-minute online session |
| [`docs/presentations/ITCC-2026-speaker-notes.md`](docs/presentations/ITCC-2026-speaker-notes.md) | The same speaker notes, exported as a run sheet with timings |

Sixteen slides covering the problem, the grounding and refusal design, the three demonstration
questions, the evaluator view, and current status. Three things to know before reusing it:

- The title and closing slides carry `[ Affiliation ]` and `[ email ]` placeholders.
- The interface screenshots come from the Streamlit web UI (`app.py`). The deck was committed on
  12 August 2026, the day before the corpus was changed (see the Task Log), so the screenshots
  show the earlier demonstration thesis, not the current one.
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
| 2026-08-12 | — (Demo slice) | Add `app.py`, a Streamlit web chat UI for the conference demo — the third shell over `ask.run_query()`, adding no retrieval, generation, citation or validation logic of its own. Index loaded once per process (`st.cache_resource`); conversation history in `st.session_state` only. Renders a sufficient answer as prose with a `Sources:` line and collapsible full citations, a refusal as a plain non-alarming notice, `[AI INTERPRETATION]` as a distinct labelled callout, and retrieval scores collapsed into "Technical details (for evaluators)" captioned as diagnostics rather than confidence. Provider/auth/network errors and validation failures are reported in plain language, never as a traceback. Verified: the real index loads and the provider-failure path renders correctly; the three demo questions were exercised through the real provenance, citation and validation code with the model call stubbed — **the live end-to-end run against the API is still outstanding and must be done before the demo**. | Implemented; pushed to `claude/streamlit-web-ui-eyheeg` (`3d5b62f`) — awaiting review | `app.py`, `README.md` |
| 2026-08-13 | — (Corpus swap) | Replace the Sönmez corpus with Karimov (2017), *The Qur’anic Concept of Justice (al-ʿAdl) from a Nursian Perspective* (Durham, 288 pp). Lifted the layout constants measured from one PDF out of `ingest.py` into a layout profile in `config.py`, added `chapter_source` (running header or chapter heading) and chapter runs built from page slices so hard rule 8 holds by construction, and excluded reference apparatus from evidence via `excluded_chapter_prefixes`. Fixed three latent extraction defects found by calibrating against a second document: the caption filter swallowed `"Table of contents"`, heading-merge fused a chapter title with the section beneath it, and pages with text but no body text were indistinguishable from blank pages. Swapping to the new thesis was then configuration only — no pipeline code changed. 288 pages → 266 chunks. Provenance audited against the PDF itself: 266/266 chunks carry the page label actually printed on their pages, and every word of every chunk appears on the pages it claims. All three entry points re-verified live against the API, including the refusal path. A second calibrated corpus (Leung 2019) is kept on `feature/swap-corpus-leung` as a fallback. | Implemented and approved; on `feature/swap-corpus-karimov` (`5468662`) — deliberately **not** merged, under test on the branch | `config.py`, `ingest.py`, `README.md`, `docs/decisions/0001-corpus-swap-via-layout-profile.md`, `data/`, `index/` |
| 2026-08-12 | — (Deployment) | Containerise the web UI for continuous self-hosting on a Raspberry Pi: `python:3.11-slim` image running as an unprivileged user, runtime dependencies pinned in `requirements.txt` (ingestion dependencies deliberately excluded — the committed index means a deployed container never re-ingests), Streamlit health endpoint wired to a Docker `HEALTHCHECK`, `restart: unless-stopped`, and capped json-file logging so an SD card cannot fill. Credentials are read at run time from a host `.env` and never enter an image layer; `data/` is excluded from the build context so the source PDF is not baked in. Published to loopback by default, since the app has no authentication and every question spends API credit. **Not build-tested — no Docker daemon was available in the authoring environment; verification is `docker compose up -d --build` on the target Pi.** | Implemented; pushed to `claude/docker-deploy` — awaiting review | `Dockerfile`, `compose.yaml`, `.dockerignore`, `.env.example`, `requirements.txt`, `docs/deployment/raspberry-pi.md`, `README.md` |
| 2026-08-14 | — (Corpus swap) | Index the bibliography as tagged apparatus instead of excluding it, reversing decision 4 of ADR 0001. That exclusion rested on an unmeasured claim — that a reference list would displace substantive evidence — and measurement disproved it: bibliography chunks took 0 of 50 evidence slots across 10 substantive questions, because dense embeddings encode a reference list as *"a list of references"* rather than as its subject matter, while on questions about the thesis's sources they ranked #1–#2. `apparatus_chapter_prefixes` replaces `excluded_chapter_prefixes`; every chunk now carries `kind` `source` or `apparatus`, and the tag is carried to both audiences — to the model in the evidence block header, and to the reader in the citation and the web UI `Sources:` line. `prompts/system_grounded_v2.md` adds a *Reference apparatus* section (apparatus supports only what the thesis cites; a title is never evidence of its contents; apparatus alone never establishes the author's position); `v1` is untouched so earlier runs stay reproducible. Index grows 266 → 294 chunks (28 apparatus, ~18,500 tokens). Title-as-content fabrication verified as guarded: asked what the thesis concludes about Hizb ut-Tahrir — present only as a bibliography title — the system refuses and reasons that the apparatus passage "could only establish what the thesis cites, not its conclusions". **Caveat: the measurement is dense-retrieval only.** Under the hybrid dense + BM25 retrieval specified in `PLAN_V2` §8–10 a bibliography chunk is a keyword magnet, so the 0% displacement result must be re-measured when hybrid lands. | Implemented and approved; on `feature/swap-corpus-karimov` (`3c6dbc9`) — open as PR #2 | `config.py`, `ingest.py`, `ask.py`, `app.py`, `prompts/system_grounded_v2.md`, `README.md`, `docs/decisions/0002-bibliography-as-tagged-apparatus.md`, `index/` |
| 2026-11-14 | E1 (Evaluation harness) | Build the evaluation harness from `docs/plans/PLAN_V3.md` §3–§7. `scripts/check_gold.py` validates the gold question file against the printed page labels in `data/canonical/pages.jsonl`: a gold page must be a quoted label printed on exactly one page, so the roman labels i–vii (printed in both the front matter and the appendix) and printed 43/44 (PDF pages 66–67 carry no number) are rejected; every failure says what to do, a blank slot is "not written yet", and the table never prints question or thesis text. `evaluate.py` sends each written question through `ask.run_query()` — no second pipeline — and writes `runs/eval_<timestamp>.jsonl`, a Markdown summary and `evaluation/rating_sheet_v1.csv`; it refuses to start with no written question, a failed gold check or a rating sheet that already holds ratings, records provider errors and malformed output as outcomes that stay in every denominator, never retries, and records the model, embedding model, prompt hash and top-k from configuration. `evaluation/metrics.py` reports the PLAN_V3 §5 metrics as `n/N`, with "retrieval not measured" as its own count; nothing is called accuracy and no similarity score is reported. Offline suite of 127 tests (126 passing, 1 strict `xfail` documenting that `ask.PAGE_CLAIM_RE` misses the word "page"), with the generation model replaced only at `ask.call_model` and the embedding provider by a deterministic stand-in; each test was shown red under at least one of 120 deliberate breaks. `ask.py` unchanged. **Not yet done: the 30 questions are unwritten (researcher only), no live run has been made, so there are no results; the CI workflow (`.github/workflows/ci.yml`) is still to be added by a maintainer.** | Implemented and approved; merged to `main` in PR #6 (`6dcef35`) | `evaluate.py`, `evaluation/`, `scripts/check_gold.py`, `tests/`, `config.py`, `requirements-dev.txt`, `pytest.ini`, `.dockerignore`, `.gitignore`, `README.md` |
| 2026-08-12 | — (Dissemination) | Prepare the 20-minute ITCC-2026 conference deck: 16 slides in English covering the hallucination and audit-trail problem, relevance to cooperative governance, the grounding pipeline, the opaque-handle mechanism that makes a fabricated page reference structurally impossible, the three outcome types, the three demonstration questions as UI screenshots, the evaluator view, and current status including what is not yet done. Speaker notes with per-slide timings on every slide, plus anticipated questions; notes also exported as a standalone run sheet. Screenshots captured from the web UI with the model call stubbed — provenance, citations and retrieval diagnostics in them are read from the real index. | Committed to `claude/itcc-2026-deck` | `docs/presentations/ITCC-2026-Source-Grounded-Research-Assistant.pptx`, `docs/presentations/ITCC-2026-speaker-notes.md`, `README.md` |
| 2026-11-15 | — (Citation fix) | Correct the citation wording for a passage that runs onto a page with no printed number. `ask.page_phrase` named the passage's first PDF page as unprinted even when that page carried a number; it now names the pages recorded in the passage's own `pages_unresolved` and keeps the one label it has (`p. 42 and PDF p. 67, which has no printed number [VERIFY]`). No label is computed (hard rule 2). The evaluation record follows the renderer, so a partly numbered citation now carries its label. 11 tests written first and failing on the old code. | Implemented and approved; merged to `main` in PR #10 | `ask.py`, `evaluate.py`, `tests/test_citations.py` |
| 2026-11-15 | E2 (Repeats and baseline) | Implement `docs/plans/PLAN_V5.md`. `evaluate.py --baseline no-rag` asks the same questions with retrieval switched off: the identical prompt and model with an empty evidence block, through the same `ask.run_query` (`retrieve_evidence=False`), so the two conditions differ in one variable. Baseline records, summaries and rating sheets are labelled `baseline_no_rag`; a baseline outcome refuses to be rendered as a cited answer and no interface exposes the switch. Page numbers the model writes are checked against the printed labels; one the thesis does not print is counted as a fabricated citation. `--repeat N` runs the set N times under one run group and reports each metric per run with its minimum and maximum, with no average. `scripts/results_tables.py` writes Markdown and LaTeX tables from recorded runs, as `n/N`, labelling baseline runs and showing `n/a` where a metric does not apply. All tests offline and written first. **No results yet: the question set is still unwritten and no live run has been made.** | Implemented and approved; merged to `main` in PRs #11, #13 and #14 | `ask.py`, `evaluate.py`, `evaluation/metrics.py`, `scripts/results_tables.py`, `tests/`, `docs/plans/PLAN_V5.md`, `README.md` |

## Companion: Work Brain template

[`work-brain/`](work-brain/) is a separate, self-contained template that applies the same
grounding ideas to personal working notes: an Andrej Karpathy-style LLM knowledge base for
Claude Code. Notes in `raw/` are compiled into a linked `wiki/` (read in Obsidian). A
pre-compile guard blocks credentials and financial identifiers, and `/query` refuses when the
wiki does not cover a question. It is stdlib-only Python and does not depend on the RAG code.
See [`work-brain/README.md`](work-brain/README.md).
