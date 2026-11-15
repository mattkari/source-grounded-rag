# PLAN_V6 — Article writer (Sprints W0–W2)

Status: **proposed — awaiting approval.** Nothing in this plan is implemented.
Builds on the query pipeline (`PLAN_V2.md` §11–§17) and on the document record of `PLAN_V4.md`.
Does not change `PLAN_V3.md` or `PLAN_V5.md`.

**Build gate: no code for this plan is written until the researcher's 30 evaluation questions are
written.** The workshop paper (due 15 December 2026) stays first, and nothing here touches the
evaluation path or the frozen index.

## 1. Why

The system can answer a question from a thesis with every claim traced to a printed page. The same
discipline can serve a second purpose: turning what a thesis says into a readable article for a
general audience, without losing the trail back to the source. The goal is a draft the researcher
can publish on Medium after reading it — an article in which a reader can check any claim.

This is a writing aid, not a publishing agent. It drafts; the researcher decides and publishes.

## 2. Decisions already taken (researcher interview, 15 November 2026)

| Topic | Decision |
|---|---|
| Where facts come from | Only the embedded collection. A topic the collection cannot support is refused. No web research. |
| Who picks the topic | The agent proposes several, each with its supporting chapters and pages; the researcher picks one or types their own. |
| Citations | Numbered notes in the prose and a Sources list with author, year, chapter and printed page. |
| The agent's own voice | Framing and takeaways only in clearly marked commentary. Nothing is presented as the author's view unless a page says it. |
| Documents per article | One: the thesis active in the app. |
| Checking | An uncited factual paragraph, a citation to a passage that was not supplied, or a page number written by the model blocks that section. Recorded, never silently retried. |
| Where it lives | A "Write an article" view in the web UI. Saved as Markdown in an output folder. Nothing is posted anywhere. |
| When | Plan now; build after the 30 questions are written. |

Assumed without asking, open to objection: sections are drafted through the existing pipeline, not a
second one; every article opens by naming the thesis it draws on and keeps quotation short; articles
are never part of an evaluation run.

## 3. Scope

In scope:

1. **Topic proposals** for the active thesis, with the evidence behind each.
2. **An outline** the researcher can edit before anything is drafted.
3. **Section-by-section drafting** through `ask.run_query`, with the same validation.
4. **Assembly** into one Markdown article with numbered notes and a Sources list.
5. **An article record** beside each article: what was asked, what was retrieved, what failed.
6. **A web UI view** for the four steps above.

Out of scope (recorded so they are not silently skipped): web research or any source outside the
collection; articles drawing on several documents; posting to Medium or any other service; images,
SEO, titles optimised for clicks; rewriting or "improving" a section after validation; any use of
articles in the paper's evaluation.

## 4. How an article is made

Each step ends with something the researcher sees and can change. Nothing is drafted before the
outline is approved, and no credit is spent before then beyond the topic step, if that uses a model.

| # | Step | What happens | Who decides |
|---|---|---|---|
| 1 | Propose topics | Candidate topics for the active thesis, each with its chapters, page span and number of passages (§5) | Researcher picks one, or types a topic |
| 2 | Outline | Four to six section briefs for that topic, each a plain question the section must answer | Researcher edits, reorders, deletes, approves |
| 3 | Draft | Each brief goes through `ask.run_query` on the active thesis; the result is validated as any answer is | A section that fails is shown with its reason |
| 4 | Assemble | Passing sections are joined; evidence handles become one run of note numbers; the Sources list is built from stored provenance | — |
| 5 | Save | `output/articles/<id>/article.md` and `record.json` | Researcher reads, edits, publishes by hand |

## 5. Topic proposals without inventing structure

A proposal must not be the system's opinion of what is interesting in someone's thesis presented as
fact. Two layers, kept apart:

- **What the thesis covers** — built without a model, from the index: the chapters and sections the
  document itself prints, with their printed page spans and passage counts. This is stored
  provenance and can be shown as it is.
- **A suggested angle** — a one-line phrasing of a topic, which is the model's wording. It is shown
  as a suggestion, labelled as such, and is never cited: hard rule 5 forbids citing a derived
  field. The researcher may ignore every suggestion and type their own topic.

Reference apparatus (the bibliography) is never proposed as a topic. A topic with too little
evidence behind it is shown as thin, with its passage count, not hidden.

## 6. Drafting stays on the one pipeline

A section brief is a question. It is sent to `ask.run_query` for the active `Document`, and comes
back as the same validated payload an answer does. The mapping is direct:

| Answer field | In the article |
|---|---|
| `answer`, with `[En]` handles | The section's prose, with note numbers |
| `evidence_sufficiency: insufficient` | The section is not written. The article says the thesis does not cover it, or the section is dropped — the researcher chooses. |
| `evidence_sufficiency: partial`, `limitations` | The section is written and its limits are stated in it |
| `ai_interpretation` | **Commentary**, set apart and labelled as the article's own inference, not the author's position |
| `unsupported_by_evidence` | Listed for the researcher in the record; not printed |

Consequences that hold by construction, because the existing code already enforces them:

- A page number can reach the article only from stored provenance (`ask.page_phrase`), never from
  the model (hard rule 2). A passage on an unnumbered page is cited as it is today, with `[VERIFY]`.
- A handle that was never supplied, a sufficiency claim with nothing cited, and a page number the
  model wrote are validation failures (`ask.validate`). In an article they **block the section**.
- No second generation path is added. Whether the existing prompt serves section briefs well, or a
  dedicated article prompt is needed, is the first thing Sprint W0 finds out (§10, decision 1). A
  new prompt would be a new versioned file, hashed into the article record like any other.

## 7. What the article says about itself

- **Opening attribution.** The first lines name the thesis, its author and year, and say the article
  is drawn from it. The identity is the confirmed one from the document record.
- **Notes.** One continuous numbering across sections. Each note gives author, year, chapter,
  section and printed page, as `ask.footnote` does. A reference-list passage is marked as such.
- **Commentary.** Visibly separate from sourced prose, with a fixed label.
- **A closing note** saying the article was drafted with an AI system from the named source and
  checked by the researcher. The researcher may edit or remove it; it is there by default.
- **Quotation.** Passages are paraphrased with citation; direct quotation is short. An uploaded
  thesis is another person's work, and whether an article about it may be published is the
  researcher's judgement, not the system's.

## 8. The article record

`output/articles/<id>/record.json` holds, for every section: the brief, the model and prompt hash,
the retrieved passages by chunk id, the validated payload, every validation failure, and whether
the researcher kept the section. It is what makes an article auditable after the fact and is
written whether or not the article is completed. `output/` is ignored by git and excluded from the
Docker build context: an article may paraphrase another person's thesis.

A failed section is never regenerated automatically (hard rule 9). Drafting it again is the
researcher's own, deliberate act, and both attempts stay in the record.

## 9. Tests (offline, a failing test first)

The model is replaced at `ask.call_model` only; the embedding provider by the offline fake.

- Topic listing comes from the index alone and never includes reference apparatus.
- A suggested angle is never citable and never enters the article unless the researcher picks it.
- A section with an unknown handle, no citation, or a model-written page number is blocked.
- An `insufficient` section is never written as prose.
- Note numbering is continuous and every note resolves to stored provenance; no "None", no page
  absent from the canonical extraction.
- Commentary is always labelled and never merged into sourced prose.
- An article about an uploaded thesis is attributed to that thesis, never to the built-in one.
- Nothing is drafted before the outline is approved; a failed section is not retried.
- The evaluation runner and the frozen index are untouched.

## 10. Sprints and acceptance

| Sprint | Delivers | Accepted when |
|---|---|---|
| **W0 — Trial** (command line, no UI) | Topic listing, one outline, one drafted section on the built-in thesis | The researcher has read three drafted sections and decided: go or no-go, and existing prompt or a new one |
| **W1 — Article pipeline** | Outline, drafting, assembly, record, all tested | A full article is produced offline from scripted model output, with every rule of §9 held |
| **W2 — Web UI** | The "Write an article" view | An article goes from topic to saved Markdown with no file edited by hand |

Each sprint is approved separately. W0 is a trial on purpose: if drafted sections read badly or
drift from the source, the plan stops there at the cost of one small sprint.

## 11. Honest limits

- **Checked is not the same as right.** Validation shows every claim points at a real passage. It
  does not show the passage supports the claim, or that the simplification is fair. That is the
  researcher's reading, every time.
- **A popular register loses nuance.** The source's hedges survive only where the model keeps them
  and the researcher checks. Faithful qualification is not measured for articles.
- **Articles are not evaluated.** The E1 and E2 measurements describe question answering on one
  thesis. They say nothing about article quality.
- **The built-in thesis's index holds footnotes as body text** (ADR 0003). A footnote reference could
  be cited in an article as if it were the author's prose until that is addressed.
- **One document per article** means no comparison across theses.
- **Cost.** An article is several model calls and several embedding calls. The view shows how many
  before drafting starts.

## 12. Open decisions

1. **Existing prompt or a dedicated article prompt.** Decided in W0 from real drafts.
2. **Whether the suggested angles use a model at all**, or the topic step is only the printed
   structure plus the researcher's own wording. Also decided in W0.
3. **What an `insufficient` section becomes**: dropped silently from the article, or stated
   ("the thesis does not address…"). The plan lets the researcher choose per section.
4. **Whether the closing AI-drafting note is fixed or removable.** The plan makes it removable.

## 13. Estimate

Roughly four focused days, stated as an estimate and not a commitment: W0 one day, W1 two days, W2
one day. The researcher's time is the trial reading in W0 and one approval per sprint.
