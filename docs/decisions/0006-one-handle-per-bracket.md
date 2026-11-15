# ADR 0006 — One handle per bracket, and no raw handle in print

Date: 15 November 2026. Status: proposed (awaiting the researcher's approval).

## What happened

The first two real drafts each printed an evidence handle raw. The model wrote one bracket for two
passages ("…from their proper balance [E1, E2]."), and the published `article.md` carried
"[E1, E2]" to the reader. The sentence had no resolved note at all.

Both sections passed every check. The pattern that finds a handle, `\[E(\d+)\]`, does not match a
joined bracket, so nothing inline was found; and `ask.validate` adds the model's own
`citations_used` list to what it checks, which named E1, E2 and E4, so the "nothing cited" and
"unknown handle" checks were satisfied. The renderer then left untouched what it could not resolve.

The same pattern and the same renderer serve the Ask view. None of the 12 stored answers has a
joined bracket, but nothing prevented one.

## Decision 1 — a joined bracket is a validation failure (option A)

Any bracket whose content opens like a handle and is not exactly `[E` + digits + `]` is a
**malformed handle**: `[E1, E2]`, `[E1,E2]`, `[E1, 2]`, `[E1; E2]`, `[E1-E3]`, and `[e4]`. It
fails `ask.validate` as `malformed_handle`, in `answer`, `limitations` and `ai_interpretation`
alike. In the Ask view the answer is shown as not grounded; in an article the section, frame
element or editorial rewrite is blocked or rejected with the reason, as for any other failure.

Option B, splitting `[E1, E2]` into `[E1] [E2]` before validation, was rejected:

- It rewrites model output, and the rewrite is a guess. `[E1-E3]` may mean two passages or three;
  `[E1, 2]` may mean E2 or something else.
- It would make the checks pass on text the model did not write, and the record would hold a
  payload that differs from what was returned. A malformed output is a recorded result (hard rule 9).
- A note joined in one bracket also hides which claim each passage supports, which is the thing the
  researcher's verdict is given on.

The cost of A is real: a section with one joined bracket has been paid for and is not printed.

## Decision 2 — a last guard in the renderers

Validation can be bypassed by a record written before this check existed: the two drafts on the Pi
say `validation_failures: []`. So:

- `article.assemble.block_reason` runs the malformed-handle check itself, on the text, every time
  an article is rendered. A reopened old draft is blocked, not printed.
- `ask.substitute_markers` (the Ask view, the command line and the copy text) and the assembled
  article both pass their output through `ask.scrub_handles`: any remaining bracket that opens like
  a handle, joined or simply unknown, is replaced by the fixed text `[unresolved note]`. No other
  character is changed. A reader sees that a note is missing, and never sees a handle.

The evaluators' "Technical details" section still quotes the rejected bracket inside the recorded
failure. That is its purpose, and it is not the answer.

Before this ADR an unknown single handle such as `[E9]` was also printed raw in the Ask view, by
design ("left visible"). It is now shown as `[unresolved note]`: still visible as a gap, without
the handle.

## Decision 3 — the model is told the format

A rule "one handle per bracket", with the forms that are rejected, is added to the question prompt
and to both article prompts. Prompts are versioned files and earlier ones are kept, so that an
earlier record can be traced to the text it was made with:

| Was | Now |
|---|---|
| `prompts/system_grounded_v2.md` | `prompts/system_grounded_v3.md` |
| `prompts/article_section_v1.md` | `prompts/article_section_v2.md` |
| `prompts/article_editorial_v1.md` | `prompts/article_editorial_v2.md` |

`system_grounded_v3.md` is v2 with that one rule added; a test holds it to that. **It is the prompt
of every question and of the evaluation.** No evaluation run has been recorded, so no result is
made incomparable; from the first run on, the prompt hash in each record is v3's.

## Decision 4 — em dashes in sourced prose are reported, not changed

The editorial pass rejects a rewrite with an em dash, but a section's own draft may print them (one
printed four). They are **left exactly as written and reported**: per section in `record.json`
(`em_dashes_in_print`), in the view, and on the command line.

They are not normalised at render time. A dash pair around a list ("the faculties—desire, anger,
and intellect—can…") turned into commas runs the list into the sentence; a single dash may stand
for a comma, a colon or a semicolon, and choosing among them is choosing how the sentence is read.
The instruction said not to change the meaning of any sentence, and a blind replacement cannot
promise that. They are not made a blocking failure either: it is a matter of style, and a blocked
section has been paid for. The section prompt already asks for none; the model did not comply.

## Not done

- Nothing checks that separate handles on one sentence each support it. That remains the
  researcher's verdict.
- The two drafts on the Pi are not repaired. Reopened, the affected sections are blocked; the
  sections have to be drafted again.
- No live call was made. Whether the model now writes separate brackets is not known until it is run.
