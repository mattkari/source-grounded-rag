# PLAN_V5 — Sprint E2: repeated runs and the no-retrieval baseline

Status: **proposed — awaiting approval.** Jira LAB-49. Implements `PLAN_V2.md` §20 and the two items
`PLAN_V3.md` §2 deferred to E2. Named V5 because `PLAN_V4.md` is the upload plan; this is "E2".

## 1. Why

The project exists to answer one question (`PLAN_V2.md` §1): does source-grounded retrieval reduce
unsupported claims, compared with the same model answering with no retrieved evidence? E1 measures
the grounded system only, once. Without a baseline there is nothing to compare it with, and without
repeats a single run cannot be told apart from luck.

## 2. The baseline: the identical prompt, an empty evidence block

Decided by the researcher on 14 November 2026 (`PLAN_V2.md` §20.2, Option 1; §32 lists it as theirs).

| | RAG | Baseline (no-RAG) |
|---|---|---|
| Question set, model, output schema, validation | identical | identical |
| System prompt | the configured prompt | **the same file, byte for byte** (same hash) |
| Evidence block | k retrieved passages | **empty** |

**Exactly one variable differs.** It is implemented as a switch on the one pipeline,
`ask.run_query(..., retrieve_evidence=False)`: retrieval is skipped and the same `call_model` and the
same `validate` run on an empty evidence list. There is no second generation path and no baseline
prompt, because either would be a second difference (`PLAN_V2.md` §20.1).

**What this costs, stated in advance.** The prompt tells the model to answer only from the evidence
and to refuse otherwise. With no evidence, the correct behaviour under that prompt is to refuse, so
most baseline answers are expected to be `insufficient`. That is the observation Option 1 produces:
how the same instructions behave when retrieval is taken away. It does **not** show what the model
would say if simply asked. A minimally adapted prompt (Option 2) would show that, at the price of a
second variable; §20.2 suggests it as a later robustness check. It is out of scope here.

## 3. What is measured

For both conditions, with the same functions, each as `n/N`:

- **Outcomes:** answered, refused, malformed output, provider error.
- **Refusal behaviour:** refusal correctness (UNANSWERABLE + ADVERSARIAL), false refusal (ANSWERABLE).
- **Contract violations** from the same `validate()`: an evidence handle that was never supplied, a
  sufficiency claim with nothing cited, a page number written by the model.
- **Page numbers the model wrote**, new in E2. Every `p. N`, `pp. N–M` or `page N` in the model's
  text is extracted and checked against the printed labels in `data/canonical/pages.jsonl`.
  A number that is **not a printed label of the thesis is counted as a fabricated citation.**
  A number that is one is counted as a page claim and nothing more.

Not applicable to the baseline, and reported as "n/a", never as zero: retrieval recall, gold rank,
citation hit. `PLAN_V2.md` §20.3 predicts this asymmetry: the baseline cannot produce a traceable
citation at all, so that comparison is not informative on its own.

**Human rating stays primary** (`PLAN_V2.md` §20.3). Each condition gets its own rating sheet, with a
`condition` column, for answers the model did give.

## 4. Repeated runs — `evaluate.py --repeat N`

N runs of the same question set under one shared **run group id**. One record file and one summary
per run, plus a group summary giving each metric **per run, with its minimum and maximum**. No
average is printed: with N this small a mean without its spread would mislead, and the spread is
already the finding. The index is loaded once; every question is asked exactly N times; a failure is
recorded in its own run and never retried (hard rule 9).

## 5. Where a baseline answer may appear

Only in evaluation records. Every baseline record, summary and rating sheet carries
`condition: baseline_no_rag`, and the file names carry it too. A baseline answer is never passed to
the citation renderer: `QueryOutcome.rendered()` refuses it. The switch is not exposed by `ask.py`'s
command line, `main.py` or `app.py`.

## 6. Tests (offline, a failing test first)

The model is replaced at `ask.call_model` only. The two conditions' records differ only in evidence
(same model string, same prompt hash); the embedding provider is never called in the baseline; a
baseline outcome cannot be rendered; page numbers are classified against a synthetic page map;
`--repeat N` gives N files, one group id, per-run counts and a min and max that bound them.

## 7. Honest limits

- **Mostly refusals are expected in the baseline** (§2). A reader must not take "the baseline refused"
  as "the model knows nothing about the topic".
- **A page number that exists is not thereby correct.** The check catches numbers the thesis does not
  print; it cannot tell whether a real page says what the model claims. That is the rater's job.
- **Only arabic page numbers are extracted.** Roman labels are not, to avoid reading ordinary words
  as page numbers.
- **One document, about 30 questions, one rater who is also the author** (`PLAN_V3.md` §9) still
  apply to both conditions.
- **N repeats describe run-to-run variation for this model and this prompt**, not a population.
- The paper's index carries footnotes as body text (ADR 0003, on the upload branch). It affects the
  RAG condition only and belongs in the paper's limitations.

## 8. Acceptance

- [ ] `python evaluate.py --baseline no-rag` writes labelled records and a labelled summary.
- [ ] `python evaluate.py --repeat N` writes N runs and a group summary with min and max.
- [ ] Offline `pytest` green; each new test shown failing first.
- [ ] No baseline answer reachable from `app.py`, `main.py` or `ask.py`'s command line.
