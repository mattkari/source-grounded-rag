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

## Calibrated on real articles (18 November 2026)

The rules above were then run on three real, openly available articles, with the repository's
own measurement, extraction and audit. No text of theirs is in the repository; the PDFs were
read in a scratch folder and discarded. No model or embedding call was made.

| Article | Layout | What it tested |
|---|---|---|
| Devlin et al., *BERT* (arXiv:1810.04805v2) | conference, two columns, footnotes, no page numbers | reading order, a repository's stamp in the margin |
| Jumper et al., *Highly accurate protein structure prediction with AlphaFold*, Nature 596 (2021) | journal, two columns, running head, footer with page number, appended form | furniture, page numbers, line sizes |
| Piwowar et al., PLoS ONE 2(3) e308 (2007) | journal, two columns | a third layout, to see that the fixes generalise |

Reading order came out right on every page read against the PDF. Six other things were wrong.
Each is now fixed and held by a test built on a synthetic PDF that does what the real one did.

| Found | Cause | Rule now |
|---|---|---|
| **Body text was silently lost**: about 3% of one article's lines, in the middle of paragraphs | A journal justifies lines by scaling them, so "8.2pt" text is set from 8.13 to 8.37pt. Lines that rounded just below the commonest size were read as a smaller size with too little text to be prose, and dropped | A size within 5% of the body size is body text when at least 80% of its characters sit inside blocks of body text. A size that close but set apart from the body text (figure panel letters, an appended form) is not |
| The running head ("Article") became a chapter, and no footer was found | Furniture was looked for on the page before and after. A journal prints its running head on left-hand pages only and its footer on alternate sides, with a page number that changes | The next page of the same side is looked at too; a line counts as repeated when it differs only by a number at one end; and furniture on at least half the left-hand or half the right-hand pages (never fewer than three) is enough |
| Every citation read `PDF p. N [VERIFY]` | The page number shares its line with the journal's name, so it is never a lone token | A number at an end of a furniture line is the page number when it keeps a constant distance from the PDF page on at least half the pages with text. On each page only the number that equals the PDF page plus that distance is taken, so "2021" at the end of the same line is never the page |
| A form appended to the article, numbered 1 and 2, would have been cited as pages 1 and 2 of the article | Its lone numbers were read as labels | Where a distance is measured, a number that does not keep it is not a label. Those pages are cited as `PDF p. N [VERIFY]` |
| A repository's stamp, printed up the side of page 1, was proposed as the title and read as a chapter heading in the middle of the abstract | It is the largest type on the page | Text not set left to right is not read, by the measurement or the extractor |
| The proposed year was 1953 | "The last year on the page" is a work the first page cites | For an article, the latest year on the first page: nothing it cites can be later than itself |

Also changed: an article's top-level heading is cited as a section (`§ 3 Method`), not as a chapter.

### What the real articles still show wrong

These were seen and are **not** fixed. Each is a reason to read an article's first passages against
its PDF before relying on it.

- **Small type inside a sentence is dropped with the rest of the small type.** Subscripts are the
  case seen: two model names that differ only by a subscript came out as the same word twice. A
  passage can therefore read differently from the page. The audit does not catch it: every word
  that remains is on the page.
- **The title block is one long heading.** Title, authors, affiliations and the word "Abstract" are
  all set larger than body text and merge into the heading of the abstract.
- **Figures and tables leave fragments**: axis labels, a caption without its table, a formula
  reduced to a full stop.
- **A page number in the middle of a furniture line is not read** (one of the three articles). Its
  citations read `PDF p. N [VERIFY]`.
- **The proposed authors are the whole block under the title**, affiliations and addresses
  included, or nothing when the list is long. The researcher types them.
- **Three articles are not many.** All three are from the sciences. A humanities journal with long
  footnotes across the foot of both columns has not been tried.

The built-in thesis is unaffected: its extraction is still held byte for byte, and
`scripts/measure_thesis.py --builtin` reports what it reported before.
