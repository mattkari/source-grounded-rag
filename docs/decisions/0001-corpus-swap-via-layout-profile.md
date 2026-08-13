# ADR 0001 — Swapping the corpus is a layout profile, not a code edit

**Date:** 2026-08-13
**Status:** Accepted
**Context:** Replacing the demo corpus; taken between `PLAN_V2.md` and the next plan.

## Context

The demo corpus was one doctoral thesis (Sönmez 2014). Replacing it exposed how much of the
pipeline was tied to that one PDF. The constants at the top of `ingest.py` were explicitly
"measured from this document": body type size, the y-bands separating running header and page
footer from body text, which fonts mark a heading, and the size thresholds for heading levels.

Two further documents were measured to test how general those values are:

| | Sönmez 2014 | Leung 2019 | Karimov 2017 |
|---|---|---|---|
| Chapter carried by | running header | 24pt chapter heading | running header |
| Printed page number at | y≈782 | y=780 | y=794 |
| Body / apparatus | 12pt / 9.8pt | 12pt / 10pt | 12pt / 9–10pt |
| Heading faces | Calibri-Bold | Garamond-Bold | TimesNewRomanPS-BoldMT |
| PDF bookmarks | — | none | 122 |

Not one of these values is shared by all three. Dropping a new PDF into the unmodified pipeline
resolved **0 of 369** printed page numbers for Leung and found **0** chapters, because that thesis
prints no running header at all. Every citation would have been unusable.

## Decision

1. **The measured constants move to a layout profile in `config.py`**, beside the document
   identity. `ingest.py` keeps only document-independent logic. Swapping the corpus is then a
   settings change plus a measurement run.

2. **`chapter_source` selects which printed feature carries the chapter** — `running_header` or
   `heading`. Both read structure the document itself prints. Neither infers a chapter that is not
   there, which keeps hard rule 6 intact. A third source (the PDF bookmark tree) is *not*
   implemented: no corpus in hand needs it, and hard rule 10 forbids speculative infrastructure.

3. **Chapter runs are built from page slices, not whole pages.** A chapter opening part-way down a
   page splits that page, so hard rule 8 — no chunk crosses a chapter boundary — holds by
   construction rather than by luck of layout.

4. **Reference apparatus is excluded from evidence** via `excluded_chapter_prefixes`. A
   bibliography is not a source claim (hard rule 5), and indexing one surfaces reference lists as
   quotable evidence. Excluded material is still extracted into the canonical record and is listed
   in the manifest with its reason — dropped from evidence, never silently discarded.

## Consequences

Calibrating a new document is a measurement pass (font/size census, band analysis, dry run against
the real extractor) followed by editing one dataclass. The measurement is not optional: the failure
mode is silent and total, and it is invisible without checking, because extraction still "succeeds"
and simply produces citations with no pages.

The manifest now records `chapter_source`, the chapter list, everything excluded from evidence, and
any page carrying text that yielded no body text — the last of these because a full-page table set
at footnote size is a real content gap, and a gap that is recorded is a research finding while a
gap that is silent is a defect.

Three latent defects surfaced during calibration and were fixed: the caption filter matched any
heading beginning `"Table "` (swallowing `"Table of contents"`), heading-merge fused a chapter
title with the section beneath it whenever both were pure heading lines, and pages with text but no
body text were indistinguishable from blank pages.

## Verification

Provenance is audited against the PDF itself rather than against the pipeline that produced it: for
every chunk, the stored page label must equal the label actually printed on that page, and every
word of the chunk must appear on the pages it claims. Both corpora pass at 100% (Leung 207/207,
Karimov 266/266).
