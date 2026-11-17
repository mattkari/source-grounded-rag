# PLAN_V7 — Several sources (Sprints M0–M4)

Status: **direction approved by the researcher on 17 November 2026; each sprint is approved
separately.** Sprint M0 is this document and ADR 0013. No code for M1–M4 is written yet.
Builds on the document record of `PLAN_V4.md` and the article writer of `PLAN_V6.md`. Does not
change `PLAN_V3.md` or `PLAN_V5.md`; the evaluation is untouched. Where this plan differs from
PLAN_V4 §2–§3 ("one active thesis", "no journal articles", "no two-column layouts", "no searching
several documents at once") this plan is the later decision.

## 1. Why

The app answers from, and drafts from, one thesis at a time. A literature review, and most
articles worth writing, draw on several works. The researcher wants to ingest journal articles
beside theses and to draft an article that uses and cites more than one of them, with the same
trail from every sentence back to a printed page.

## 2. Decisions already taken (researcher, 17 November 2026)

| Topic | Decision |
|---|---|
| Source types | Journal articles and book chapters with a text layer, one or two columns, alongside theses. No scanned PDFs. |
| Agent or workflow | **Not an agent.** Fixed steps. Code shows where each source has material; the researcher chooses what is used. |
| Evaluation | Unchanged: the built-in thesis only, through the unchanged single-document path. |

Assumed without asking, open to objection: identity is proposed from the PDF and confirmed by the
researcher, with no network lookup; sources share the embedding model already configured; uploaded
PDFs stay in the private `library/` folder and are never committed.

## 3. What the code already gives, and what is missing

Already there (read on `main` at `4f650a4`):

- Each document has its own record, extraction, audit and index (`upload.py`, `documents.Document`).
- Identity travels with each passage (`ask.EvidenceItem.document`); the evidence shown to the
  model, `ask.footnote` and `article/export.source_line` read author and year per passage.
- A chunk id begins with its document id, so ids are unique across documents.
- A document with no chapters is extracted as one run (ADR 0003).

Missing:

- `layout.py` and `ingest.py` assume one text column; `identity.py` assumes a thesis title page.
- `ask.retrieve` ranks one index. `article.pipeline.Workspace` holds one document; an article
  record has one `document_id`; the disclosure and the "Drawn from" line name one source.
- The prompts say "the thesis" and "the author", which is ambiguous once there are several.
- No check exists for the errors that several sources bring (§7).

## 4. Scope

In scope: ingestion of journal articles (M1); one question over several sources through the one
pipeline (M2); the article writer over several sources, with a coverage map and three new checks
(M3); optionally, the Ask view over all sources (M4).

Out of scope, recorded so it is not silently skipped: an agent or any loop; OCR; GROBID; Crossref
or any network lookup; a reranker; a database; evaluating the collection (that would need its own
plan and the researcher's own questions); writing any evaluation question.

## 5. Sprint M1 — ingest a journal article

- `documents.Document` gains `kind` (`thesis` or `article`) and the optional fields `container`
  (journal or book), `volume_issue`, `pages` and `doi`. Existing records load as `thesis`.
- `layout.py` measures the number of text columns from the horizontal positions of body blocks and
  records it in the profile with its evidence. When the profile says two columns,
  `ingest.extract_page` orders blocks by column and then by height. **Uploads only.** The built-in
  thesis's profile says one column, and the test that holds its extraction byte for byte stays.
- A "References" heading inside an article with no chapters marks what follows as reference
  apparatus, as a bibliography chapter already is in a thesis.
- `identity.py` proposes title, authors and year, and a DOI read by pattern from the first page.
  They are proposals; nothing is cited until the researcher confirms them (hard rule 6).
- `audit.py` keeps its rule (a passage's words must be on the pages it claims) and gains one
  figure: pages on which column order could not be established, flagged for the researcher.
- `upload.py`: the document id's prefix follows the kind; the Library view asks which it is.
- Footnotes: the per-document footnote map of PLAN_V6 §7 is checked on two-column pages. Where
  footnotes cannot be told apart, the article path already refuses to draft from that document.

## 6. Sprint M2 — one question, several sources, the same pipeline

- `ask.retrieve_collection(question, sources, k, per_source)` ranks each source's index with the
  existing cosine code, keeps at most `per_source` passages from each (setting
  `PER_SOURCE_PASSAGES`, proposed default 3), merges by score and numbers the handles `E1…`. It
  refuses if the indexes were built with different embedding models.
- `ask.run_query(..., collection=None)`. With a collection it calls the function above. Without
  one **nothing changes**: a test holds a single-document run record identical to today's, so the
  RAG and no-RAG conditions still differ in one variable. `evaluate.py` is not modified.
- A run record lists the document id of every passage.
- The question prompt is not changed. A collection run passes a short, hashed instruction
  (`prompts/collection_v1.md`) through the existing `instructions` argument: each passage header
  names its source; attribute each claim to that source's author by name.

## 7. Sprint M3 — the article writer over several sources

- `Workspace` holds one or more documents, each with its own filtered sources. A draft records
  `document_ids`. Record schema 5; schemas 2 to 4 still open.
- **Coverage map.** For each section brief, each source's best passages by page and score, from
  the embedding step alone (it extends the retrieval preview; no model). The researcher ticks the
  sources for the article and may narrow a section to some of them. A score is a diagnostic.
- Section prompt `article_section_v3.md`: name the author of the source in the sentence; one
  source per sentence; no "scholars agree".
- Three checks. Each **raises a sentence for the researcher; none decides** (hard rule 12):
  1. its notes resolve to two different sources (a merged claim);
  2. it names one source's author while its note resolves to another (a wrong source);
  3. it uses consensus wording such as "scholars agree" (the synthetic-consensus heuristic of
     `PLAN_V2.md` §19).
- The review view shows the source beside each passage. Notes, the source list and the disclosure
  name every source; the list is grouped by source.
- `workflows.py`, `docs/workflows.md` and the article trace gain the coverage step.
- `write_article.py`: `--document` may be given several times; `--coverage` prints the map.

## 8. Sprint M4 — Ask across sources (small, optional)

The Ask view's document picker gains "All ready sources", using M2. Each note already names its
source.

## 9. Tests (offline, a failing test first)

The model is replaced at `ask.call_model`, the embeddings at `ask.embed_texts`. PDFs are synthetic
"FIXTURE" documents built in the tests with PyMuPDF. No real article text enters the repository.

- A two-column fixture extracts in reading order; a one-column document extracts as before; the
  built-in extraction is byte-identical.
- An article's identity is never cited before it is confirmed; a DOI is a proposal.
- A single-document run record is identical before and after M2; a long source cannot take more
  than the cap; indexes from different embedding models are refused.
- Every note of a multi-source article resolves to the right source's stored provenance.
- Each of the three checks raises on a hand-built sentence and blocks nothing by itself.
- Articles recorded under schemas 2 to 4 still open.
- `index/`, `data/`, `evaluation/`, `evaluate.py` and `.env` are unchanged on every branch.

## 10. Sprints and acceptance

| Sprint | Delivers | Accepted when |
|---|---|---|
| **M0** | This plan and ADR 0013 | The researcher has read them |
| **M1** | Journal-article ingestion | Two or three real articles of the researcher's choosing pass the audit, or fail it with a stated reason, and their citations read correctly |
| **M2** | Collection retrieval on the one pipeline | A question over two sources returns passages from both, each named, and the single-document record is unchanged |
| **M3** | Multi-source article writer | An article citing two sources goes from outline to export with every note naming the right source |
| **M4** | Ask across sources | The researcher asks one question of all ready sources in the view |

Each sprint is approved separately, one pull request each.

## 11. Honest limits

- **Column detection will be calibrated on very few real articles.** Expect some to fail the
  audit; that is the audit doing its work.
- **Cosine scores from different documents are merged as if comparable.** The per-source cap is a
  blunt remedy, and three is the number one published system uses, not one measured here.
- **The three checks are patterns.** A wrong-source claim that names nobody will pass them. The
  researcher's verdict on each sentence, beside its passage and its source, remains the check.
- **Published multi-source systems leave roughly one statement in seven cited but unsupported**
  (ADR 0013). Nothing here is evidence this system does better; articles are not evaluated.
- **The question prompt still says "the thesis".** The collection instruction corrects that in
  words only; whether a model follows it is unknown until a live run.
- **Other authors' work.** Articles are processed on the researcher's own machine and quoted
  within the existing 25-word limit. Whether a given PDF may be used this way is the researcher's
  judgement, not the system's.
- **The paper.** The workshop paper is due on 15 December 2026. This plan takes none of the
  evaluation's code, but it does take the researcher's reading time in M1 and M3.

## 12. Open decisions

1. Which two or three real articles to trial in M1 (supplied privately, never committed).
2. The per-source cap (3 proposed).
3. Whether M4 is wanted.
4. Whether a DOI lookup is added later, which would send a DOI to an outside service.

## 13. Estimate

Roughly seven focused days, an estimate and not a commitment: M1 three days (column order carries
the risk), M2 one, M3 two and a half, M4 half a day.
