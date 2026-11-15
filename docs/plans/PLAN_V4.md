# PLAN_V4 — Upload and ingest another thesis (Sprints U0–U3)

Status: **proposed — awaiting approval.** Nothing in this plan is implemented.
Supersedes nothing. Builds on `PLAN_V2.md` §4–§7 and §11 (ingestion, chunking, provenance) and on
ADR 0001 (the layout profile). Does not change `PLAN_V3.md`.

**Build gate: no code for this plan is written until the first Sprint E1 evaluation run is recorded.**
The workshop paper (due 15 December 2026) rests on that run, and nothing here may disturb it.

## 1. Why

Today the system answers questions about exactly one thesis. Making it answer about another one is
a manual job: someone measures the new PDF by hand and edits `config.py`. ADR 0001 records what
happens when that step is skipped: a second thesis dropped into the unmodified pipeline resolved
**0 of 369** printed page numbers and found **0** chapters, while extraction still "succeeded".

The goal is that the researcher uploads a thesis PDF in the web UI and, after reviewing a report,
can query it with the same grounding guarantees as the original. The upload button is the small
part. The real work is **automating the measurement step and making its result checkable**.

## 2. Decisions already taken (researcher interview, 14 November 2026)

| Topic | Decision |
|---|---|
| Scope | One active thesis at a time. Each question searches only the active one. |
| Who uploads | The researcher only, through the existing Streamlit app. No login. |
| Document types | Theses with a text layer. No journal articles, books or scanned PDFs in this plan. |
| Quality gate | The system measures and audits; the researcher reads the report and approves or rejects. No fixed pass mark. |
| Unresolved pages | Cited as `PDF p. N [VERIFY]`, as today. Never guessed. |
| Identity | The system proposes author, year and title; nothing is cited until the researcher confirms. |
| Where it runs | On the Raspberry Pi, inside the app. |
| The original thesis | Frozen, read-only, the default document, and the only corpus the evaluation runs against. |
| Trust in uploads | Audit report only. An upload is "ingested and audited", never "evaluated". |
| Retention | PDF, extraction and index kept in a private folder; a remove button deletes all three. Nothing uploaded is committed. |
| Timing | Plan now; build after the first E1 run. |

Assumed without asking, open to objection: uploads use the embedding model already in config; the
app shows an estimated embedding cost and waits before spending; and the original thesis is the
acceptance test for the automatic measurement (§9).

## 3. Scope

In scope:

1. A **measurement module** that derives a layout profile from a PDF and says how it reached each value.
2. A **provenance audit** that checks an extraction against the PDF itself, committed and tested.
3. A **document record** per thesis: its own profile, identity, extraction, index and audit.
4. A small refactor so the pipeline takes its document from that record instead of from one global.
5. **Web UI**: upload, review, confirm identity, approve, switch the active document, remove.
6. **Deployment**: the Pi image gains the ingestion dependencies and a mounted library folder.

Out of scope (recorded so they are not silently skipped): searching several documents at once;
journal articles and two-column layouts; OCR; other users, login and quotas; a scored evaluation
of uploaded theses; using PDF bookmarks as a chapter source; any database.

## 4. Two findings from reading the code

These shape the plan and were not known before it was written.

1. **The provenance audit is not in the repository.** ADR 0001 reports 266/266 for the current
   thesis, but no audit script is committed. The gate in this plan depends on that audit, so it
   must first exist as tested code. Until then the 266/266 figure cannot be reproduced from `main`.
2. **One layout value is still hard-coded.** `ingest._is_heading_span` compares against a literal
   `12.0` for body-size bold headings. It is correct for the current thesis and would be wrong for
   one set in 11pt. It moves into the profile.

## 5. The document record

Each uploaded thesis gets one folder. Plain files, no database (hard rule 10).

```
library/<document_id>/
  source.pdf            the upload, byte for byte
  record.json           state, identity, layout profile, and how each value was obtained
  canonical/pages.jsonl per-page extraction — immutable once written (hard rule 7)
  audit.json            the audit result the researcher approved or rejected
  index/                vectors.npy, chunks.json, manifest.json — same shape as today
```

- `document_id` is derived from the SHA-256 of the PDF bytes, so the same file uploaded twice is
  recognised and never ingested twice under two names.
- `library/` is set by one config value, lives on a mounted volume, and is ignored by git and by
  the Docker build context. Uploaded works are never committed and never baked into an image.
- The original thesis is **not** moved. Its profile stays in `config.py` and its index in `index/`.
  It appears in the app as the default document and cannot be removed or re-ingested from the UI.

## 6. What happens to an upload

Each stage writes its outcome to `record.json`. A failure is a recorded state with a reason, never
a silent retry (hard rule 9). Nothing is embedded, and no credit is spent, before approval.

| # | Stage | What it does | Stops when |
|---|---|---|---|
| 1 | Receive | Stores the PDF, computes its hash | The file is not a PDF, is encrypted, or was already ingested |
| 2 | Pre-flight | Counts pages and checks for a text layer | There is no text layer (a scan) — out of scope, said plainly |
| 3 | Measure | Derives the layout profile (§7) | — (unknown values are left null and flagged) |
| 4 | Dry run | Runs the real extractor and chunker with that profile | — |
| 5 | Audit | Checks the result against the PDF (§8) | — |
| 6 | Identity | Proposes author, year, title for confirmation (§10) | — |
| 7 | **Review** | Shows the report; the researcher approves or rejects | Rejected: nothing is indexed; the record keeps the reason |
| 8 | Cost | Shows token count and estimated embedding cost | The researcher declines |
| 9 | Index | Embeds and writes the index | Provider error — recorded; the researcher may start the stage again |
| 10 | Ready | The thesis can be made the active document | — |

## 7. Automatic measurement

The module reproduces, in code, the manual pass ADR 0001 describes: a font and size census, a band
analysis, and a dry run. It reads only what the document prints.

| Profile value | How it is measured |
|---|---|
| Body type size | The size carrying most of the text on body pages |
| Footnote / apparatus size | Smaller sizes that recur at the foot of the text column |
| Header band, footer band | Vertical positions where short text recurs page after page, above and below the body |
| Printed page number | A roman or arabic token at a stable position in a band, accepted only if it forms a consistent sequence across pages |
| Heading faces and size tiers | Bold faces at or above body size, grouped into chapter / section / finer by size |
| Chapter source | `running_header` if a header recurs and changes only at chapter boundaries; otherwise `heading` |
| Reference apparatus | Chapters whose printed title marks them as a bibliography or reference list |

Rules:

- Every value is stored **with its evidence** (how many pages, how many characters, which
  positions), so the report can show why a value was chosen.
- A value that cannot be determined is **null and flagged**, never defaulted (hard rule 6).
- The numeric cut-offs these rules need ("recurs", "consistent", "most") are **not fixed in this
  plan**. They are calibrated in Sprint U0 against real theses and recorded in an ADR with the
  measurements that justify them.

## 8. The audit and the report

The audit checks the extraction **against the PDF, not against the pipeline that produced it**:

- For every chunk, the stored page label equals the label printed on that page.
- Every word of every chunk appears on the pages the chunk claims.
- No chunk crosses a chapter boundary (hard rule 8).

The report shown at Review states, as counts and never as a score:

- pages in the PDF; pages with body text; pages with a printed number; pages without one (listed);
- pages that carry text but yielded no body text (listed — typically full-page tables);
- chapters found, by name, and which printed feature carried them;
- chunks passing each audit check as `n/N`, with every failing chunk listed;
- profile values left null, and what each costs (for example: no page number means every
  citation of that thesis reads `PDF p. N [VERIFY]`).

There is no pass mark. The researcher decides (the AI analyses, the researcher decides), and a
heuristic is not treated as proof (hard rule 12). Three conditions are not judgement calls and stop
the upload outright: no text layer, an encrypted file, or an audit in which a chunk's words are not
on its claimed pages. The last would make citations false, which no approval can waive.

## 9. Acceptance test: the original thesis

The automatic measurement is run on the original thesis PDF **in a scratch folder**. It must:

1. reproduce the hand-measured profile in `config.py`, value for value;
2. produce chunks identical to the committed `index/chunks.json`;
3. pass the audit at 266/266.

The committed `index/` is never written to. Its `corpus_text_sha256` before and after is part of
the test. The second calibrated thesis in ADR 0001 (Leung 2019) is the known-answer case for
`chapter_source: heading`. The Task Log places it on a branch that is not on the remote today, so
using it depends on the researcher still having the PDF and its measured values.

## 10. Identity

- The proposal comes from the title page by layout rules only (the largest text, the lines around
  it, a four-digit year). **No model call** in this plan: the step stays deterministic and testable.
- PDF metadata is shown as a hint and labelled unreliable. The current thesis's metadata names a
  second author inherited from a template; that is the standing reason.
- Any field the rules cannot read is left blank for the researcher to type.
- The record stores who confirmed the identity and when. Until it is confirmed, the document
  cannot be indexed, so an unconfirmed author or year can never appear in a citation.

## 11. Pipeline change: the document comes from a record

Today `ingest.py`, `ask.py`, `app.py` and `main.py` read the document's identity, layout and index
path from the single global `settings`. This sprint introduces one small object carrying those
three things, passed in explicitly. The built-in thesis's object is built from `config.py`.

- `ask.run_query()` remains the one pipeline. No second retrieval, generation, validation or
  citation path is added.
- **With the default document, behaviour is unchanged**: the whole E1 offline suite passes without
  edits, and an answer rendered from a recorded run is byte-identical before and after.
- `evaluate.py` and `scripts/check_gold.py` stay pinned to the default document. An evaluation of
  an uploaded thesis is out of scope and the runner will say so if asked.
- Run records already carry `document_id`. History is shown per document, as `app.py` does today.

## 12. Web UI

- **Document picker** in the sidebar: the default thesis first, then approved uploads.
- **Upload** box, then a page that walks the stages of §6, showing each outcome as it is recorded.
- **Review** page: the report of §8, the measured profile with its evidence, the identity form,
  and Approve / Reject.
- **Cost** confirmation before embedding.
- **Remove** on each upload, with a confirmation. It deletes the PDF, the extraction and the index.
  Run records are kept; `runs.py` already reports their citations as unresolvable.
- Every uploaded thesis is labelled **"ingested and audited — not evaluated"** wherever it is active.

## 13. Deployment on the Pi

- The image gains the two ingestion dependencies (`pymupdf`, `tiktoken`), pinned. This reverses a
  deliberate choice ("a deployed container never re-ingests"); the requirement is now stated, so
  hard rule 10 is met. The image will be larger; by how much is measured in U3, not promised here.
- `library/` is bind-mounted, like `runs/`, so uploads survive a rebuild.
- The app stays bound to loopback with no authentication. Upload is single-user by design, and
  exposing the app to a network would now also expose the ability to spend embedding credit.
- How long a full ingest takes on the Pi is unknown. It is measured in U0 before the UI is built.

## 14. Tests (offline, red-first, as in E1)

- **Measurement**: synthetic PDFs generated in the test with known sizes, bands, page-number
  positions and chapter sources; the measured profile must match exactly. Synthetic text only.
- **Audit**: planted defects (a wrong page label, a word moved to another page, a chunk across two
  chapters) must each be reported.
- **Stages**: each stop condition of §6; nothing is embedded before approval; a declined cost
  spends nothing.
- **Identity**: an unconfirmed document cannot be indexed or cited.
- **Removal**: all three artefacts are gone; the default document cannot be removed.
- **No regression**: the E1 suite unchanged and green; the default index hash unchanged.
- No live model or embedding call, no API key, no thesis text in the repository. Every test is
  shown failing against a deliberately broken implementation before it is trusted.

## 15. Sprints and acceptance

| Sprint | Delivers | Accepted when |
|---|---|---|
| **U0 — Measure and audit** (command line only) | The measurement module, the audit, a trial report | §9 passes on the original thesis; the trial has run on two or three theses the researcher chose; the researcher decides go / no-go for the rest |
| **U1 — Document record** | The refactor of §11, no new behaviour | E1 suite green without edits; default index hash unchanged |
| **U2 — Upload and review** | The UI of §12 and the stages of §6 | A thesis goes from upload to answered question with no file edited by hand; a rejected thesis leaves no index |
| **U3 — Pi deployment** | The image and volume of §13, removal | Ingest and query work on the Pi after a container rebuild; removal leaves nothing behind |

Each sprint is approved separately. U0 is deliberately a **trial**: if automatic measurement does
not hold up on real theses, the plan stops there and the result is written up, at the cost of one
sprint and with no UI built on a weak foundation.

## 16. Honest limits

- **Layout variety is the real risk.** Three theses have been measured by hand and no two share a
  layout value. Automatic measurement may fail on a share of theses that is unknown until U0.
- **A thesis with no printed page numbers** can be ingested but every citation of it will read
  `PDF p. N [VERIFY]`. That is honest, and much less useful.
- **An upload is not evaluated.** The audit shows the extraction is faithful to the PDF. It says
  nothing about whether answers are correct, complete or well attributed.
- **Copyright.** Uploaded theses stay on the researcher's own machine and are not redistributed.
  Whether a given thesis may be processed this way is the researcher's judgement, not the system's.
- **The paper is not affected**, provided the build gate at the top of this plan is kept.

## 17. Open decisions

1. **The one stop that approval cannot waive** (§8): an audit in which a chunk's words are not on
   its claimed pages. The interview decision was "show the report, I decide" with no pass mark.
   This plan adds that single exception because such a citation would be false. The researcher may
   strike it.
2. Whether the trial in U0 includes the Leung thesis (needs the PDF).
3. Which two or three further theses the researcher wants in the trial.
4. Whether a failed embedding stage may be restarted from the UI, or only by uploading again.

## 18. Estimate

Roughly six focused days, stated as an estimate and not a commitment: U0 two days (it carries the
risk), U1 one day, U2 two days, U3 one day. The researcher's time is the trial review in U0 and
one approval per sprint.
