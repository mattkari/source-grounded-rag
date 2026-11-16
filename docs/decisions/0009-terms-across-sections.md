# ADR 0009 — Terms used in more than one section are shown side by side

Date: 16 November 2026. Status: proposed (awaiting the researcher's approval).

## The problem

In the first published article one English term named the faculty of anger in one section and the
faculty of desire in another. The thesis itself uses the term both ways, on different pages. Each
sentence matched its own passage, so every check passed, and so would a verdict given sentence by
sentence (ADR 0008): the fault is between two sentences, not in either.

## Decision

The review lists the terms an article uses in two or more sections, each with every sentence that
uses it, grouped by section. The researcher reads the uses together.

- **What counts as a term**: a word carrying transliteration marks, a phrase the text puts in
  quotation marks, or a run of two or three content words. Where a shorter run occurs in exactly the
  sentences a longer one does, only the longer is shown. At most twelve are listed, the most widely
  used first.
- **It decides nothing.** It does not say that two uses differ, blocks nothing and is not needed
  for export. Whether a term means one thing is read, not computed (hard rule 12).
- **No model.** It is counting over the article's own sentences.
- The record lists each term with the ids of the sections and sentences that use it.

## Limits

- It finds repeated wording, not repeated meaning. A clash between two different terms for one
  thing, or between a term and a pronoun, is not shown.
- Runs of ordinary words that happen to recur are listed too. Twelve is a cap, not a judgement.
- Sentences in the closing list of limits are left out.
