# ADR 0010 — The researcher's own prose as an example of voice in the editorial pass

Date: 16 November 2026. Status: proposed (awaiting the researcher's approval).

## The problem

The editorial pass changed little. On the first real drafts the connective rate stayed at 9.0 per
1,000 words against a target of 12 or more, and the researcher's own rate is about 22. The pass is
told to "join the sentences", but it is not shown how this researcher joins them.

## Decision

When the researcher supplies a piece of their own published prose and switches the editorial pass
on, its opening (whole sentences, about 300 words) is shown to the editor between the rules and
the draft, under the heading VOICE EXAMPLE.

- **For voice only.** The prompt (`prompts/article_editorial_v3.md`) says to take the length of the
  sentences and the way they are joined, and nothing else: no fact, name, number, term, opinion or
  turn of phrase, and no first person unless the draft has it.
- **Enforced, not trusted.** A rewrite is still checked against the draft alone: it may add no
  name, number or transliterated term the draft did not have, and must carry the same markers in
  each paragraph (ADR 0005). Content borrowed from the example fails those checks and the original
  stands. A test borrows a name and the first person from the example; both are rejected.
- **Off unless asked for.** In the view it is a tick box beside the upload of the researcher's own
  writing; on the command line, `--voice-example FILE`. It does nothing without the editorial pass.
- **The example is the researcher's and stays local.** It is kept with the plan in `record.json`,
  so an interrupted draft resumes with it; `output/` is not committed. Each rewrite's own entry
  holds only the example's word count and hash.

## What this costs

- **The example is sent to the model provider** with each section's rewrite. It should be prose the
  researcher has already published.
- About 300 more words of input per rewrite.

## Not known

- **Whether it works.** No live call has been made. The voice counts before and after each rewrite
  are already recorded, so the first real draft with an example will show whether the connective
  rate moves. If it does not, this is the thing to remove.
- A rewrite in a stronger voice may be rejected more often by the checks. That is the safe
  direction: the original stands.
