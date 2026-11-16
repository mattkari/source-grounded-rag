# ADR 0008 — An article the author can check sentence by sentence, and publish as recorded

Date: 15 November 2026. Status: proposed (awaiting the researcher's approval).

## The problem

A clean draft (three sections, six notes, nothing blocked) was published. Checking it against the
cited pages, the author still found six errors that every automatic check had passed: a factual
misreading, two claims the source gives to a named scholar presented as the thesis's own, one
English term used for two different things, an inference turned around, and a sentence with no
note printed as sourced prose. One note covered six sentences, three of them wrong. No note was
judged in the app, the corrections were made outside it, and the record no longer matches what was
published.

"Write an article" is a workflow, not an agent: no loop, no retry, no model deciding what comes
next. This ADR keeps it so and changes what the author is given to check.

## What the sources say

Read from the papers' own text unless marked. Venues are as usually cited and were not checked.

| Source | What it says | Used for |
|---|---|---|
| Gao, Yen, Yu, Chen, *Enabling Large Language Models to Generate Text with Citations* (ALCE), arXiv 2305.14627 | "we segment LLMs' output into statements by sentence boundaries." Citation recall is "of each statement (0 or 1)"; precision is "for each citation (0 or 1)". "even the best models lack complete citation support 50% of the time" (ELI5). It notes its own gap: the algorithm "overlooks the scenario when one citation partially supports the statement." | The unit of checking is the sentence and one of its citations. *Partly* stays a verdict. |
| Rashkin, Nikolaev et al., *Measuring Attribution in Natural Language Generation Models* (AIS), arXiv 2112.12870 | Attributable if a hearer would affirm "According to P, s". Whole-output judgement "has the potential disadvantage of being coarser grained, not allowing AIS judgments at the sentence level." Annotators apply the test "strictly, without making further assumptions beyond what is conveyed in the text." | The verdict is a person's, per sentence, and strict. |
| Liu, Zhang, Liang, *Evaluating Verifiability in Generative Search Engines*, arXiv 2304.09848 | "a single in-line citation's scope is often ambiguous (e.g., a cite marker after two statements could be interpreted as either supporting both statements, or merely the final one)". "merely 51.5% of generated sentences are fully supported with citations". | A sentence without its own marker is not covered by the next one's. |
| Shao et al., *Assisting in Writing Wikipedia-like Articles From Scratch with Large Language Models* (STORM), arXiv 2402.14207 | The pre-writing stage produces an outline. "Removing the outline stage significantly deteriorates the performance across all metrics." Of unsupported sentences: "the primary issues stem from drawing improper inferences and inaccurate paraphrasing, rather than hallucinating non-existent contents." | The outline deserves help. The errors found here are the kind STORM reports. |
| University of Portland library, APA 7th edition guide to secondary sources (read through a summarising tool) | "If you use a source that was cited in another source, name the original source in your signal phrase", with "as cited in". | A claim the thesis gives to someone else keeps that person's name. |
| The Decoder and Plagiarism Today (2024), reporting Medium's distribution guidelines | AI-assisted text "needs to be disclosed at the beginning of the story, within the first two paragraphs." | The export opens with the disclosure. |

## Decisions

1. **Every sourced sentence carries its own note.** A sentence of section prose with no marker is
   not printed. The author deletes it or keeps it as their own words, recorded with origin
   "researcher".
2. **One verdict per sentence and note pair**: *supports*, *partly* or *does not*. Each sentence is
   shown beside the one to three sentences of the cited passage that share most of its words, with
   the shared words marked. The matching is plain word overlap; it chooses what to show, never what
   is true. A verdict given per note before this ADR opens as the verdict of every pair of that
   note, marked "carried over".
3. **Reported speech is raised.** When the best-matching passage sentence gives the claim to a named
   person ("X argues", "according to X", "as X claims") and the drafted sentence does not name X,
   the pair is flagged. It raises and never blocks (hard rule 12).
4. **A sentence can be edited or deleted in the view.** An edit keeps the sentence's markers, is
   checked for form, and needs a fresh verdict. The record keeps the original, the edit and the time.
5. **Export only when reviewed.** "Copy for Medium" and "Download Markdown" are disabled until every
   pair is judged, no *does not* remains and every held-back sentence is resolved. The export opens
   with the AI disclosure, has no draft banner, prints compact sources, adds no em dash of its own,
   and says plainly when the source is not by the configured owner.
6. **The frame is a suggestion.** "Suggest an introduction / conclusion" makes one call that sees
   only the article's own section text. The suggestion may add no name, number or transliterated
   term. Accepted or edited by the author, it is printed without a commentary label and recorded as
   "suggested by model, accepted by researcher".
7. **A retrieval preview before paying.** The passages a brief would draw on, with pages and scores,
   from the embedding step alone.
8. **An outline helper with no model**: brief templates by rhetorical move, filled from the
   thesis's own section titles.

## Rejected

- **An entailment model, an LLM judge, or any automatic verdict** (ADR 0005 stands). The errors
  above are the kind such checks pass. Checks here raise items; only the author accepts.
- **Blocking on the reported-speech flag.** It is a pattern over names and verbs.
- **Treating a retrieval score as confidence** (hard rule 4). The preview warns; it refuses nothing.

## Proposed next steps, not built

- A passage of the author's own writing as a voice exemplar in the editorial prompt.
- A table of terms across sections, to catch one term used for two things (error 4 above).
- An optional, ALCE-style support *suggestion* shown beside each pair, never a verdict.

## Not verified

- **Medium's rules in Medium's own words.** Its policy pages refused automated access. The
  "first two paragraphs" rule is from two 2024 reports and may have changed. No Medium text was
  found on AI summaries of another author's work; that reason for naming a non-owner source is the
  researcher's report, not a quoted rule.
- The official APA page on secondary sources (a university guide was read instead, through a
  summarising tool).
- The venues of all four papers, and the column alignment of STORM's ablation table.
- **No retrieval-score threshold for the real embedding model.** It cannot be measured offline. The
  tests show that a threshold separates in-corpus from out-of-corpus questions with the offline
  stand-in; the setting ships unset, and the preview then shows scores without a warning.
