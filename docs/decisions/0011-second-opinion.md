# ADR 0011 — A second opinion from the model, after the researcher's verdict

Date: 16 November 2026. Status: proposed (awaiting the researcher's approval).

## The question

ADR 0005 and ADR 0008 reject a model as judge: no entailment model, no LLM judge, no automatic
verdict. They leave room for a *suggestion*, and ADR 0008 lists one as a next step: an optional
reading by the model of whether a passage supports a sentence, in the manner of ALCE's per-statement
check. This ADR builds it without giving back what the earlier ones refused.

## Decision

On a sentence-and-note pair the researcher may ask the model, once, whether the cited passage
supports the sentence. The answer is *supports*, *partly* or *does not*, with one or two sentences
of reason.

- **Only after the researcher's own verdict.** The button does not exist until a verdict is saved
  for that pair. The opinion is compared with a judgement already made; it does not make it. This
  is the guard against anchoring: a reader shown the model's answer first tends to agree with it.
- **It is never a verdict.** It is recorded apart from the verdict, changes none, and counts for
  nothing: not in the support figures, not in the article's status, not in what blocks export. If
  it differs from the researcher's verdict the view says so and asks them to read again. Their
  verdict stands until they change it themselves.
- **One call, one passage, nothing retrieved.** The model is shown the sentence without its markers
  and the one passage it cites, through the same model call and the same validation
  (`ask.draft_from_evidence`, with `prompts/article_support_v1.md`, hashed into the record). An
  answer that fails validation is recorded and no opinion is shown. Nothing is asked twice.
- **It lapses with the wording.** An opinion on a sentence that has since been edited is not shown.
- **Off unless asked for, pair by pair.** There is no "check everything" button: that would be an
  automatic pass by another name, and a cost the researcher did not choose.

## Why this is not an LLM judge

A judge decides. This decides nothing: remove every opinion from a record and the article's status,
its support figures and its export are unchanged. It is a second reader the researcher can consult
after reading, and overrule in silence.

## Limits

- **Its misses are the dangerous ones.** The sources in ADR 0005 report that models most often fail
  to notice a changed entity or a subtle inconsistency, and mark unsupported text as supported. An
  opinion of *supports* is weak evidence; *does not* or *partly* is the useful signal. The view does
  not say this in so many words yet.
- **It is the same model that wrote the sentence**, unless the configuration is changed between
  drafting and reviewing. Agreement between the two is not independent confirmation.
- **No live call has been made.** Whether its readings are any good on this thesis is unknown until
  it is tried, and the place to try it is the six errors already found by hand.
- It costs one model call per pair asked.
