# ADR 0003 — Automatic layout measurement: rules, cut-offs, and what the acceptance test showed

**Date:** 2026-11-14
**Status:** Proposed — taken while implementing `PLAN_V4.md`; for the researcher to accept or amend
**Context:** `PLAN_V4.md` §7 leaves the numeric cut-offs of the measurement to be "calibrated in
Sprint U0 against real theses and recorded in an ADR". This is that record. It also records where
the implementation departs from the plan as approved, because approved plans are not edited in place.

## Context

ADR 0001 made a thesis's layout a profile rather than code, and described the manual measurement
pass that produces one. `layout.py` now performs that pass. It had exactly **one real thesis** to
be calibrated against — the built-in one — plus synthetic PDFs built for the tests. Every cut-off
below should be read with that in mind.

## Decision 1 — the rules

| Profile value | Rule | Cut-off |
|---|---|---|
| Body size | The type size carrying the most characters | — |
| Header / footer band | Lines at the page edge that the neighbouring page prints again at the same height, or lone page labels. The band boundary is midway between the furthest such line and the nearest other text | Furniture on ≥ 50% of pages with text; a height counts only if furniture sits there on ≥ 2% of pages; "same height" is ± 2pt; stacked furniture lines are ≤ 1.6 line-heights apart |
| Page number | A lone roman or arabic token in a band | Accepted only if the label advances in step with the PDF page on ≥ 90% of consecutive numbered pages |
| Smallest body size | The smallest size below body that carries running prose and is not confined to the foot of the column | A size with < 5% of the characters is apparatus; a size with ≥ 80% of its blocks below the last body-size text on the page is footnote apparatus |
| Heading threshold | Body size plus one point | 1.0pt |
| Heading faces | Bold faces **of the body family** that open a block at body size | On ≥ 3 pages |
| Heading tiers | The largest recurring heading size is the chapter tier, the next the section tier | "Recurring" = on ≥ 3 pages |
| Chapter source | `running_header` if a header is printed on ≥ 50% of pages, changes at least once, and typically stays for ≥ 2 pages; else `heading` if a chapter-tier heading recurs; else none | as stated |
| Reference apparatus | Chapters whose printed title begins "Bibliography", "References", "Reference list", "Works cited" or "List of references" | — |

Two principles decide the ambiguous cases:

1. **A value that cannot be measured is null and flagged**, never defaulted (hard rule 6). No page
   number found means every citation reads `PDF p. N [VERIFY]`; no chapter structure means passages
   carry no chapter.
2. **When in doubt, invent less structure.** A missed heading costs a coarser section label. An
   invented one puts a false title on a citation. This is why bold text in a face other than the
   body family's is *not* adopted as headings; it is reported instead.

Every value is returned with its evidence (counts, positions, the rule), which the review report
shows. The cut-offs live as named constants at the top of `layout.py`.

## Decision 2 — the extractor gained three behaviours, for uploads only

- The literal `12.0` in `ingest._is_heading_span` became `layout.body_size`.
- A page number printed **in the header band** is read as the label and kept out of the chapter title.
- A document with **no chapter structure** is extracted as one run with no chapter.

The built-in thesis's profile uses none of the new paths. With its hand-measured profile the
refactored code reproduced the committed extraction, chunks and manifest byte for byte; a test
holds the per-page extraction to that on every run.

## What the acceptance test showed (PLAN_V4 §9)

`python scripts/measure_thesis.py --builtin` measures the built-in thesis and compares the result
with what is committed. Nothing is written; `index/` and `data/canonical/` are only read.

| Criterion in the plan | Result | Met? |
|---|---|---|
| Reproduce the hand profile "value for value" | 7 of 11 values identical. Both band thresholds differ numerically (58.4 vs 60.0; 775.5 vs 770.0) but fall in the same gaps and separate the same blocks. The two heading-tier thresholds differ (16/14 vs 20/15) | **No**, not literally |
| Chunks identical to `index/chunks.json` | 275 of 294 identical. Pages identical: 287 of 288 | **No** |
| Audit passes at 266/266 | 294/294 on all three checks (266 source passages + 28 reference apparatus), for both the committed index and the measured one | Yes |

The single cause of the 19 differing passages is on PDF page 262. There the hand profile gives a
14pt title and the 12pt bold heading beneath it the same heading level, so the extractor fuses them
into one section title. The measured profile gives them different levels and keeps them apart.
ADR 0001 lists "heading-merge fused a chapter title with the section beneath it" as a defect it
fixed; this is a surviving instance of it in the hand profile. The measured result is closer to the
document, but it is not what the plan asked for, so the criterion is recorded as not met.

**The committed index is unchanged and must stay so:** it is the paper's corpus.

## Findings about the built-in thesis

Measuring it automatically surfaced three things the hand calibration did not record.

1. **Its footnotes are in the index as body text.** `config.py` says the footnote apparatus is
   9–10pt and is dropped. In this thesis 213 footnotes on 213 pages are set in 11pt — the same size
   as the block quotations — each opening with a 7pt numeral at the foot of the column. The size
   threshold of 11.0 keeps the quotations and therefore the footnotes too. Footnote references can
   be retrieved and cited as if they were the author's own text. The audit does not catch this,
   because the words *are* on the page.
2. **Sub-headings set in Calibri-Bold (23 pages) are read as ordinary text.** The hand profile lists
   one heading face; the measured profile agrees and flags the other.
3. **One fused section title**, described above.

None of these is changed here. They are properties of the frozen corpus and belong in the paper's
limitations; whether to act on them is the researcher's decision.

## Departures from PLAN_V4 as approved

| Plan | What was done | Why |
|---|---|---|
| Build gate: no code until the first E1 run is recorded | Built before that run | The researcher's instruction ("approve then implement all"). The frozen index is untouched; a test and the acceptance script check its hash |
| Each sprint approved separately; U0 ends in a go / no-go | U0–U3 built in one pass | Same instruction. **The go / no-go is still owed** — see below |
| U0 trial on two or three theses the researcher chooses | Not run | No such PDFs were available. Only the built-in thesis and synthetic layouts were measured |
| §9 criteria 1 and 2 | Not met literally | See the table above |
| Open decision 3 (restart a failed embedding) | Allowed from the UI | The failure is recorded and nothing is retried automatically; starting the stage again is the researcher's own act |
| §13: image size and Pi ingest time "measured in U3" | Not measured | No Docker daemon and no Pi in the build session. The image is **not build-tested** |

## Consequences

- Automatic measurement is **untested on any real thesis other than the one it was calibrated on.**
  Until the trial is run, an uploaded thesis's review report is the only safeguard, which is what
  the "researcher decides" gate is for.
- The likeliest failures on a new thesis: a header band misplaced by unusual furniture; headings in
  a non-body face left undetected; footnotes sharing a size with quotations kept as body text (now
  flagged with a count); a thesis whose page numbers sit in the outer margin rather than a band.
- When a real thesis is measured wrongly, the fix is a change to a rule or cut-off here, with the
  measurement that justifies it — not a per-document override.
