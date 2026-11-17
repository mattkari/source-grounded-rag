# ADR 0015 — Ingesting journal articles: columns, reference lists and identity

Date: 17 November 2026. Status: proposed (taken while implementing `PLAN_V7.md` §5, Sprint M1).
Extends ADR 0003, which gives the measurement rules for a thesis.

## Context

`PLAN_V4.md` took theses only. `PLAN_V7.md` §5 adds journal articles and book chapters with a text
layer, in one or two columns. The plan left the rules and their cut-offs to the sprint. They were
calibrated on **synthetic two-column PDFs only**. No real article has been through them yet.

## Decision 1 — the rules

| What | Rule | Cut-off |
|---|---|---|
| Columns | Two, if enough pages set blocks of body-size prose side by side: one ends before the other begins, and they overlap in height | on ≥ 50% of pages with body text; a block counts as prose at ≥ 80 characters |
| Where they divide | Midway between the right edge of the left blocks and the left edge of the right ones; the document's value is the median over its pages | — |
| Reading order | A block that lies across the division splits the page into bands; within a band, the left column to its foot, then the right | "lies across" = reaches ≥ 6pt past the division on both sides |
| Footnotes | A footnote sits below the last body text **of its own column** | as ADR 0003 otherwise |
| Reference list | In a document with no chapters, a section whose printed title begins "References", "Bibliography", "Reference list", "Works cited" or "List of references" is reference apparatus | — |
| Identity | Title: the largest text on the first page. Authors: the short block under it. Year: the last one printed on that page. DOI: read by its printed shape | authors block ≤ 200 characters |

PyMuPDF gives no reading order for columns; its documentation says the boundaries must be worked
out from block positions. That is what the rule does, and nothing else: no model, no guess at what
the text means.

## Decision 2 — what is raised, and what is not decided

- **A page whose order cannot be established is reported, not refused.** That is a page where a
  block lies across the division while other text sits beside it, or where text sits side by side
  without dividing at one place (three columns, a table set as text). The audit lists those pages
  and tells the researcher to read their passages against the PDF before citing. It is not a hard
  stop: the words of such a passage are on the pages it claims, so its citation is not false. Its
  order may be. The researcher decides (hard rule 12).
- **Identity is proposed, never adopted.** Nothing is cited until the researcher confirms it. The
  journal, volume, page range and DOI are the researcher's entries; none is looked up. A DOI is
  checked for shape only.
- **No chapter is invented.** An article is one run with sections; a citation gives the section
  and the printed page.

## Decision 3 — what did not change

- The built-in thesis's profile says one column. Its extraction is held byte for byte by the same
  test as before, and `scripts/measure_thesis.py --builtin` reports exactly what ADR 0003 records.
- A thesis is measured and extracted as before. The reference-list rule applies only to a document
  that prints no chapters.
- Profiles, records and audits saved before this sprint still load: a missing kind is a thesis.

## Limits

- **Calibrated on synthetic PDFs.** Real journals differ: drop capitals, figures and tables that
  interrupt a column, footnotes running across the foot of both columns, a first page with a
  single-column abstract box. Expect some to be read wrongly. The unclear-pages list catches the
  cases with a block across the division; it does not catch a column misread for another reason.
- **The existing audit cannot see a wrong order.** It proves each passage's words are on its
  pages. Two columns read across would pass it. This is why the reading-order rule is tested on
  its own and why the first real articles must be read against their PDFs.
- **The title block of an article becomes a section heading**, sometimes with the authors' line
  joined to it, because both are set larger than body text. A citation from the first page may
  name that as its section. It is what the page prints, but it reads oddly.
- **Small type that is not a footnote** (affiliations, a DOI line) can keep a real footnote size
  from being recognised in a short article, since the rule looks at where a size mostly sits.
- **A page number that shares a line with the running header** is read as the label, but the
  audit's "printed on its own page" check may count it as failing. That check counts; it does not
  block.
- Three or more columns are not supported. Such pages are flagged.
