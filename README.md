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

## Running it continuously (Docker)

For hosting the web UI permanently — on a Raspberry Pi or any other always-on machine:

```bash
cp .env.example .env && chmod 600 .env    # then fill in the two API keys
docker compose up -d --build
```

Full guide, including the 64-bit-OS requirement and how to reach the service safely:
[`docs/deployment/raspberry-pi.md`](docs/deployment/raspberry-pi.md).

Three things worth knowing before deploying:

- **The image serves `app.py`**, which is on branch `claude/streamlit-web-ui-eyheeg` and not yet on
  `main`. Merge that branch first, or build from a checkout containing it.
- **It binds to `127.0.0.1` by default.** The app has no authentication and every question spends
  money on two APIs, so it is not published to the network until you change `BIND_ADDRESS`.
- **Credentials never enter the image.** They are read at run time from `.env` on the host, because
  anything set with `ENV` or `ARG` in a Dockerfile is readable via `docker history`.

The container needs neither the source PDF nor the ingestion dependencies: `index/` is committed, so
a deployed container queries it directly and never re-ingests.

## Task Log

Chronological record of completed and approved work. Rows are appended after each sprint is
implemented and approved — existing rows are never removed or reordered.

| Date | Sprint | Task | Status | Files Touched |
|---|---|---|---|---|
| 2026-08-11 | — (Planning) | Produce architecture and Agile implementation plan for the source-grounded RAG prototype | Planning complete — awaiting human approval | `docs/plans/PLAN_V2.md`, `README.md`, `CLAUDE.md` |
| 2026-08-11 | — (Demo slice) | Build the minimum end-to-end vertical slice: PyMuPDF extraction with printed-page and running-header provenance, chapter/section-bounded chunking (~700 tokens, 15% overlap), `text-embedding-3-large` embeddings, brute-force cosine retrieval (k=5), grounded generation with opaque `[En]` handles resolved to page-numbered footnotes by the renderer, refusal path, and blocking post-generation validation. 320 pages → 249 chunks. | Implemented and committed to `main` (`9577d6e`) | `config.py`, `embeddings.py`, `ingest.py`, `ask.py`, `prompts/system_grounded_v1.md`, `index/`, `data/canonical/` |
| 2026-08-12 | — (Demo slice) | Add `main.py` interactive CLI wrapper. Refactored `ask.py`'s core into a shared `run_query()` returning a `QueryOutcome`, so the single-question and interactive entry points call one pipeline; cached the Anthropic client and system prompt, and load the index once per session. Clean exit on `exit`/`quit`/`q`, Ctrl+C and Ctrl+D. All three demo questions re-run through both entry points: retrieval diagnostics and sufficiency labels byte-identical, generated prose varies (model nondeterminism). | Implemented; committed to `main` (`91ad972`) | `main.py`, `ask.py`, `README.md` |
| 2026-08-12 | — (Deployment) | Containerise the web UI for continuous self-hosting on a Raspberry Pi: `python:3.11-slim` image running as an unprivileged user, runtime dependencies pinned in `requirements.txt` (ingestion dependencies deliberately excluded — the committed index means a deployed container never re-ingests), Streamlit health endpoint wired to a Docker `HEALTHCHECK`, `restart: unless-stopped`, and capped json-file logging so an SD card cannot fill. Credentials are read at run time from a host `.env` and never enter an image layer; `data/` is excluded from the build context so the source PDF is not baked in. Published to loopback by default, since the app has no authentication and every question spends API credit. **Not build-tested — no Docker daemon was available in the authoring environment; verification is `docker compose up -d --build` on the target Pi.** | Implemented; pushed to `claude/docker-deploy` — awaiting review | `Dockerfile`, `compose.yaml`, `.dockerignore`, `.env.example`, `requirements.txt`, `docs/deployment/raspberry-pi.md`, `README.md` |
