# PLAN_V2 — Source-Grounded RAG for Scholarly Research and Literature Reviews

**Status:** Planning complete — awaiting human approval
**Date:** 2026-08-11
**Document type:** Authoritative architecture and Agile implementation plan for this phase
**Scope note:** This document is a plan. No application source code exists yet. No sprint has been implemented.

---

## 1. Executive Summary

### 1.1 What is being built

A **scholarly research assistant** that answers questions about an authorised research collection using only evidence retrieved from that collection, and that refuses to answer when the collection does not contain sufficient evidence.

The initial corpus is two documents (one doctoral thesis by Melih Sönmez; one selected academic article), English only. The corpus is deliberately small because the near-term deliverable is a conference demonstration. The *architecture*, however, is corpus-agnostic: replacing the PDFs and re-running ingestion must be sufficient to point the system at a different scholar, discipline, or document type.

### 1.2 The research question the software must serve

Does source-grounded retrieval measurably reduce unsupported claims and improve traceability, compared to the same generation model answering from parametric knowledge alone?

This means the software is not only a product; it is **experimental apparatus**. Two consequences run through every design decision below:

- Every run must be reproducible and fully logged, because runs are evidence.
- The RAG and no-RAG conditions must differ in exactly one variable (presence of retrieved evidence), because otherwise the comparison proves nothing.

### 1.3 Core principle

> **The AI analyses. The researcher decides.**

The system retrieves evidence, generates a source-grounded answer, preserves attribution and qualification, surfaces disagreement rather than resolving it, labels its own interpretation as interpretation, cites traceably, and refuses when evidence is insufficient. Final scholarly judgement is never delegated to the model.

### 1.4 Headline recommendations

| Decision | Recommendation | Rationale (short) |
|---|---|---|
| Language / runtime | Python 3.11+ | Ecosystem for PDF, embeddings, evaluation; matches prior team experience |
| Interface (MVP) | CLI (Typer) | Reproducible, scriptable, diffable outputs; a UI is not required to answer the research question |
| PDF extraction | PyMuPDF (`pymupdf4llm`) as primary, MarkItDown evaluated as comparator | **Page fidelity is the deciding criterion.** See §4 |
| Document model | Explicit `Document → Chapter → Section → Chunk` hierarchy persisted as JSON | Provenance must be structural, not inferred at query time |
| Chunking | Structure-aware, section-bounded, ~700–900 tokens, ~15% overlap, never crosses a chapter boundary | Preserves argumentative unit; keeps citations honest |
| Embedding model (MVP) | `text-embedding-3-large` via `EMBEDDING_PROVIDER=openai` | Strong on academic English, 3072-dim, negligible cost at this corpus size, trivial deployment. Local `BAAI/bge-m3` documented as the offline/reproducibility alternative |
| Vector store (MVP) | **Exact brute-force cosine over a persisted NumPy matrix + SQLite metadata** | ~1.5k chunks. Exact search removes ANN recall variance as a confound. No infrastructure without a requirement |
| Retrieval (MVP) | Hybrid: dense cosine + BM25, fused with Reciprocal Rank Fusion, optional metadata pre-filter, k≈10 | Scholarly text is dense in proper nouns and terms of art where lexical match matters |
| Reranking | **Deferred** — not in MVP | See §10 for the justification and the trigger condition that would introduce it |
| Generation model (MVP) | `claude-opus-5` via `LLM_PROVIDER=anthropic` | Selected for refusal calibration, handling conflicting evidence, and structured output — not for novelty. See §9 |
| Amazon Bedrock | **Not used** | Explicitly out of scope per project constraints |
| Refusal | Multi-signal: model-declared evidence sufficiency (primary) + retrieval diagnostics (advisory) | A similarity threshold alone cannot distinguish absence from retrieval failure. See §14 |

### 1.5 What is explicitly *not* in the MVP

Web UI; multi-language; OCR for scanned documents; cross-encoder reranking; agentic multi-hop retrieval; knowledge graphs; fine-tuning; multi-model ensembles; Bedrock; Kubernetes; a hosted service.

---

## 2. Target Architecture

### 2.1 Pipeline

```
                    ┌──────────────────── INGESTION (offline, batch) ────────────────────┐

  data/raw/*.pdf
        │
        ▼
   ┌─────────┐   ┌──────────────┐   ┌──────────────┐   ┌───────────┐   ┌──────────┐
   │ Scanner │──▶│  Extractor   │──▶│  Structurer  │──▶│  Chunker  │──▶│ Embedder │
   │ (files, │   │ PDF → text + │   │ chapters,    │   │ section-  │   │ Embedding│
   │  hashes)│   │ page spans   │   │ sections,    │   │ bounded   │   │ Provider │
   └─────────┘   │ (canonical)  │   │ metadata     │   │ +overlap  │   └────┬─────┘
                 └──────┬───────┘   └──────────────┘   └───────────┘        │
                        │                                                    ▼
                        │                                            ┌───────────────┐
                        ▼                                            │  Index Store  │
              data/canonical/<doc_id>/                               │ vectors.npy   │
                 pages.jsonl  (immutable source of truth)            │ chunks.sqlite │
                 document.json (structure + metadata)                │ manifest.json │
                                                                     └───────┬───────┘
                                                                             │
                    ┌──────────────────── QUERY (online) ─────────────────────┼──────┐
                                                                             │
   question ──▶ ┌────────────┐   ┌───────────────┐   ┌──────────────┐        │
                │  Retriever │◀──┤ Index Store   │◀──┘                       │
                │ dense+BM25 │   └───────────────┘                            
                │  + RRF     │
                └─────┬──────┘
                      ▼
                ┌──────────────┐   ┌────────────────┐   ┌──────────────┐   ┌──────────────┐
                │ Evidence Set │──▶│  RAG Service   │──▶│ LLM Provider │──▶│  Answer      │
                │ (+provenance)│   │ prompt assembly│   │ (anthropic)  │   │  Envelope    │
                └──────────────┘   │ + schema       │   └──────────────┘   │ (structured) │
                                   └────────────────┘                      └──────┬───────┘
                                                                                   ▼
                                                                          ┌────────────────┐
                                                                          │ Citation       │
                                                                          │ Renderer +     │
                                                                          │ Run Recorder   │
                                                                          └────────────────┘
```

### 2.2 Layering rules

1. **Providers are leaves.** `EmbeddingProvider` and `LLMProvider` are abstract interfaces; concrete implementations know about vendors, and nothing else in the codebase does.
2. **No vendor name appears in application logic.** Not in the retriever, not in the RAG service, not in the CLI. Only in `providers/` and in `.env`.
3. **The canonical extraction is immutable.** Once `pages.jsonl` is written it is never rewritten by a downstream stage. Summaries, chapter abstracts, and generated metadata live in separate files and are always marked as derived.
4. **Provenance flows forward, never backward.** A chunk carries its origin; an answer carries its chunks. Nothing is reconstructed by guessing at answer time.
5. **The generation step cannot reach the index.** It receives an `EvidenceSet` object. This makes the no-RAG baseline (§20) a matter of passing an empty evidence set through the same code path, not of writing a second pipeline.

### 2.3 Interface (MVP) and interface (later)

- **MVP:** a CLI (`Typer`) with subcommands for ingest, index, query, evaluate, and baseline. Output is JSON plus a human-readable rendering.
- **Later (optional, Sprint 8):** a thin FastAPI wrapper over the same service layer, containerised with Docker. The service layer must be written so this is additive — no logic in the CLI beyond argument parsing and presentation.

---

## 3. Component Responsibilities

| Component | Responsibility | Must not |
|---|---|---|
| `Scanner` | Discover PDFs under `data/raw/`, compute SHA-256, emit a stable `document_id` | Parse content |
| `Extractor` | PDF → per-page text with page numbers; produce canonical `pages.jsonl` | Reformat, summarise, or drop content |
| `Structurer` | Detect chapters/sections; attach metadata; produce `document.json` | Invent structure where none is detectable — must mark low confidence |
| `MetadataResolver` | Populate document-level bibliographic fields; flag human-verification-required fields | Guess author/year silently |
| `Chunker` | Split section text into retrieval units with full provenance | Create a chunk spanning two chapters |
| `EmbeddingProvider` | text[] → vector[]; expose `model_id`, `dimensions`, `normalise()` | Cache silently across model changes |
| `IndexStore` | Persist vectors + chunk metadata + build manifest; exact similarity search; metadata filtering | Perform approximate search in MVP |
| `Retriever` | Query → ranked `EvidenceSet` with scores from each retrieval channel | Interpret scores as confidence |
| `RAGService` | Assemble prompt, call `LLMProvider`, validate structured response, attach provenance | Contain vendor-specific code |
| `LLMProvider` | messages + schema → structured response + usage metadata | Retry in a way that hides failures from the run log |
| `CitationRenderer` | Internal provenance → academically readable footnotes | Emit a page number not present in provenance |
| `RunRecorder` | Write a complete, replayable record of every run | Omit failed or refused runs |
| `Evaluator` | Execute question sets, collect outputs, compute automatic metrics, emit human-review sheets | Report a heuristic as a verdict |

---

## 4. PDF-to-Markdown Ingestion

### 4.1 The deciding requirement

Section 5 of the brief requires provenance down to `page`, and forbids inventing page numbers. **This single requirement disqualifies most "PDF → Markdown" converters as the primary extractor**, because they produce a continuous Markdown stream in which page boundaries are discarded. Once page boundaries are gone, any page number in a citation is reconstructed — that is, invented.

Therefore the pipeline is not "PDF → Markdown". It is:

```
PDF ──▶ per-page text blocks (page number attached at extraction time)   ← canonical, immutable
     └▶ structural markup (headings, lists, emphasis)                     ← derived, for readability
```

### 4.2 Evaluation of candidate extractors

| Tool | Page fidelity | Structure quality | Deps | Licence | Verdict |
|---|---|---|---|---|---|
| **PyMuPDF / `pymupdf4llm`** | **Native** — extraction is page-by-page; `pymupdf4llm` can emit page-chunked Markdown | Good headings/lists via font-size heuristics; tables adequate | Single wheel, no service | AGPL-3.0 (commercial licence available) | **Recommended primary** |
| Microsoft MarkItDown | **Weak** — produces one Markdown stream; page boundaries not preserved in output | Reasonable, uniform across many input formats | Light | MIT | **Recommended as comparator, not as primary.** Excellent if the corpus later includes `.docx`, `.pptx`, `.xlsx`, HTML |
| Docling (IBM) | Good — retains page provenance in its document model | Strongest layout/table/reading-order handling | Heavy (ML models, ~GB) | MIT | **Deferred.** Right answer if thesis layout defeats PyMuPDF; too heavy to adopt speculatively |
| `pdfplumber` | Native | Weak on headings; strong on tables/coordinates | Moderate | MIT | Useful fallback for table-heavy pages |
| OCR (Tesseract / Surya) | N/A | N/A | Heavy | — | **Out of scope.** Corpus assumed to be born-digital with a text layer |

**Assessment of MarkItDown specifically (as requested):** MarkItDown is a good, well-maintained, permissively-licensed general-purpose converter, and its breadth across formats is genuinely valuable for the "future researcher swaps the corpus" requirement. It is *not* suitable as the primary extractor for this project because it optimises for a clean linear Markdown document, and cleanliness here costs exactly the thing the research needs: page-level traceability. The plan therefore keeps a `MarkItDownExtractor` behind the same `Extractor` interface, used (a) for non-PDF inputs later, and (b) as a Sprint 2 comparison artifact showing why page-aware extraction was chosen. This is a documented finding for the paper, not merely an implementation detail.

### 4.3 Ingestion stages

1. **Scan** — hash file, assign `document_id`, record file metadata.
2. **Extract** — per page: raw text, character count, layout confidence. Write `pages.jsonl`, one JSON object per page. **Never rewritten.**
3. **Structure** — detect chapter and section headings using (a) the PDF outline/bookmark tree when present (most theses have one — highest confidence), else (b) font-size/weight and numbering-pattern heuristics, else (c) `structure_confidence: "low"` and a flag for human review.
4. **Metadata** — extract title/author/year from PDF metadata and first pages; **any field not confidently resolved is left null and reported**, never guessed.
5. **Emit** — `document.json` (structure + metadata + page index), validated against a JSON schema.
6. **Human checkpoint** — the researcher reviews the detected chapter/section tree once per document. This is cheap for a 2-document corpus and eliminates a whole class of downstream provenance errors. It is a **first-class step**, not an afterthought.

### 4.4 Failure handling

A page with no extractable text is recorded with `text: ""` and `extraction_warning: "no_text_layer"`. It is not silently skipped, because a missing page silently dropped would make later page ranges wrong.

---

## 5. Scholarly Document Model

Four levels, each with a stable identifier.

```
DOCUMENT   document_id, source_path, sha256, author[], year, title, publication,
           source_type (thesis|article|book|policy|other), language, page_count,
           metadata_confidence, ingested_at, extractor{name, version}

  CHAPTER  chapter_id, chapter_number, chapter_title, page_start, page_end,
           chapter_summary*, major_findings[]*, structure_confidence

    SECTION  section_id, section_heading, hierarchy_path[], level,
             page_start, page_end

      CHUNK  chunk_id, document_id, chapter_id, section_id,
             page_start, page_end, char_start, char_end,
             text (verbatim source passage), token_count,
             concepts[]*, embedding_ref, chunk_index, prev_chunk_id, next_chunk_id
```

`*` = **derived, non-authoritative**. Every derived field carries `"derived": true` and the identity of the model that produced it.

### 5.1 The authority rule

> Chapter summaries, major findings, and extracted concepts may be used **to improve retrieval and to orient the reader**. They may **never** be quoted, cited, or presented as the author's position. Only `chunk.text` — the verbatim source passage — is admissible evidence.

This is enforced in three places, not one:
1. The prompt states it explicitly.
2. Derived text is passed to the model in a visibly distinct, labelled block, or (default in MVP) **not passed to the generation step at all** — summaries are used at the retrieval stage only.
3. The citation renderer will only mint a citation from a `chunk_id`, and a summary has no `chunk_id`.

### 5.2 Storage layout

```
data/canonical/<document_id>/
    source.pdf.sha256
    pages.jsonl          # immutable canonical extraction
    document.json        # structure + metadata
    derived.json         # summaries, findings, concepts — clearly separated
    extraction_report.md # warnings, low-confidence flags, human-review notes
```

---

## 6. Metadata Model

### 6.1 Fields and their provenance class

| Level | Field | Class | Notes |
|---|---|---|---|
| Document | `document_id` | system | `<slug>-<sha256[:8]>` — stable across re-ingestion of the same file |
| Document | `author[]`, `year`, `title`, `publication` | **human-verified** | Auto-extracted, then confirmed at the Sprint 2 checkpoint |
| Document | `source_type`, `language` | human-set | Declared in `corpus.yaml` |
| Document | `sha256`, `page_count`, `ingested_at`, `extractor` | system | Reproducibility anchors |
| Chapter | `chapter_number`, `chapter_title`, `page_start/end` | extracted | With `structure_confidence` |
| Chapter | `chapter_summary`, `major_findings[]` | **derived** | Generated; never citable |
| Section | `section_heading`, `hierarchy_path[]`, `level` | extracted | |
| Chunk | page/char spans, `text` | extracted | Verbatim |
| Chunk | `concepts[]` | derived | Retrieval aid only |

### 6.2 Corpus manifest

A single human-authored `corpus.yaml` declares the authorised collection. Nothing outside it is ever indexed. This is what makes "the authorised research collection" a concrete, auditable object rather than a figure of speech:

```yaml
corpus_id: sonmez-demo-v1
language: en
documents:
  - file: data/raw/sonmez_thesis.pdf
    source_type: thesis
    author: ["Sönmez, Melih"]
    year: <to confirm at ingestion>
    title: "<to confirm at ingestion>"
  - file: data/raw/article_01.pdf
    source_type: article
    author: ["<to confirm>"]
    year: <to confirm>
    title: "<to confirm>"
```

---

## 7. Chunking Strategy

### 7.1 Rules

1. **Section-bounded.** A chunk never spans a section heading; never, under any circumstance, spans a chapter boundary. A chunk that mixes two chapters produces a citation that is false at one end.
2. **Target 700–900 tokens**, hard maximum 1,100. Rationale: scholarly argument needs enough room for claim + qualification + hedge in one unit. Chunks that are too small systematically strip qualifications — which is precisely the failure mode this research is investigating.
3. **Overlap ~15%** (≈120 tokens), aligned to sentence boundaries. Overlap is duplicated text and is deduplicated at evidence-assembly time by `chunk_id`.
4. **Split preference order:** paragraph break → sentence break → clause. Never mid-sentence.
5. **Short sections** (< 250 tokens) are kept whole rather than merged with a neighbour, preserving one-section-one-idea.
6. **Provenance computed at split time,** from character offsets back into `pages.jsonl`. Page range is derived arithmetically, never estimated. A chunk crossing a page boundary carries `page_start` and `page_end`.
7. **Contextual header prepended for embedding only.** The embedded text is `"{document short-title} — {chapter} — {section}\n\n{text}"`. The *stored* and *cited* text is the bare passage. This lifts retrieval quality for short, pronoun-heavy passages without contaminating the quotable evidence.

### 7.2 Deliberately rejected for MVP

- **Semantic/embedding-based chunking** — non-deterministic across embedding-model changes, undermining reproducibility.
- **Fixed-size character chunking** — ignores structure, breaks provenance guarantees.
- **Sentence-window / parent-document retrieval** — attractive, and listed in §29 as a future enhancement; adds an indirection layer that is not needed to answer the research question.

### 7.3 Expected scale

A ~250-page thesis plus one article ≈ 130k–180k tokens ≈ **1,200–1,800 chunks**. This number is what justifies §8 and §9's "no infrastructure" stance throughout.

---

## 8. Embedding Strategy

### 8.1 Constraint from the provider landscape

Anthropic does not offer an embeddings endpoint. `LLM_PROVIDER=anthropic` therefore **necessarily** implies a different `EMBEDDING_PROVIDER`. This is not an awkwardness to be worked around — it is the concrete reason the two-role separation in §7 of the brief is correct, and it should be stated plainly in the paper.

### 8.2 Candidate evaluation

| Model | Dim | Academic English | Cost | Offline | Reproducible | Deploy | Notes |
|---|---|---|---|---|---|---|---|
| **OpenAI `text-embedding-3-large`** | 3072 (truncatable) | Strong | ~$0.13/M tok → **< $0.05 for this whole corpus** | No | Version-pinned by name; snapshot-frozen vectors mitigate drift | One API key | **Recommended MVP** |
| OpenAI `text-embedding-3-small` | 1536 | Good | ~$0.02/M | No | Same | One API key | Cheaper, slightly weaker on nuance |
| `BAAI/bge-m3` (local) | 1024 | Strong; multilingual; long-context | Free after download | **Yes** | **Fully** — weights are frozen artifacts | ~2.2 GB + PyTorch | **Recommended offline alternative**; also the natural Sprint 3 swap-test |
| `intfloat/multilingual-e5-large` | 1024 | Good | Free | Yes | Fully | ~1.1 GB | Lighter local option |
| Voyage `voyage-3` family | 1024 | Very strong on retrieval benchmarks | Low | No | Vendor-pinned | One API key | Strong contender; adds a third vendor relationship |
| Amazon Titan Text Embeddings v2 | 1024 | Good | Low | No | Vendor-pinned | AWS account/IAM | **Rejected for MVP** — pulls AWS into a project that explicitly excludes Bedrock |

### 8.3 Recommendation and its honest trade-off

**MVP default: `EMBEDDING_PROVIDER=openai`, `EMBEDDING_MODEL=text-embedding-3-large`.**

Reasons: strongest general retrieval quality per unit of setup effort on academic English; 3072 dimensions give headroom for nuanced distinctions between adjacent scholarly claims; cost is effectively zero at this corpus size; deployment is a single environment variable.

The trade-off, stated plainly: it requires network access and a second vendor key, and a hosted model could in principle change beneath a fixed model name. Two mitigations, both cheap:

1. **Freeze the vectors.** The built index (`vectors.npy` + `manifest.json` recording model, dimension, normalisation, and a hash of all embedded text) is a committed research artifact. Re-running an experiment uses the frozen index; it does not re-embed.
2. **Prove the abstraction.** Sprint 3 includes a swap-test that rebuilds the index with local `bge-m3` and compares retrieval on the same question set. This validates `EmbeddingProvider` *and* yields a genuine finding about embedding-model sensitivity.

If the researcher prefers full offline reproducibility over peak quality — a legitimate choice for a conference demo on unreliable venue wifi — flipping two environment variables to `bge-m3` is the entire change. That is the point of the abstraction.

### 8.4 Operational rules

- Normalise vectors to unit length at write time; similarity is then a dot product.
- The embedding cache key includes `EMBEDDING_MODEL`. Changing the model invalidates the cache; it must never silently reuse vectors from another model.
- Batch at 64 texts/request with exponential-backoff retry.
- An index built with model A can never be queried with model B. `manifest.json` records the model and the loader **refuses to start** on mismatch. Silent dimension coercion is the kind of bug that quietly invalidates a paper.

---

## 9. Retrieval Strategy

### 9.1 Options considered

| Strategy | Verdict for MVP |
|---|---|
| Flat dense vector search | Necessary, not sufficient — misses exact terminology and proper nouns |
| **Metadata-filtered retrieval** | **Include.** Cheap and directly useful ("what does Chapter 4 say…", "in the article only…") |
| **Hybrid dense + lexical (BM25)** | **Include.** Scholarly text is dense in terms of art, author names, and coined terms where lexical match is decisive. ~40 lines with `rank_bm25` |
| Hierarchical (chapter → chunk) | **Defer.** Real value at 50+ documents; at 2 documents it adds a failure mode without adding recall |
| Multi-query / HyDE expansion | **Defer.** Non-deterministic; adds an LLM call inside retrieval, complicating the RAG/no-RAG comparison |
| Agentic / iterative retrieval | **Out of scope** for MVP |

### 9.2 MVP retrieval pipeline

```
question
  ├─▶ optional metadata pre-filter (document / chapter / year)
  ├─▶ dense: embed question → exact cosine over the filtered candidate set → top 20
  ├─▶ lexical: BM25 over the same candidate set → top 20
  ├─▶ fuse: Reciprocal Rank Fusion, RRF(d) = Σ 1/(60 + rank_i(d))
  ├─▶ deduplicate overlapping chunks by chunk_id
  ├─▶ optional neighbour expansion (±1 chunk within the same section)
  └─▶ top k = 10 → EvidenceSet
```

`k = 10` is a starting value, tuned in Sprint 6 against the evaluation set and recorded per run.

### 9.3 Multiple passages, deliberately

The brief requires that retrieval return enough material for the model to distinguish supporting evidence, qualifications, related evidence, and conflicting evidence. A single top-1 chunk cannot express disagreement — there is nothing for it to disagree with. `k = 10` with neighbour expansion is chosen so that a genuine tension in the corpus has a real chance of appearing *inside one evidence set*, which is a precondition for §16 working at all.

### 9.4 Similarity is not confidence — enforced, not merely asserted

Scores are carried through as **diagnostics**, in a field named `retrieval_diagnostics`, and:

- they are **never** shown to the user as a confidence percentage;
- they are **never** the sole basis for a refusal (§14);
- they **are** logged for every run, because their relationship to human-judged evidence sufficiency is itself a research output.

A nearest neighbour always exists. Cosine 0.34 against an empty corpus and cosine 0.34 against a rich one mean different things. The number is a property of the vector space, not of the world.

---

## 10. Reranking Strategy

**Recommendation: no reranker in the MVP.**

Justification: reranking pays off when a first-stage retriever returns many plausible-but-wrong candidates from a large corpus. With ~1,500 chunks from two documents and hybrid retrieval, the top-10 recall ceiling is expected to be high enough that a reranker mostly reorders already-correct results. Adding one now would mean a second model (a third vendor dependency or a local cross-encoder), an extra latency step, an extra variable in every experiment, and an extra thing to explain in the paper — for a benefit that is at this scale unmeasured.

**Trigger condition for revisiting** (recorded now so the decision is evidence-based later): if Sprint 6 evaluation shows that for ≥ 20% of ANSWERABLE questions the human-identified gold passage is retrieved but ranked below position 5, add a reranker. Preferred option at that point: a local cross-encoder (`BAAI/bge-reranker-v2-m3`) behind a `Reranker` interface, so the RAG/no-RAG comparison stays clean.

The `Retriever` interface is designed with an optional, no-op-by-default `rerank` hook, so this is an insertion rather than a refactor.

---

## 11. Provenance Architecture

### 11.1 The chain

```
document_id → chapter_id → section_id → page_start..page_end → chunk_id → source passage (verbatim)
```

Every link is stored, not inferred. `EvidenceItem` carries the full chain; the answer envelope carries an `EvidenceItem` for every citation marker.

### 11.2 Invariants (each becomes an automated test)

| # | Invariant |
|---|---|
| P1 | Every citation marker in the answer resolves to exactly one `chunk_id` present in the evidence set for that run |
| P2 | Every `page_start`/`page_end` in a rendered citation exists in that document's `pages.jsonl` |
| P3 | `chunk.text` is byte-identical to the corresponding span of the canonical page text |
| P4 | No citation is ever minted from a derived field (summary, finding, concept) |
| P5 | A run whose evidence set is empty produces zero citations |
| P6 | Every run record can regenerate its exact evidence set from the frozen index |

**P2 and P3 together are the mechanical guarantee against invented page numbers.** A page number cannot be fabricated by the model because the model does not supply page numbers at all — it supplies chunk identifiers, and the *renderer* looks up pages from stored provenance. This is a structural defence, not a prompt-level request.

### 11.3 Model-facing evidence format

Each evidence item is presented to the model with a short opaque handle:

```
[E3] Sönmez (thesis), Chapter 4 — "Methodological Position", pp. 112–113
"<verbatim passage>"
```

The model cites `[E3]`. The renderer maps `[E3]` → `chunk_id` → full provenance → the reader-facing footnote. The model never types a page number, so it cannot mistype one.

---

## 12. Citation Architecture

### 12.1 Two layers, deliberately different

- **Internal provenance:** exhaustive — document, chapter, section, page range, chunk id, character offsets, retrieval scores. Machine-readable, present in every run record, used for verification.
- **User-facing citation:** academically readable footnotes. Detail that would clutter a footnote (chunk ids, char offsets) stays internal.

### 12.2 Footnote format (MVP)

Answer body carries superscript markers; a footnote block follows:

```
The author positions the study within an interpretivist tradition,¹ while noting that
this constrains generalisability.²

──
1. Sönmez, M. (YEAR). <Thesis Title>, Ch. 4 "Methodological Position", §4.2, pp. 112–113.
2. Sönmez, M. (YEAR). <Thesis Title>, Ch. 4 "Methodological Position", §4.3, p. 118.
```

A `--verbose-provenance` flag additionally prints, per footnote, the `chunk_id` and the verbatim passage — so a reviewer can check any claim against its source in one step, without leaving the terminal. This is the feature that makes the demonstration persuasive to a sceptical audience of researchers.

### 12.3 Style

Footnote style is chosen as the MVP default because it is standard in humanities and social-science scholarship and keeps the answer body readable. `CitationRenderer` is an interface; APA/Harvard/Chicago author–date renderers are a small, well-isolated future addition (§29).

---

## 13. Source-Grounded Generation

### 13.1 Prompt architecture (three parts)

1. **System prompt** — role, grounding rules, refusal policy, interpretation-labelling policy, output contract. Static; prompt-cached; version-controlled at `prompts/system_grounded_v1.md`.
2. **Evidence block** — the `EvidenceSet` rendered as `[E1]…[Ek]` with headers and verbatim passages.
3. **User block** — the question, plus any scope constraints.

### 13.2 Grounding instructions (summarised; the file is the source of truth)

The model is instructed to: answer only from the evidence block; attribute claims to the author whose passage supports them; preserve hedges, conditions, and scope limits present in the source rather than flattening them; report disagreement between passages instead of reconciling it; state explicitly when evidence is partial; refuse when evidence is insufficient; mark any inference beyond what a passage states as `[AI INTERPRETATION]`; and cite `[En]` markers for every substantive claim.

### 13.3 Structured output contract

The response is constrained to a JSON schema (Anthropic structured outputs, `output_config.format`), so that downstream code parses fields rather than prose:

```jsonc
{
  "evidence_sufficiency": "sufficient" | "partial" | "insufficient",
  "answer": "string | null",              // null iff insufficient
  "limitations": ["string"],              // required when partial
  "positions": [                          // one entry per distinct position found
    { "summary": "...", "attributed_to": "...", "qualifications": ["..."],
      "citations": ["E3","E7"] }
  ],
  "disagreements": [
    { "description": "...", "position_a": "E3", "position_b": "E7",
      "context_note": "..." }
  ],
  "ai_interpretation": ["string"],        // rendered under [AI INTERPRETATION]
  "unsupported_by_evidence": ["string"],  // model-declared gaps
  "citations_used": ["E1","E3"]
}
```

### 13.4 Honesty about what prompting achieves

Prompting alone does not guarantee grounding, and this plan does not claim it does. Grounding is a property of the **whole pipeline**: retrieval must supply the right passages; provenance must make citation mechanical; the schema must make sufficiency an explicit decision rather than an implicit one; validation must reject malformed or unresolvable citations; and evaluation must measure the residue. The prompt is one of five layers, and it is the least reliable of the five. That is why P1–P6 are enforced in code.

### 13.5 Post-generation validation (blocking)

Before an answer is shown or recorded as valid:

1. Every `[En]` marker resolves to an evidence item actually supplied → else the answer is rejected and the failure is logged as `citation_hallucination`.
2. `evidence_sufficiency == "insufficient"` ⇒ `answer` is null and `citations_used` is empty.
3. `evidence_sufficiency == "partial"` ⇒ `limitations` is non-empty.
4. The rendered output contains no page number absent from provenance (regex check against the provenance set — a belt-and-braces test of P2).

A validation failure is a **recorded experimental result**, not a silent retry. At most one bounded retry with an explicit repair instruction is permitted, and both attempts are stored.

---

## 14. Refusal Strategy

### 14.1 Four distinct situations that must not be conflated

| Case | Meaning | Correct response |
|---|---|---|
| **A. Genuine absence** | The corpus does not address the topic | Refuse; state that the collection lacks evidence |
| **B. Retrieval failure** | The corpus addresses it; retrieval failed to surface it | Refuse *and* flag for diagnostic review — this is a system defect |
| **C. Weak retrieval** | Loosely related material only | Refuse or answer with heavy qualification; surface what was retrieved |
| **D. Partial evidence** | Some but not all of the question is covered | Answer the covered part, explicitly bound the rest (§15) |

**No similarity threshold can separate A from B.** Both look like "nothing scored highly". Any design that leans on a threshold alone will systematically mislabel its own failures as absences of evidence — which, in a project about detecting hallucination, would be a serious methodological flaw.

### 14.2 MVP approach: model-primary, diagnostics-advisory

1. Retrieve as normal. **Never suppress retrieval based on scores.** The model always sees the top-k, even when scores are low.
2. The model declares `evidence_sufficiency` after reading the actual passages. Semantic judgement over passage content is strictly better than a scalar over a vector space.
3. Retrieval diagnostics (top score, score distribution, channel agreement, number of distinct sections represented) are recorded alongside — for research, for tuning, and to distinguish B from A *after the fact*.
4. **A low-diagnostic + "sufficient" combination is flagged for human review** rather than blocked. Blocking would hide the most interesting cases.
5. Refusal text is specific and useful: what was searched, what was found, what would be needed:

> The authorised research collection does not contain sufficient evidence to answer this question. Retrieval returned passages from Chapter 2 (research context) and Chapter 6 (limitations), but none address <topic>. This is a statement about the collection, not about the topic.

That last sentence matters. A refusal must not read as a claim about the world.

### 14.3 Distinguishing B from A in practice

Case B is caught by the evaluation loop, not at query time. The UNANSWERABLE and PARTIAL question sets (§17) are constructed by the researcher *from knowledge of the corpus*, so a refusal on a question known to be answerable is by construction a retrieval failure. Measuring the B rate is a headline research output, not an implementation detail.

---

## 15. Partial-Evidence Strategy

Triggered by `evidence_sufficiency == "partial"`. Requirements:

1. Answer only the supported portion.
2. Populate `limitations[]` with what could not be established — this is schema-enforced, not left to the model's discretion in prose.
3. Cite everything that *is* used, normally.
4. Render a visible boundary marker so partiality survives copy-paste into a literature review:

```
⚠ PARTIAL EVIDENCE — this answer reflects what the collection contains on this
  question and should not be read as a complete account of the author's position.

  Not established from the collection:
  • whether the position was revised in later work
  • the author's stance on <adjacent sub-question>
```

5. **Never** present a partial answer as complete. The most damaging realistic failure mode of a tool like this is not fabrication — it is a fluent, correctly-cited, *incomplete* answer read as the whole of a scholar's view. §19's synthetic-consensus work targets exactly this.

---

## 16. Conflicting-Evidence Strategy

When the evidence set contains passages in tension:

1. **Identify** the disagreement (`disagreements[]` in the schema).
2. **Present positions separately**, each with its own attribution and citations. No merged paragraph.
3. **Preserve context** — a claim in a literature-review chapter and a claim in a findings chapter are not equivalent utterances, and the rendering says so.
4. **Do not synthesise a resolution.** The system may characterise the nature of the disagreement (definitional? scope? empirical? temporal?); it may not adjudicate it.
5. Render distinctly:

```
⚖ DIVERGENT EVIDENCE

  Position A — Sönmez, Ch. 3 §3.1, p. 74:
    <summary>  ¹

  Position B — Sönmez, Ch. 6 §6.2, p. 201:
    <summary>  ²

  Nature of the divergence: the passages apply different scope conditions
  (Ch. 3 discusses the general case; Ch. 6 discusses a specific sub-population).

  [AI INTERPRETATION] These may be compatible rather than contradictory.
  Scholarly judgement required.
```

Note that even the observation "these may be compatible" is labelled as interpretation. That is deliberate: the boundary between reporting and reconciling is exactly where synthetic consensus begins.

---

## 17. AI Interpretation Strategy

### 17.1 Three tiers, always visually distinct

| Tier | Definition | Rendering |
|---|---|---|
| **Evidence** | Directly supported by a cited passage | Plain text + footnote |
| **AI interpretation** | Inference, synthesis, or connection beyond what any passage states | `[AI INTERPRETATION]` block |
| **AI suggestion** | Research directions, gaps, further-reading ideas | `[AI-GENERATED SUGGESTION]` block |

### 17.2 Enforcement

Interpretation is a **separate schema field**, not a prose convention. The model cannot blur the boundary by writing a paragraph that drifts from report into inference, because the two occupy different fields in the response object and different blocks in the rendering. A prose-level instruction ("please label your interpretations") would be violated silently and often; a structural separation is checkable.

Additionally: an interpretation may reference `[En]` markers as the material it reasons *from*, but such references are rendered as "drawing on ¹, ²" rather than as a citation supporting the interpretive claim itself. An interpretation is never presented as if the source asserted it.

---

## 18. Chronological Comparison

Not implemented in the MVP (the initial corpus has one author and one document from that author), but the **data model supports it now** so that it costs no rework later:

- `document.year` and `document.author[]` are first-class fields.
- The retriever supports metadata filters and grouping by `(author, year)`.
- The chunk model has stable identifiers suitable for cross-document alignment.

Planned behaviour when 2+ works by one scholar are present:

1. Retrieve per-work evidence for the same question.
2. Report per-work positions **separately and chronologically** — never a merged timeline.
3. Characterise the relationship as: continuity, development, added qualification, changed position, or apparent contradiction.
4. **Explicit caution, enforced in the prompt:** different wording does not entail a changed position. Terminology drifts; conventions differ by venue; a scholar may compress an argument for a journal that they developed at length in a thesis. Any suggestion of change is `[AI INTERPRETATION]` and requires the year, venue, and context of both passages to be shown side by side.

This is listed under future enhancements for implementation; the design commitment is made now.

---

## 19. Synthetic-Consensus Evaluation

**The core hypothesis to investigate:** that AI-generated syntheses tend to smooth qualified, evolving, or contested scholarly positions into an artificially unified account — and that this is *more* insidious than outright fabrication, because it is fluent, plausible, and correctly cited.

### 19.1 Automatic flags (heuristics — signals only)

| Flag | Signal |
|---|---|
| `qualification_loss` | Hedging terms present in cited passages (may, tends to, in some contexts, under conditions) absent from the answer |
| `divergence_suppressed` | Evidence set contains passages judged divergent, but `disagreements[]` is empty |
| `overreach_language` | Universalising phrasing ("the author argues that X", "establishes", "demonstrates") not matched by comparable strength in the cited passage |
| `single_source_generalisation` | A general claim citing exactly one chunk |
| `context_flattening` | Passages from structurally different chapter roles (literature review vs findings) cited interchangeably for one claim |

### 19.2 The methodological guardrail

> **A heuristic flag is not proof of synthetic consensus.** Every flagged case is queued for human review, and the reported result is the *human* verdict. Flags are a sampling instrument that raises the density of interesting cases for a human to examine; they are never presented as measurements.

Reported metrics distinguish: flags raised, cases human-reviewed, cases human-confirmed, and false-positive rate of each flag. Flag precision is itself a finding worth publishing.

---

## 20. RAG / No-RAG Baseline

### 20.1 Experimental design

| Variable | Condition A (no-RAG) | Condition B (RAG) |
|---|---|---|
| Question set | identical | identical |
| Generation model + model ID | identical | identical |
| Effort setting | identical | identical |
| Output schema | identical | identical |
| System prompt | **matched** — same role, grounding, refusal, and interpretation rules | same |
| **Evidence block** | **absent (empty EvidenceSet)** | **present (k retrieved passages)** |
| Everything else | identical | identical |

**Exactly one variable differs.** This is implemented by passing an empty `EvidenceSet` through the *same* `RAGService` code path, not by writing a separate baseline script. Two code paths would silently diverge and quietly invalidate the comparison.

### 20.2 The prompt-matching problem, addressed explicitly

There is a genuine methodological subtlety here: an instruction like "use only the evidence provided" is odd when no evidence is provided. Two options were considered.

- **Option 1 (recommended):** keep the system prompt byte-identical across conditions. The no-RAG condition then sees grounding instructions with an empty evidence block. This is the cleanest single-variable manipulation, and any resulting confusion is itself an observation about the value of retrieval.
- **Option 2:** use a minimally adapted prompt for no-RAG. More "natural", but introduces a second differing variable and weakens every claim derived from the comparison.

Recommendation: **Option 1**, with Option 2 run once as a robustness check and reported. This is flagged in §32 as a decision the researcher should confirm.

### 20.3 Measured outcomes

Unsupported-claim rate; fabricated-reference rate; verifiable-citation rate; refusal rate on UNANSWERABLE questions; attribution correctness; preservation of qualification; synthetic-consensus flag rate. All measured by human raters (§17 of the brief), with automatic metrics reported as supporting instrumentation.

**Predicted asymmetry worth stating in advance:** the no-RAG condition cannot produce a traceable citation at all, so citation-traceability is trivially 0% vs ~100%. That comparison is not informative on its own. The informative measures are unsupported-claim rate, fabricated-reference rate, and refusal calibration — pre-register these as the primary outcomes so the analysis is not accused of choosing its metrics after seeing results.

---

## 21. LLM Provider Abstraction

```python
class LLMProvider(Protocol):
    model_id: str
    provider_name: str

    def generate(
        self,
        system: str,
        messages: list[Message],
        response_schema: dict | None = None,
        max_tokens: int = 8000,
    ) -> LLMResponse: ...
```

`LLMResponse` carries: `text`, `parsed` (schema-validated object or None), `stop_reason`, `usage` (input/output/cache tokens), `model_id`, `provider_name`, `raw` (full provider payload, stored in the run record), `latency_ms`.

**Rules**

- Concrete implementations live only in `providers/llm/`. `AnthropicProvider` is the only one in the MVP; an `OpenAIProvider` is expected in Sprint 8 or later for controlled model comparison.
- Model names come from `LLM_MODEL`. **A vendor model string must never appear outside `providers/` and `.env`** — enforced by a test that greps the source tree.
- `stop_reason` is inspected before reading content. In particular `refusal` is handled as a first-class outcome and recorded distinctly from an evidence-based refusal — conflating a safety refusal with "the collection lacks evidence" would corrupt the results.
- Provider errors surface; they are never swallowed into a generic "no answer".
- **No Bedrock.** Direct provider APIs only. The abstraction is what would make a Bedrock backend possible later, and that is the extent of the accommodation the MVP makes for it.

---

## 22. Embedding Provider Abstraction

```python
class EmbeddingProvider(Protocol):
    model_id: str
    provider_name: str
    dimensions: int

    def embed_documents(self, texts: list[str]) -> np.ndarray: ...   # (n, d), unit-normalised
    def embed_query(self, text: str) -> np.ndarray: ...              # (d,)
```

**Rules**

- `embed_query` is separate from `embed_documents` because some models require asymmetric prefixes (`bge-m3`: `"query: "` / `"passage: "`). Collapsing them into one method is the single most common way to silently degrade retrieval by 10–20%.
- Providers declare `dimensions`; `IndexStore` validates against `manifest.json` and refuses to start on mismatch.
- Implementations in the MVP: `OpenAIEmbeddingProvider` (default) and `LocalSentenceTransformerProvider` (for the Sprint 3 swap-test and offline operation).
- Disk cache keyed on `(model_id, sha256(text))`.

---

## 23. Environment-Variable Configuration

`.env` is never committed. `.env.example` is committed and documents every variable. **This plan does not create a `.env` file.**

```bash
# ---- Embedding role ----
EMBEDDING_PROVIDER=openai            # openai | local
EMBEDDING_MODEL=text-embedding-3-large
EMBEDDING_DIMENSIONS=3072
EMBEDDING_BATCH_SIZE=64

# ---- Generation role ----
LLM_PROVIDER=anthropic               # anthropic | openai
LLM_MODEL=claude-opus-5
LLM_MAX_TOKENS=8000
LLM_EFFORT=high                      # low | medium | high | xhigh | max

# ---- Credentials (never hard-coded, never committed) ----
ANTHROPIC_API_KEY=
OPENAI_API_KEY=

# ---- Retrieval ----
RETRIEVAL_TOP_K=10
RETRIEVAL_CANDIDATE_K=20
RETRIEVAL_MODE=hybrid                # dense | lexical | hybrid
RRF_K=60
NEIGHBOUR_EXPANSION=1

# ---- Chunking ----
CHUNK_TARGET_TOKENS=800
CHUNK_MAX_TOKENS=1100
CHUNK_OVERLAP_TOKENS=120

# ---- Paths ----
CORPUS_MANIFEST=corpus.yaml
DATA_RAW_DIR=data/raw
DATA_CANONICAL_DIR=data/canonical
INDEX_DIR=data/index
RUNS_DIR=data/runs

# ---- Reproducibility ----
RUN_SEED=42
RECORD_RAW_RESPONSES=true
```

**Configuration rules**

1. Loaded once at startup into a validated, frozen `Settings` object (`pydantic-settings`). No `os.getenv` scattered through the code.
2. Missing required values fail loudly at startup, never at first use mid-run.
3. **Never hard-code model names.** A test asserts that no vendor model string literal appears outside `providers/` and `.env.example`.
4. The effective configuration is snapshotted into every run record, with secrets redacted.
5. Note for the paper: on Claude Opus 5, sampling parameters (`temperature`, `top_p`, `top_k`) are not accepted, and thinking is on by default. Determinism therefore cannot be obtained by pinning temperature — see §26.

---

## 24. Security and API-Key Management

- Keys come from environment variables (loaded from `.env` in development) or the OS keychain / CI secret store in other contexts. **Never** in source, notebooks, prompts, run records, logs, or commits.
- `.gitignore` covers `.env`, `data/raw/`, `data/canonical/`, `data/index/`, `data/runs/`, `*.pdf`.
- **Copyright:** the thesis and article are third-party works. Source PDFs and extracted full text are not committed to the repository. The repository holds code, prompts, configuration, question sets, and — where the researcher confirms it is permissible — evaluation outputs containing short quotations.
- **Redaction:** `RunRecorder` passes every record through a redactor that strips anything matching known key patterns before writing.
- Logs record `provider_name` and `model_id`; never authorisation headers.
- Third-party data flow is documented plainly for ethics review: chunk text is transmitted to the embedding provider at index time; retrieved passages and the question are transmitted to the generation provider at query time. If the corpus is ever unpublished or sensitive, the local embedding provider plus a self-hosted generation model is the required configuration — the abstraction makes this a configuration change, and this should be stated in any ethics application.
- Dependencies pinned via lockfile; `pip-audit` in CI.

---

## 25. Testing Strategy

| Layer | Scope | Notes |
|---|---|---|
| **Unit** | Chunk boundary arithmetic, page-span computation, RRF, citation rendering, schema validation, config loading | Fast, no network |
| **Provenance invariants** | P1–P6 from §11.2, as executable property tests | The most important tests in the project |
| **Contract** | Every `EmbeddingProvider` / `LLMProvider` implementation runs the same interface test suite | Ensures a provider swap is truly transparent |
| **Golden-file** | A small committed synthetic PDF with known structure → asserted chapters, sections, pages, chunks | Detects regressions in extraction, deterministically and without the copyrighted corpus |
| **Fake providers** | `FakeEmbeddingProvider` (deterministic hash-based vectors), `FakeLLMProvider` (scripted responses, including malformed ones) | The whole pipeline is testable offline with zero API cost |
| **Refusal/partial/conflict** | Scripted `FakeLLMProvider` responses exercising every branch, including invalid ones | Guarantees an invalid model output is rejected rather than rendered |
| **Integration (marked, opt-in)** | One real call per provider, `-m live`, skipped by default in CI | Catches API drift without making CI cost money |
| **Evaluation regression** | A frozen 10-question mini-set with recorded outputs; drift is reported, not asserted equal | Model outputs are not deterministic (§26) — the test surfaces change, it does not fail on it |

Target: ≥ 85% line coverage on `core/`, 100% on provenance and citation modules. Every sprint's acceptance criteria include its tests passing.

---

## 26. Reproducibility Strategy

Reproducibility here means: *another researcher, or the same researcher in two years, can re-derive the reported results.* Three tiers, because they are genuinely different in strength:

### Tier 1 — Fully deterministic (guaranteed)
Extraction, structuring, chunking, index building given fixed inputs and a fixed embedding model. Same PDF + same config ⇒ byte-identical `pages.jsonl`, `document.json`, and chunk set. Verified by hashes in the manifest.

### Tier 2 — Frozen artifacts (guaranteed)
The built index is a research artifact: `vectors.npy`, `chunks.sqlite`, and `manifest.json` (embedding model, dimensions, chunk config, per-document SHA-256, corpus manifest hash, build timestamp, library versions). Experiments run against the frozen index; they never silently re-embed. Retrieval is exact (not ANN), so **for a fixed index and question, the retrieved evidence set is deterministic** — a real and useful guarantee, and a reason the brute-force store is the right call.

### Tier 3 — Not deterministic, therefore recorded verbatim (honest limitation)
LLM generation. On current Claude models sampling parameters are not available and thinking is enabled by default, so "temperature = 0" is not a reproducibility strategy — and was never a guarantee of identical output on any model. The mitigations are:

- **Record everything.** Every run stores: run id, UTC timestamp, config snapshot (redacted), corpus + index manifest hashes, prompt file version hashes, the fully rendered prompt, the complete raw provider response, parsed output, token usage, latency, and validation results.
- **Report distributions, not single runs.** Evaluation executes each question *n* times (default 3) and reports variation across runs as a measured quantity. Output variance is data, not noise to be hidden.
- **Version prompts as files** under `prompts/`, hashed into every run record. A prompt change is a visible experimental change.
- **State the limitation in the paper.** Exact output reproducibility is not achievable with a hosted, non-deterministic generation model. Full input reproducibility and complete output archival are — and that is what is claimed.

Run records are append-only JSONL under `data/runs/<run_id>/`.

---

## 27. Project / Folder Structure

```
source-grounded-rag/
├── README.md                      # overview + Task Log (chronological record)
├── CLAUDE.md                      # routing file for AI assistants
├── .env.example                   # documented; .env itself is never committed
├── .gitignore
├── pyproject.toml
├── corpus.yaml                    # the authorised research collection
│
├── docs/
│   ├── plans/
│   │   └── PLAN_V2.md             # THIS FILE — authoritative plan
│   ├── decisions/                 # ADRs, one per resolved open question (§32)
│   └── evaluation/                # question sets, rubrics, human-rating sheets
│
├── prompts/                       # versioned, hashed into run records
│   ├── system_grounded_v1.md
│   └── system_baseline_v1.md
│
├── src/sgrag/
│   ├── config.py                  # Settings — the only place env vars are read
│   ├── models.py                  # Document/Chapter/Section/Chunk/EvidenceSet/AnswerEnvelope
│   ├── ingestion/
│   │   ├── scanner.py
│   │   ├── extractors/            # pymupdf.py, markitdown.py (comparator)
│   │   ├── structurer.py
│   │   └── metadata.py
│   ├── chunking/chunker.py
│   ├── providers/
│   │   ├── embedding/             # base.py, openai.py, local.py, fake.py
│   │   └── llm/                   # base.py, anthropic.py, fake.py
│   ├── index/store.py             # vectors.npy + chunks.sqlite + manifest.json
│   ├── retrieval/
│   │   ├── dense.py  lexical.py  fusion.py  retriever.py
│   ├── generation/
│   │   ├── rag_service.py  prompt_builder.py  schema.py  validator.py
│   ├── citation/renderer.py
│   ├── evaluation/
│   │   ├── runner.py  metrics.py  consensus_flags.py  baseline.py
│   ├── runs/recorder.py
│   └── cli/main.py                # Typer; argument parsing + presentation only
│
├── tests/
│   ├── unit/  provenance/  contract/  golden/  integration/
│   └── fixtures/synthetic_thesis.pdf
│
└── data/                          # gitignored
    ├── raw/  canonical/  index/  runs/
```

**The `docs/plans/` convention established here:** every substantial planning document lives in `docs/plans/` with a version suffix (`PLAN_V2.md`, then `PLAN_V3.md`, …). Plans are never edited in place after approval; a new phase gets a new file, and the superseded plan is retained for the audit trail. Architectural decisions taken *between* plans are recorded as short ADRs in `docs/decisions/`.

---

## 28. MVP Scope

### In scope

1. Ingest 2 PDFs → canonical per-page extraction + verified chapter/section structure.
2. Structure-aware chunking with full provenance.
3. Embedding via configurable provider; frozen, manifest-verified index.
4. Hybrid retrieval (dense + BM25 + RRF) with optional metadata filter.
5. Source-grounded generation with structured output, via configurable LLM provider.
6. Refusal, partial-evidence, conflicting-evidence, and AI-interpretation handling.
7. Footnote citations backed by verified provenance.
8. CLI: `ingest`, `index`, `query`, `evaluate`, `baseline`.
9. Complete run recording.
10. Evaluation harness: three question categories, automatic metrics, human-rating sheets.
11. RAG vs no-RAG baseline via one code path.
12. Synthetic-consensus flags + human review queue.
13. Reproducible outputs suitable for static presentation slides.

### Out of scope for MVP

Web UI; FastAPI/Docker (optional Sprint 8); multi-language; OCR; reranking; hierarchical retrieval; chronological comparison *implementation* (model support only); knowledge graphs; multi-model ensembles; Bedrock; hosted deployment; user accounts.

### Definition of done

The researcher can, from a clean checkout: configure `.env`, place two PDFs, run four commands, and obtain — reproducibly — a correct cited answer, a partial-evidence answer, a clear refusal, and a RAG/no-RAG comparison table, with every claim traceable to a page.

---

## 29. Future Enhancements

**Near-term (post-MVP):** FastAPI + Docker; cross-encoder reranking (if §10's trigger fires); OpenAI generation provider for controlled model comparison; APA/Harvard/Chicago citation renderers; sentence-window / parent-document retrieval.

**Medium-term:** chronological comparison across a scholar's corpus (design already committed, §18); hierarchical retrieval as the corpus grows past ~50 documents; MarkItDown-backed ingestion for `.docx`/`.pptx`/HTML; multi-language support (embedding model + prompt localisation); a reviewer UI for the human-evaluation loop; export to Zotero/BibTeX.

**Longer-term / research:** cross-document claim alignment; automated qualification-preservation scoring; citation-graph awareness; local self-hosted generation for sensitive corpora; per-claim confidence calibration studies against human judgement.

---

## 30. Agile Sprints

Process for every sprint: **PLAN → IMPLEMENT → TEST → REVIEW → APPROVE → NEXT**. Human approval is required before each sprint begins and before its results are accepted. On approval, append a row to the README Task Log.

---

### Sprint 1 — Foundation, Configuration, and Provider Abstractions

**Objective.** Establish a runnable, fully tested skeleton with both provider abstractions and no domain logic — so that every later sprint plugs into a stable spine.

**Scope.** Project scaffolding (`pyproject.toml`, lint/format/type config); `Settings` with validation; core dataclasses/Pydantic models (`Document`, `Chapter`, `Section`, `Chunk`, `EvidenceItem`, `EvidenceSet`, `AnswerEnvelope`); `EmbeddingProvider` and `LLMProvider` protocols; `OpenAIEmbeddingProvider`, `AnthropicLLMProvider`, and both fakes; `RunRecorder` skeleton; Typer CLI shell with `version` and `config check`; `.env.example`; `.gitignore`.

**Files/components.** `pyproject.toml`, `.env.example`, `.gitignore`, `src/sgrag/{config,models}.py`, `src/sgrag/providers/**`, `src/sgrag/runs/recorder.py`, `src/sgrag/cli/main.py`, `tests/{unit,contract}/**`.

**Acceptance criteria.** `sgrag config check` prints the effective, redacted configuration and exits 0 with a valid `.env`, non-zero with a clear message otherwise. Both providers satisfy the shared contract suite. Fakes work with zero network. No vendor model string exists outside `providers/` and `.env.example` (test-enforced). Type checks and lint pass.

**Tests.** Config validation (valid/missing/malformed); provider contract suite against fakes and (opt-in, `-m live`) real providers; run-record redaction; model round-trip serialisation.

**Expected outputs.** A repository that installs, type-checks, lints, and tests green; one live smoke call per provider on request.

**Risks.** Over-engineering the abstractions before real requirements land — mitigated by keeping the protocols to the minimum surface in §21/§22 and resisting speculative options.

---

### Sprint 2 — PDF Ingestion, Document Structure, and Metadata

**Objective.** Turn the two PDFs into a verified, immutable canonical representation with trustworthy page and structure provenance.

**Scope.** `Scanner`; `PyMuPDFExtractor` producing `pages.jsonl`; `MarkItDownExtractor` as a comparator behind the same interface; `Structurer` (outline-first, heuristics second, low-confidence flagging third); `MetadataResolver` with explicit null-on-uncertainty; `document.json` schema + validation; `extraction_report.md`; CLI `ingest`; the **human structure-verification checkpoint**; a written comparator note on PyMuPDF vs MarkItDown for the paper.

**Acceptance criteria.** Both PDFs ingest without unhandled errors. Every page in `pages.jsonl` has a page number matching the PDF. Chapter/section tree is generated and reviewed by the researcher; anything uncertain is flagged, not guessed. No metadata field is populated by guesswork. Re-running ingestion on unchanged inputs is byte-identical. The comparator note is written.

**Tests.** Golden-file test against `tests/fixtures/synthetic_thesis.pdf` (known structure); page-count and page-number invariants; empty-page handling; idempotence via hash comparison; metadata-uncertainty propagation.

**Expected outputs.** `data/canonical/<doc_id>/` for both documents; `extraction_report.md` per document; the extractor comparison note in `docs/`.

**Risks.** Thesis layout defeats heading heuristics (**most likely risk in the project**) — mitigated by outline-first detection, the human checkpoint, and Docling as a documented fallback. Missing/absent text layer — detected at Sprint 2, not at Sprint 5.

---

### Sprint 3 — Chunking, Embedding, and Index Build

**Objective.** Produce a frozen, manifest-verified, provenance-complete index.

**Scope.** `Chunker` per §7; embedding batch pipeline with disk cache; `IndexStore` (`vectors.npy` + `chunks.sqlite` + `manifest.json`) with mismatch refusal; CLI `index build` / `index info`; the **embedding-provider swap-test** (rebuild with local `bge-m3`, compare retrieval overlap on a small probe set).

**Acceptance criteria.** No chunk crosses a chapter boundary (test-enforced). Every chunk's `page_start`/`page_end` verified against `pages.jsonl` (invariant P2). Every chunk's text is byte-identical to its canonical span (P3). `manifest.json` fully populated. Loading an index with a mismatched embedding model fails loudly. The swap-test runs and its comparison is documented.

**Tests.** Chunk-boundary property tests; page-span verification across all chunks; overlap correctness; cache-key isolation across models; manifest mismatch refusal; deterministic rebuild.

**Expected outputs.** A frozen index; `index info` summary (chunk count, token distribution, per-chapter coverage); the swap-test report.

**Risks.** Chunk size mis-tuned for this corpus's argumentative density — mitigated by making size configurable and reviewing a sample of 20 chunks with the researcher before freezing. Embedding cost/rate limits — negligible at this scale.

---

### Sprint 4 — Retrieval

**Objective.** Retrieve well, and make retrieval quality inspectable *before* any generation exists to obscure it.

**Scope.** Exact dense cosine search; BM25 lexical channel; RRF fusion; metadata pre-filtering; neighbour expansion; deduplication; `EvidenceSet` assembly with full provenance and `retrieval_diagnostics`; CLI `query --retrieval-only` rendering ranked passages with provenance and per-channel scores; a no-op `rerank` hook.

**Acceptance criteria.** `sgrag query "<question>" --retrieval-only` returns k passages, each showing document, chapter, section, page range, both channel scores, and fused rank. Metadata filters work. Retrieval is deterministic for a fixed index and query. Scores are labelled as diagnostics and never as confidence anywhere in the output.

**Tests.** RRF correctness against hand-computed cases; filter correctness; dedup of overlapping chunks; determinism; empty-result handling; provenance completeness for every returned item.

**Expected outputs.** A retrieval CLI usable for manual corpus exploration; a first informal retrieval-quality read on ~15 researcher-authored questions.

**Risks.** Hybrid fusion tuned by intuition rather than evidence — mitigated by deferring tuning to Sprint 6 and recording `RETRIEVAL_TOP_K`/`RRF_K` per run.

---

### Sprint 5 — Source-Grounded Generation, Refusal, Partial and Conflicting Evidence, Citations

**Objective.** The heart of the system: grounded answers, honest refusals, and mechanically verified citations.

**Scope.** `prompts/system_grounded_v1.md`; `PromptBuilder`; the response JSON schema (§13.3); `RAGService`; `Validator` implementing §13.5 including the citation-hallucination check; refusal / partial / conflict / interpretation rendering (§14–17); `CitationRenderer` with footnotes and `--verbose-provenance`; full run recording; CLI `query`.

**Acceptance criteria.** An answerable question yields a cited answer whose every citation resolves and whose every page number exists in provenance (P1–P5 test-enforced). An out-of-corpus question yields a clear, specific refusal with no citations. A partially-covered question yields an answer with a non-empty `limitations[]` and a visible partial-evidence marker. A question with divergent evidence yields separated positions with no merged conclusion. Interpretation appears only inside labelled blocks. Malformed model output is rejected and recorded, never rendered.

**Tests.** Full branch coverage via `FakeLLMProvider` (sufficient / partial / insufficient / conflicting / malformed / hallucinated-citation / safety-refusal); P1–P6 invariants end-to-end; renderer snapshot tests; a regex test that no rendered page number is absent from provenance.

**Expected outputs.** Three demonstrable cases — clean answer, partial evidence, refusal — with complete run records. These are the presentation's core exhibits.

**Risks.** Model over-refuses or under-refuses — this is a research finding as well as a tuning target; addressed by measurement in Sprint 6, not by prompt-thrashing here. Schema-vs-prose tension in long answers — mitigated by keeping the schema shallow.

---

### Sprint 6 — Evaluation Harness and Human Review

**Objective.** Turn the system into an instrument that produces measurements.

**Scope.** Question sets (ANSWERABLE / PARTIAL-AMBIGUOUS / UNANSWERABLE, ~20 each, authored by the researcher from corpus knowledge, with gold passages for the answerable set); `evaluation/runner.py` with n-repeat execution; automatic metrics (citation resolution rate, page-verification rate, refusal rate by category, retrieved-gold-passage rate, retrieval rank of gold passage); human-rating sheet generation (CSV/Markdown) covering factual accuracy, source relevance, citation traceability, attribution correctness, fabricated references, unsupported claims, refusal appropriateness, preservation of disagreement; the §10 reranker trigger check.

**Acceptance criteria.** `sgrag evaluate --set answerable` executes the set, writes per-question run records, and emits both an automatic-metrics table and a human-rating sheet. Case-B (retrieval failure) is distinguishable from Case-A (genuine absence) via gold-passage tracking. Run-to-run variance is reported. Every metric definition is documented in `docs/evaluation/`.

**Tests.** Runner determinism given a `FakeLLMProvider`; metric computation against hand-labelled fixtures; rating-sheet completeness; correct handling of a refusal within metric aggregation.

**Expected outputs.** A completed evaluation over all three question sets; a metrics report; human-rating sheets ready for the researcher and any second rater.

**Risks.** Question sets that are unconsciously biased toward what the system does well — mitigated by writing all three sets **before** seeing system output, and recording that ordering in the methodology.

---

### Sprint 7 — RAG vs No-RAG Baseline, Synthetic Consensus, and Presentation Artifacts

**Objective.** Answer the research question and produce the conference materials.

**Scope.** `evaluation/baseline.py` running both conditions through one code path with an empty vs populated `EvidenceSet`; `prompts/system_baseline_v1.md` (byte-identical to the grounded prompt for the primary run; the Option-2 variant for the robustness check, §20.2); the §19 synthetic-consensus flags plus a human-review queue; comparison reporting; export of reproducible, slide-ready artifacts (the three demonstration cases and the comparison table) as Markdown + JSON.

**Acceptance criteria.** `sgrag baseline --set all` produces a per-question side-by-side comparison and an aggregate table. The only differing input between conditions is the evidence block — asserted by a test that diffs the two rendered prompts and confirms the difference is confined to the evidence region. Synthetic-consensus flags produce a review queue with flag rationale; reported outcomes are human verdicts, with flag precision reported separately. Exports render correctly on slides without a live system.

**Tests.** Prompt-difference assertion between conditions; flag heuristics against hand-labelled fixtures; export format snapshots; end-to-end baseline run with fakes.

**Expected outputs.** The comparison table; the flagged-case review queue; the three demonstration exhibits; a findings summary in `docs/evaluation/`.

**Risks.** Results may not support the hypothesis — this is a legitimate outcome and must be reported as found; the pre-registration of primary metrics in §20.3 exists precisely to make that reporting credible. Small corpus limits generalisability — stated as a limitation, not engineered around.

---

### Sprint 8 (Optional / Deferred) — API and Packaging

**Objective.** Make the system usable beyond the researcher's terminal, *if* required after Sprint 7.

**Scope.** FastAPI wrapper over the existing service layer (`/query`, `/health`, `/corpus`); Dockerfile + compose; API-key auth; a second `LLMProvider` (OpenAI) for controlled model comparison.

**Acceptance criteria.** The API adds no logic — endpoints call the same services the CLI calls. The container runs with only environment variables supplied. Model comparison is achievable by changing `LLM_PROVIDER`/`LLM_MODEL` alone, with no retrieval change.

**Risks.** Scope creep away from the research question. **This sprint is explicitly optional and should only be approved if a concrete need emerges.**

---

## 31. Risks

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R1 | Thesis layout defeats chapter/section detection | **High** | High | Outline-first detection; human verification checkpoint (Sprint 2); Docling fallback documented |
| R2 | Citations resolve but the answer subtly misrepresents the source | Medium | **High** | Human evaluation is mandatory; `--verbose-provenance`; synthetic-consensus flags; automatic metrics cannot catch this and are not claimed to |
| R3 | Refusal miscalibration (over- or under-refusal) | **High** | Medium | Model-primary + diagnostics-advisory design; measured in Sprint 6; treated as a finding, not only a defect |
| R4 | Retrieval failure misread as absence of evidence (Case B as Case A) | Medium | **High** | Gold-passage tracking in the answerable set makes B measurable and distinguishable |
| R5 | Two-document corpus limits generalisability | Certain | Medium | Stated as a limitation; architecture is corpus-agnostic; swap-test demonstrates portability |
| R6 | Non-deterministic generation weakens reproducibility claims | Certain | Medium | Three-tier reproducibility (§26); n-repeat runs; complete verbatim archival; honest statement of limits |
| R7 | Hosted embedding model changes beneath a fixed name | Low | Medium | Frozen index artifact; manifest hashes; local-model alternative validated in Sprint 3 |
| R8 | Copyright constraints on committing corpus/outputs | Medium | Medium | Corpus gitignored; only short quotations in shared outputs, subject to researcher confirmation |
| R9 | Scope creep into UI/infrastructure | Medium | Medium | Sprint 8 explicitly optional; "no infrastructure without a requirement" as a standing rule |
| R10 | Prompt over-tuning to the evaluation set | Medium | **High** | Prompts versioned and hashed; question sets authored before seeing output; tuning changes recorded as experimental events |
| R11 | Vendor API drift breaks the pipeline mid-study | Low | Medium | Provider abstraction; opt-in live tests; pinned SDK versions; frozen index insulates ingestion |
| R12 | Chunk size strips the qualifications the research is about | Medium | **High** | Generous 700–900 token target; section-bounded splits; manual review of 20 chunks before freezing (Sprint 3) |

---

## 32. Open Architectural Decisions

Each requires a human decision; each becomes an ADR in `docs/decisions/` when resolved.

| # | Decision | Options | Plan's recommendation |
|---|---|---|---|
| D1 | Embedding provider for MVP | OpenAI `text-embedding-3-large` / local `bge-m3` / Voyage | **OpenAI**, with the local model validated as a swap in Sprint 3. Choose local instead if offline operation or full determinism outranks retrieval quality |
| D2 | Generation model for MVP | `claude-opus-5` / `claude-sonnet-5` | **`claude-opus-5`** — refusal calibration and disagreement handling are the study's dependent variables, and query volume is small enough that cost is not a constraint |
| D3 | Baseline prompt handling | Byte-identical / minimally adapted | **Byte-identical** as primary; adapted variant as a reported robustness check (§20.2) |
| D4 | Whether chapter summaries reach the generation step | Retrieval-only / also shown as labelled non-evidence | **Retrieval-only in MVP** — the simplest guarantee that a summary can never be cited |
| D5 | Number of evaluation repetitions | 1 / 3 / 5 | **3** — enough to surface variance without tripling review burden |
| D6 | Citation style | Footnote / APA / Harvard | **Footnote** for MVP; renderer interface makes others cheap |
| D7 | Second human rater | Single rater / two raters + agreement | **Two raters if feasible** — inter-rater agreement materially strengthens the claims; single-rater is acceptable for a conference demonstration if resources are limited, and must then be stated |
| D8 | Committing evaluation outputs containing quotations | Commit / withhold | Researcher's call, subject to copyright and any ethics approval |
| D9 | Whether Sprint 8 (API/Docker) happens at all | Yes / no / later | **Defer** — decide after Sprint 7 |

---

## 33. Explicit Assumptions

| # | Assumption | If false |
|---|---|---|
| A1 | Both PDFs are born-digital with an extractable text layer | OCR is required; adds a sprint and introduces extraction-error confounds |
| A2 | The thesis has a PDF outline/bookmark tree | Heading detection falls back to heuristics; the Sprint 2 human checkpoint becomes essential rather than merely valuable |
| A3 | The corpus is English-only for this phase | Embedding model choice must be revisited (`bge-m3` becomes clearly preferable) |
| A4 | The researcher can author ~60 evaluation questions and rate outputs | Evaluation scope shrinks; the study becomes illustrative rather than measured |
| A5 | The researcher has, or can obtain, Anthropic and OpenAI API keys | With Anthropic only, the local embedding provider becomes mandatory — supported by design |
| A6 | Total API spend across the project stays under ~$50 | At ~1,500 chunks and a few hundred generations this is a comfortable ceiling |
| A7 | Python 3.11+ is available in the target environment | Minor adjustment |
| A8 | The corpus may be used for research analysis; outputs may quote briefly | Sharing of outputs is restricted; the system still functions locally |
| A9 | No live demo is required at the conference | Pre-generated artifacts (Sprint 7) already satisfy this; a live demo would add a stability requirement |
| A10 | A human is available to approve each sprint | The Agile process as specified cannot proceed without this |
| A11 | The initial two documents have different authors (thesis + selected article) | If both are by Sönmez, chronological comparison (§18) becomes MVP-relevant and should be pulled forward |

---

# FINAL SECTION

## A. RECOMMENDED ARCHITECTURE

A **Python CLI application** with a strictly layered, provider-agnostic core.

**Ingestion** treats the PDF as a sequence of pages, not as a document to be flattened into Markdown: `PyMuPDF` produces an immutable per-page canonical extraction, structure is detected outline-first and **verified by a human once per document**, and everything derived (summaries, findings, concepts) is stored separately and can never be cited.

**Indexing** produces a frozen research artifact — a NumPy vector matrix, a SQLite chunk store, and a manifest hashing the corpus, chunking configuration, and embedding model. Chunks are section-bounded, ~800 tokens, and carry the full `document → chapter → section → page → chunk` chain.

**Retrieval** is exact (brute-force cosine — correct and deterministic at ~1,500 chunks, and it removes ANN recall variance as an experimental confound), hybridised with BM25 through Reciprocal Rank Fusion, with optional metadata filtering. Similarity scores travel as diagnostics and are never rendered as confidence.

**Generation** receives an `EvidenceSet` and nothing else — it has no access to the index. This one constraint is what makes the no-RAG baseline a single code path with an empty evidence set rather than a parallel implementation that could silently diverge. The model returns a structured object declaring evidence sufficiency, positions with attributions and qualifications, disagreements, and separately-fielded AI interpretation. **The model never emits a page number**; it emits opaque evidence handles, and the citation renderer resolves them from stored provenance. Fabricated page numbers are therefore structurally impossible rather than merely discouraged.

**Both model roles are abstracted and configured entirely through environment variables.** Anthropic has no embeddings endpoint, so the two-role separation is not an architectural nicety here — it is forced by reality, and the plan treats that as a point worth making in the paper. No Bedrock. No vendor model name anywhere outside `providers/` and `.env`, enforced by a test.

Every run is recorded in full — prompt, raw response, config, manifest hashes, usage, validation results — because in this project runs are evidence.

## B. RECOMMENDED MVP

| Dimension | Choice |
|---|---|
| Runtime | Python 3.11+, Typer CLI |
| Extraction | PyMuPDF (`pymupdf4llm`); MarkItDown retained as a documented comparator |
| Chunking | Section-bounded, 700–900 tokens, 15% overlap, never crossing a chapter |
| Embedding | `EMBEDDING_PROVIDER=openai`, `EMBEDDING_MODEL=text-embedding-3-large` (local `bge-m3` validated as a swap) |
| Index | `vectors.npy` + `chunks.sqlite` + `manifest.json`; exact search; no vector database |
| Retrieval | Hybrid dense + BM25 via RRF, k=10, optional metadata filter, no reranker |
| Generation | `LLM_PROVIDER=anthropic`, `LLM_MODEL=claude-opus-5`, effort `high`, structured output |
| Grounding | Structured sufficiency declaration + code-enforced citation validation + provenance invariants P1–P6 |
| Citations | Footnotes, with `--verbose-provenance` for verbatim source inspection |
| Evaluation | 3 question categories × ~20, n=3 repeats, automatic metrics + mandatory human rating |
| Baseline | One code path, empty vs populated evidence set, byte-identical prompt |
| Infrastructure | **None.** No database server, no vector DB, no container, no cloud service |

Deliverable: four commands from a clean checkout produce a cited answer, a partial-evidence answer, a refusal, and a RAG/no-RAG comparison — reproducibly, with every claim traceable to a page.

## C. PROPOSED SPRINT 1

**Foundation, Configuration, and Provider Abstractions.**

**Objective:** a runnable, fully tested skeleton containing both provider abstractions and no domain logic.

**Deliverables:** `pyproject.toml` with pinned dependencies and lint/type configuration; `.env.example` documenting every variable in §23; `.gitignore` covering secrets, corpus, index, and runs; `config.py` exposing a single validated, frozen `Settings`; `models.py` with the core data model; `EmbeddingProvider` and `LLMProvider` protocols with one real and one fake implementation each; a `RunRecorder` skeleton with secret redaction; a Typer CLI exposing `version` and `config check`; unit and contract test suites.

**Acceptance criteria:** `sgrag config check` exits 0 with a valid `.env` and prints the effective redacted configuration; exits non-zero with an actionable message otherwise. Both provider implementations pass the same contract suite. The full test suite runs offline against fakes with zero API cost. A test proves no vendor model string appears outside `providers/` and `.env.example`. Lint and type checks pass.

**Explicitly not in Sprint 1:** PDF handling, chunking, embedding, retrieval, prompts, and generation. Sprint 1 builds the spine only.

**Why this first:** every later sprint depends on configuration, the data model, and the provider abstractions. Building them first — and proving them with fakes — means Sprints 2–7 can be developed and tested without spending a cent on API calls, and means the provider swap promised in §21/§22 is demonstrated before anything depends on it.

**Estimated size:** small — roughly a day of focused work; no external dependencies beyond package installation.

## D. OPEN QUESTIONS REQUIRING HUMAN DECISION

1. **Embedding provider (D1).** Confirm OpenAI `text-embedding-3-large`, or choose local `bge-m3` if offline operation and full determinism outrank retrieval quality. *Needed before Sprint 3.*
2. **Generation model (D2).** Confirm `claude-opus-5`, or choose `claude-sonnet-5` if cost or latency is a real constraint. *Needed before Sprint 5.*
3. **Baseline prompt handling (D3).** Confirm the byte-identical prompt as the primary condition, with the adapted variant as a reported robustness check. *This is a methodological decision affecting every claim derived from the comparison. Needed before Sprint 7.*
4. **Corpus confirmation.** Exact files, and the bibliographic metadata for both — particularly whether the selected article is also by Sönmez, which would pull chronological comparison (§18) into MVP scope. *Needed before Sprint 2.*
5. **Copyright and ethics (D8).** May extracted text and short quotations appear in committed evaluation outputs? Is any ethics approval required for this use of the thesis? *Needed before Sprint 2.*
6. **Evaluation capacity (D5, D7, A4).** Can the researcher author ~60 questions and rate the outputs? Is a second rater available for inter-rater agreement? *Needed before Sprint 6.*
7. **API keys (A5).** Are Anthropic and OpenAI keys available? If only Anthropic, the local embedding provider becomes mandatory — supported, but it should be decided rather than discovered. *Needed before Sprint 3.*
8. **Sprint 8 (D9).** Is a FastAPI/Docker deployment wanted at all, or is the CLI sufficient for the conference and the paper? *Decide after Sprint 7.*
9. **Presentation format.** Confirm that static, pre-generated slide artifacts are sufficient and that no live demo will be attempted. *Needed before Sprint 7.*

---

*End of PLAN_V2.md. No implementation has begun. Sprint 1 awaits approval.*
