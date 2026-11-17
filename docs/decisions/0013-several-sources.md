# ADR 0013 — Several sources: a workflow with a coverage map, not an agent

Date: 17 November 2026. Status: proposed (direction approved by the researcher; see `PLAN_V7.md`).

## The question

The researcher wants to ingest journal articles beside theses and draft an article that cites
several of them, and asked whether this should be an agent: given a topic, the model finds the
theme and adds material by itself.

## Decision

1. **A fixed workflow.** For each section, code shows which sources hold relevant passages (a
   coverage map: pages and scores from the embedding step, no model). The researcher chooses the
   sources. Sections are drafted through `ask.run_query` as now.
2. **Retrieval over several sources is one function on the one pipeline**, with a cap on passages
   per source. The single-document path, which the evaluation uses, does not change.
3. **Three pattern checks raise sentences for the researcher**: notes from two sources in one
   sentence, an author named whose source is not the one cited, and consensus wording.
4. **Ingestion stays PyMuPDF and the researcher's confirmation.** No GROBID, no Crossref.

## What was read

Figures are as the papers report them; none was reproduced here.

- **STORM** (Shao et al. 2024, arXiv:2402.14207), a fixed pipeline: citation recall 84.8% and
  precision 85.2% by an LLM judge. The commonest error was improper inferential linking; editors
  noted unrelated facts being associated.
- **PaperQA2** (Skarlinski et al. 2024, arXiv:2409.13740), an agent: 13.5% of statements in its
  generated articles were cited but unsupported. Its errors were reasoning errors and attribution
  errors, the latter claims probably supported by a *different* included source than the one cited.
  Its agent beat a fixed pipeline on open-literature search, averaging 1.26 searches a question,
  and needed three runs to average out run-to-run noise.
- **OpenScholar** (Asai et al. 2024, arXiv:2411.14199): limits retrieval to three passages per
  paper; its self-feedback loop made answers worse in about a fifth of cases.
- **A deep-research audit** (arXiv:2605.06635): links valid above 94%, factual accuracy 39–77%,
  falling as the number of tool calls rose. That conflation across sources is the cause is the
  authors' hypothesis.
- **NotebookLM**: no official account of its design or accuracy was found. One small study
  (arXiv:2509.25498; 40 responses, one annotator) describes attributed claims turned into general
  statements.
- **Anthropic, "Building effective agents"**: workflows give predictability for well-defined
  tasks; agents suit open-ended ones, at higher cost and with compounding errors.
- **PyMuPDF documentation**: reading order depends on how the PDF was made; for several columns
  the column boundaries must be worked out from block positions.
- **GROBID documentation**: header and reference extraction as a Java or Docker service.

Not found: any study that measures how often two sources are merged into one claim, or how often
a false consensus is stated; any peer-reviewed measurement of one long document crowding short
ones out of the top results. Those two risks are argued here from the error descriptions above,
not from a figure.

## Why not an agent

- An agent's advantage is discovery in open literature. Here the collection is closed, small, and
  chosen by the researcher. There is little to discover that a ranked list does not show.
- Runs are evidence (CLAUDE.md, WHY). A model that decides what to search and when to stop gives
  a different article from the same request, and the record could not say why.
- The errors that grow with several sources are wrong-source citation and merged claims. More
  autonomous steps are associated with more of them, not fewer.
- It would reverse ADR 0005 and ADR 0008 ("a workflow, not an agent") for no stated requirement.

What the researcher asked an agent for is kept as steps: finding where a topic is covered is the
coverage map; choosing the theme and what to add is the researcher's.

## Why no GROBID or Crossref

Both are infrastructure without a stated requirement (hard rule 10). GROBID is a service to run on
a Raspberry Pi; its value is parsed reference lists and citation contexts, which this plan does not
use. Crossref is a network lookup that sends a DOI outside. For a few dozen PDFs whose identity a
person confirms anyway, a proposal from the first page is enough. A DOI lookup is left as an open
decision in `PLAN_V7.md`.

## Limits

- Three passages per source is one system's choice, not a measured optimum for this collection.
- The checks are heuristics that raise; they prove nothing (hard rule 12).
- Whether a model keeps sources apart when told to is unverified until a live run.
