# PLAN_V6 — Article writer (Sprints W0–W2)

Status: **proposed — awaiting approval.** Nothing in this plan is implemented. Direction approved by
the researcher on 15 November 2026; this is the revision they asked for before approving the plan.
Builds on the query pipeline (`PLAN_V2.md` §11–§17) and on the document record of `PLAN_V4.md`.
Does not change `PLAN_V3.md` or `PLAN_V5.md`.

**Build gate: no code for this plan is written until the workshop paper is submitted
(15 December 2026).** The W0 trial needs the researcher's reading time, and that time belongs to the
paper until then. Nothing here touches the evaluation path or the frozen index.

## 1. Why

The system can answer a question from a thesis with every claim traced to a printed page. The same
discipline can serve a second purpose: turning what a thesis says into a readable article for a
general audience, without losing the trail back to the source. The goal is a draft the researcher
can publish on Medium after checking it — an article in which a reader can verify any claim.

This is a writing aid, not a publishing agent. It drafts; the researcher decides and publishes.

## 2. Decisions already taken (researcher, 15 November 2026)

| Topic | Decision |
|---|---|
| Where facts come from | Only the embedded collection. A topic it cannot support is refused. No web research. |
| Who picks the topic | The agent proposes several, each with its supporting chapters and pages; the researcher picks one or types their own. |
| Citations | Plain `[1]` markers in the prose and a Sources list at the end (§8). |
| The agent's own voice | Only in clearly labelled commentary. Nothing is presented as the author's view unless a page says it. |
| Documents per article | One: the thesis active in the app. |
| Checking | An uncited factual paragraph, a citation to a passage that was not supplied, or a page number written by the model blocks that section. Recorded, never silently retried. |
| Where it lives | A "Write an article" view in the web UI. Saved as Markdown in an output folder. Nothing is posted anywhere. |
| When | After the paper is submitted. |

Assumed without asking, open to objection: every article opens by naming the thesis it draws on and
keeps quotation short; articles are never part of an evaluation run.

## 3. Scope

In scope:

1. **Topic proposals** for the active thesis, with the evidence behind each.
2. **An outline** the researcher edits before anything is drafted.
3. **Section drafting** through the existing pipeline, with the same validation.
4. **The frame** of the article — title, introduction, transitions, conclusion (§6).
5. **A source filter** so that a footnote or reference entry is never presented as the thesis
   author's own view (§7).
6. **Assembly** into Markdown that Medium can import (§8).
7. **A review view** in which the researcher judges every note, and an **article record** that
   stores those verdicts (§9).
8. **A voice measurement** against the researcher's own writing (§10).

Out of scope (recorded so they are not silently skipped): web research or any source outside the
collection; articles drawing on several documents; posting to Medium or any other service; images,
SEO, click-optimised titles; rebuilding the built-in thesis's index; any use of articles in the
paper's evaluation.

## 4. How an article is made

Each step ends with something the researcher sees and can change. Nothing is drafted before the
outline is approved.

| # | Step | What happens | Who decides |
|---|---|---|---|
| 1 | Propose topics | Candidate topics for the active thesis, each with its chapters, page span and passage count | Researcher picks one, or types a topic |
| 2 | Outline | Three to six section briefs, each a plain question the section must answer | Researcher edits, reorders, deletes, approves |
| 3 | Draft sections | Each brief goes through the pipeline on filtered evidence (§5, §7); the result is validated | A section that fails is shown with its reason |
| 4 | Frame | Title, introduction, transitions and conclusion (§6) | Researcher writes them, or accepts labelled commentary |
| 5 | Review | Every note beside the passage it cites; one verdict per note (§9) | Researcher |
| 6 | Save | `output/articles/<id>/article.md` and `record.json` | Researcher edits and publishes by hand |

**Topic proposals come in two layers, kept apart.** *What the thesis covers* is built without a
model, from the chapters and sections the document itself prints, with their page spans and passage
counts. *A suggested angle* is the model's one-line wording; it is labelled as a suggestion and is
never cited, because hard rule 5 forbids citing a derived field. Reference apparatus is never
proposed as a topic, and a thin topic is shown as thin, with its count.

## 5. Sections stay on the one pipeline

A section brief is a question. It is sent to `ask.run_query` for the active `Document` and comes
back as the same validated payload an answer does.

| Answer field | In the article |
|---|---|
| `answer`, with `[En]` handles | The section's prose, with note markers |
| `evidence_sufficiency: insufficient` | The section is not written. The researcher chooses: drop it, or say the thesis does not cover it. |
| `evidence_sufficiency: partial`, `limitations` | The section is written and its limits are stated in it |
| `ai_interpretation` | **Commentary**, set apart and labelled as the article's own inference |
| `unsupported_by_evidence` | Listed for the researcher in the record; not printed |

What holds by construction, because the existing code enforces it: a page number can reach the
article only from stored provenance (`ask.page_phrase`), never from the model (hard rule 2); and a
handle that was never supplied, a sufficiency claim with nothing cited, or a page number the model
wrote is a validation failure (`ask.validate`). In an article each of these **blocks the section**.
A blocked section is never regenerated automatically (hard rule 9).

## 6. The frame: an article is not a set of answers

A title, an introduction, the sentences that carry a reader from one section to the next, and a
conclusion are what make sections into an article. **None of them is on a page of the thesis, so
none of them can be cited.** The plan therefore allows exactly two origins for each, and records
which was used:

| Element | Origin A: the researcher writes it | Origin B: generated |
|---|---|---|
| Title | Typed by the researcher. **This is the default.** | Up to three suggestions, labelled as suggestions; the researcher picks or rewrites one |
| Introduction | Typed by the researcher | Generated as **labelled commentary** |
| Transitions | Typed by the researcher | Generated as **labelled commentary**, one or two sentences each |
| Conclusion | Typed by the researcher | Generated as **labelled commentary** |

Rules for a generated frame element:

- It is commentary and is labelled as such in the article. It is the article's voice, not the
  thesis author's, and the label says so.
- It may **restate** a claim a section has already made, and then it carries that claim's existing
  note. It may **not** introduce a fact, a passage or a note that no section contains. A frame
  sentence with a new factual claim and no existing note fails validation.
- It is drafted from the validated sections only: no new retrieval. This needs one small, explicit
  addition to the pipeline — calling the same `call_model` and the same `validate` on a given list
  of already-cited passages — in the manner of the E2 switch (`PLAN_V5.md` §2). It is not a second
  generation path, and no other interface may use it.
- Text the researcher types is theirs. It is not validated or labelled, and the record marks it as
  researcher-written so the support rate (§9) is never claimed for it.

## 7. Requirement: a footnote or reference entry is never the thesis author's view

ADR 0003 found that the built-in thesis's index holds 213 footnotes as body text, because they are
set in the same type size as its block quotations. A footnote there typically cites another
writer's work. Drafted from as-is, an article would say "the author argues…" about something the
author merely cites. For general readers this is the attribution error most likely to be noticed,
and the most damaging. It is therefore a **W1 requirement, not a limit**:

> A passage, or part of a passage, that is a footnote or a reference-list entry is either excluded
> from drafting or attributed to the writer it cites. It is never presented as the thesis author's
> own view.

How, without touching the frozen index:

- **Reference-list passages** are already tagged `kind: "apparatus"` in the index. They are
  excluded from article drafting outright.
- **Footnote text inside a body passage** is not tagged; the index cannot tell it apart. W1 builds
  a **footnote map** for the document: for each page, the blocks that have a footnote's shape (they
  open with a small numeral and sit at the foot of the column — the test `layout.py` already
  applies when it counts them). The map is a derived side file. It is never written into the
  canonical extraction or the index (hard rule 7), and the evaluation never reads it.
- At drafting time the mapped footnote text is **removed from the evidence the model sees**. This is
  the default: exclusion is certain, while attributing a footnote to "the writer it cites" needs
  that writer to be identified reliably. Attribution is offered only where the footnote names its
  source unambiguously, and is an open decision (§13).
- A passage that is mostly footnote text after filtering is not used.
- **Every exclusion is counted and shown**: the article record lists how many passages were filtered
  and how many dropped, so the researcher can see what the article could not draw on.

The filter is tested against the built-in thesis: every one of the 213 footnotes ADR 0003 counted
must be found by the map, and no footnote text may appear in the evidence of a drafted section.

## 8. Output format: what Medium can actually show

Medium has no footnotes and no tables. The article file is plain Markdown that survives import:

- **Notes are plain `[1]` markers** in the prose, numbered once across the whole article.
- **A "Sources" list at the end**, one numbered line per note: author, year, chapter, section and
  printed page, from `ask.footnote`. A passage on an unnumbered page is listed as it is cited today,
  with `[VERIFY]`.
- **No tables anywhere in the article body.** Nothing in an article is laid out as a table.
- **Commentary is marked with words, not layout**: a short fixed label in plain text that survives
  import, opening every commentary passage.
- **Headings, paragraphs, short block quotations, bold and italic only.**
- **Opening attribution**: the first lines name the thesis, its author and year, using the confirmed
  identity from the document record, and say the article is drawn from it.
- **A closing line** saying the article was drafted with an AI system from the named source and
  checked by the researcher. Removable by the researcher; present by default.

(This plan uses tables; articles never do.)

## 9. Review: making "the researcher checked it" a measurement

Validation shows that every claim points at a real passage. It does not show that the passage
supports the claim. Only reading can, so the view is built to make that reading quick and to record
its result.

- **Side by side.** For each note, the review view shows the sentence that carries it and, beside
  it, the cited passage with its page reference. The passage is displayed from the index; the
  record stores its chunk id, not its text.
- **One verdict per note**: *supports*, *partly*, or *does not*. The researcher may add a short
  reason.
- **Stored in `record.json`** with the note number, the chunk id, the verdict, the time, and that
  the researcher gave it.
- **A measured support rate for every article**, as counts: notes judged *supports*, *partly* and
  *does not*, out of all notes. Notes not yet judged are counted as not judged, never as supported.
- **Status follows the verdicts.** An article is "draft" until every note has a verdict. A note
  judged *does not* keeps the article in draft until its sentence is removed or rewritten; the
  original verdict stays in the record. The saved file carries its status in its first line while
  it is a draft.
- Researcher-written frame text has no notes and is outside the rate, and the record says so.

The record also holds, per section: the brief, the model and prompt hash, the retrieved passages by
chunk id, the validated payload, every validation failure, what the source filter removed, and
whether the researcher kept the section. `output/` is ignored by git and excluded from the Docker
build context: an article may paraphrase another person's thesis.

## 10. Voice: a number behind "reads well"

The answer prompt writes in a report register ("The collection states…"). That is right for an
answer and wrong for an article. Whether drafted sections sound like the researcher is measured in
W0, not only judged by reading.

- **Reference sample.** The researcher supplies several pieces of their own published writing for
  general readers. They are the researcher's own text, kept outside git by default.
- **Measures**, computed the same way on the reference and on every draft, by plain counting with
  no model:
  - sentence length: median and spread, in words;
  - first-person rate: sentences containing a first-person pronoun, per hundred sentences;
  - connective rate: sentences opening with a connective from a fixed, published list, per hundred;
  - report-register phrases: occurrences of a fixed list ("the collection states", "the thesis
    states", "the evidence indicates"), per thousand words.
- **Reported as numbers side by side**, draft against reference, for each section and for the
  assembled article. No single "voice score" is computed.
- **What counts as close enough is set by the researcher in W0**, from the first real comparison,
  and recorded in an ADR. This plan does not invent a threshold.
- The measure decides open decision 1: if the existing prompt cannot be brought near the reference,
  a dedicated article prompt is written — a new versioned file, hashed into every article record.
- Commentary and sourced prose are measured separately, since only commentary may use the first
  person on the researcher's behalf.

These measures describe surface style. They do not measure whether the article is good, accurate
or fair, and the plan does not claim they do.

## 11. Tests (offline, a failing test first)

The model is replaced at `ask.call_model` only; the embedding provider by the offline fake.

- Topic listing comes from the index alone and never includes reference apparatus.
- A suggested angle or title is never citable and enters the article only if the researcher picks it.
- A section with an unknown handle, no citation, or a model-written page number is blocked; an
  `insufficient` section is never written as prose; a failed section is not retried.
- A generated frame element is always labelled; one that introduces a fact or note absent from the
  sections fails; researcher-written text is recorded as such.
- Footnote-shaped text never reaches the evidence shown to the model; reference-list passages are
  never used; the built-in thesis's 213 footnotes are all found; the index and canonical extraction
  are byte-for-byte unchanged afterwards.
- The article file contains `[n]` markers and a Sources list, and no table syntax anywhere.
- Every note resolves to stored provenance: no "None", no page absent from the canonical extraction.
- A verdict is stored per note; the support rate counts unjudged notes as unjudged; a *does not*
  verdict keeps the article in draft.
- Voice measures give known values on hand-written fixture text.
- The evaluation runner is untouched.

## 12. Sprints and acceptance

| Sprint | Delivers | Accepted when |
|---|---|---|
| **W0 — Trial** (command line, no UI) | Topic listing; one outline; **one assembled three-section draft with its frame**; the voice measures on that draft against the reference sample; a count of how many retrieved passages the footnote filter would touch | The researcher has read the draft **as a whole article, not section by section**, has the voice numbers beside it, and decides: go or no-go; existing prompt or a new one; who writes the frame by default |
| **W1 — Article pipeline** | Outline, sections, frame, the footnote and reference filter (§7), assembly in Medium format (§8), the record | A full article is produced offline from scripted model output with every rule of §11 held |
| **W2 — Web UI** | The "Write an article" view, including the side-by-side review (§9) | An article goes from topic to a saved, fully reviewed Markdown file with no file edited by hand, and its record shows a support rate |

Each sprint is approved separately. W0 is a trial on purpose: if the assembled draft does not read
as an article, or cannot be brought near the researcher's voice, the plan stops there.

## 13. Honest limits

- **A support rate is one reader's judgement.** It records what the researcher found, note by note.
  The rater is also the system's builder: a disclosed bias, as in `PLAN_V3.md` §9.
- **A popular register loses nuance.** The source's hedges survive only where the model keeps them
  and the researcher's verdicts catch it when it does not.
- **The footnote filter is a heuristic about shape** (hard rule 12). It is tested on one thesis. On
  an uploaded thesis with a different layout it may miss footnotes or remove body text; the record's
  counts are how the researcher finds out.
- **Excluding footnotes loses what the author put in them.** That is the price of never
  misattributing them.
- **Articles are not evaluated.** The E1 and E2 measurements describe question answering.
- **Voice measures are surface counts.** Matching them does not make a draft sound like the
  researcher; missing them shows that it does not.
- **One document per article** means no comparison across theses.

## 14. Open decisions

1. **Existing prompt or a dedicated article prompt.** Decided in W0 from the voice measures and the
   whole-article reading.
2. **Who writes the frame by default** — the researcher, or generated commentary. Decided in W0.
   The title defaults to the researcher either way.
3. **Whether topic angles use a model at all**, or the topic step is only the printed structure
   plus the researcher's own wording. Decided in W0.
4. **Footnotes: exclusion only, or attribution where the cited writer is unambiguous.** The plan
   builds exclusion; attribution is added only if the researcher asks for it after W1.
5. **The wording of the commentary label and of the closing line.**

## 15. Estimate

Roughly six focused days, stated as an estimate and not a commitment: W0 one and a half days, W1
three days (the footnote filter and the frame carry the risk), W2 one and a half days. The
researcher's time is the W0 reading, supplying the reference sample, and one approval per sprint.

## 16. Amendments after the first real draft (15 November 2026)

Added, not rewritten: the sections above stand as approved. Where an entry below differs from them,
the entry is what the code does. The reasons and the sources are in
[`docs/decisions/0005-article-quality.md`](../decisions/0005-article-quality.md).

| § above | Was | Now |
|---|---|---|
| §5, `limitations` | "The section is written and its limits are stated in it" | At most one line per section, written for a reader, gathered under one closing heading. Every limitation and gap stays in the record. |
| §5, `ai_interpretation` | Printed as commentary | Off by default; one paragraph per section at most; each printed paragraph needs the researcher's own verdict. |
| §5, what blocks a section | A validation failure, a refusal, a table | Also: a note marker used as a word of the sentence, a direct quotation over 25 words, quotation over one fifth of the section. |
| §5, the call | The question alone | The question plus a hashed prompt of rules of form (`prompts/article_section_v1.md`), through an `instructions` argument on the one pipeline. Questions and evaluation runs never pass it. |
| §9, status | "draft" until every note has a verdict | "drafting" while steps of the plan remain; then "draft"; "reviewed" also needs every printed commentary accepted. |
| §9, saving | When the draft is finished | After every section, rewrite and frame element. An unfinished article is resumed from its record. |
| §10, voice | Measured | Measured, and an optional editorial pass (`prompts/article_editorial_v1.md`) may rewrite a section for flow. It is kept only if it preserves; see ADR 0005. |
| §12 | Command line for the W0 trial only | `write_article.py`, the same pipeline and records as the web view, with a dry run. |

Further limits, added to §13:

- **The checks of form are patterns.** A marker used as a noun in a way the patterns do not list
  passes; a sound sentence that happens to match is blocked. A blocked section has been paid for.
- **The editorial checks guard what a rewrite may not add** (names, numbers, transliterated terms,
  markers moved between paragraphs). They do not show that a rewrite kept the meaning: a changed
  verb, a dropped hedge or a new lower-case claim passes them. The researcher's verdict on each
  note is still the only check of support, and it is given on the text as printed.
- **The "who acts" check on commentary is a prompt to read, not a verdict** (hard rule 12). It
  looks for a fixed list of verbs beside a capitalised name.
- **Only two of the eight checks of the researcher's voice profile are built in**, the two whose
  targets were given: connectives per thousand words, and em dashes. The connective count uses this
  project's own list, so it will not equal a rate measured with another list.
- **One reader-facing limit per section** means other limits the model stated are not printed.
- **The step in flight when a restart happens may have been charged** and is sent again on resume.

## 17. Amendments after the first published article (15 November 2026)

Added, not rewritten. Where an entry differs from the sections above, including §16, the entry is
what the code does. Reasons and sources:
[`docs/decisions/0008-checkable-articles.md`](../decisions/0008-checkable-articles.md).

| § above | Was | Now |
|---|---|---|
| §5 | A section with one cited sentence passes whole | Every sentence of section prose carries its own note. One without is held back until the researcher deletes it or keeps it as their own words. |
| §9, the verdict | One per note | One per sentence and note it carries. A per-note verdict from an earlier record is carried over to each of its sentences and marked so. |
| §9, the review | The sentence beside the passage | The sentence beside the one to three passage sentences that share most of its words, shared words in bold; the whole passage one tap away; a flag when the passage gives the claim to a named person the sentence does not name. |
| §9, corrections | Removal of a note's sentences | A sentence is edited or deleted in the view. The record keeps the original, the edit and the time; an edited sentence needs a fresh verdict. |
| §6, generated frame | Printed as labelled commentary | A suggestion from the article's own section text, shown for editing, printed without a label once the researcher uses it, and recorded as suggested by the model and accepted by the researcher. |
| §8, output | The working draft is the output | The working draft keeps its DRAFT line. The export exists only for a reviewed article: AI disclosure first, source named, compact sources, no draft line. |
| §4, outline | "What does the thesis say about …" | Also briefs by rhetorical move, from the thesis's own section titles, with no model. |
| §4, before drafting | A count of calls | Also a retrieval preview: pages and scores per brief, from the embedding step alone. |

Further limits, added to §13 and §16:

- **Sentence and note pairs are still the author's to judge.** Nothing here decides support. The
  matching chooses which passage sentences to show by shared words; a sentence that shares many
  words with a passage can still misread it, and the first article's errors were of that kind.
- **Sentences are split by pattern.** An unusual abbreviation can split one early, and the stray
  half is then held back for want of a note. The researcher edits or keeps it.
- **The reported-speech flag knows a fixed list of verbs and a capitalised name.** It misses
  attributions in other forms ("in the words of", a pronoun) and flags a name that is not a person.
- **An edit is checked for form, not for truth.** It may say anything that keeps its markers. That
  is why it needs a fresh verdict, and why the record keeps both wordings.
- **A frame suggestion is checked for what it may not add** (names, numbers, transliterated terms,
  brackets). It can still overstate. It carries no note, so nothing is judged on it: using it is
  the researcher's act, recorded as such.
- **The export says whose work the source is only if `OWNER_NAME` is set**, and decides by surname.
  Unset, it names the source and claims nothing either way.
- **Medium's rules were not read in Medium's own words** (its pages refused automated access). The
  disclosure placement follows 2024 reports of them.
- **No retrieval-score threshold is shipped.** It depends on the embedding model and has to be read
  off real questions; unset, the preview shows scores and warns of nothing.
- **A term used for two things in two sections is not detected** (the fourth error of the first
  article). A term table across sections is a proposed next step.

