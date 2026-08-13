# ADR 0002 — The bibliography is indexed as tagged apparatus, not excluded

**Date:** 2026-08-14
**Status:** Accepted. **Supersedes decision 4 of [ADR 0001](0001-corpus-swap-via-layout-profile.md).**

## Context

ADR 0001 excluded the bibliography from the evidence index, on the stated grounds that a reference
list would pollute retrieval and displace substantive evidence. **That justification was asserted
without measurement, and measurement disproved it.**

Bibliography chunks were built, embedded, and appended to the real index in memory, then scored
against realistic questions:

| Question type | Result |
|---|---|
| 10 substantive questions (al-ʿAdl, Nursi, qadar, Izutsu's method, …) | **0 of 50** evidence slots taken by bibliography chunks |
| Best evidence vs best bibliography score, "lexical meaning of al-ʿAdl" | 0.7202 vs 0.3658 |
| Best evidence vs best bibliography score, "Nursi on balance and order" | 0.7763 vs 0.5263 |

Dense embeddings encode a reference list as *"a list of references"*, not as its subject matter, so
displacement did not occur. Meanwhile, on questions genuinely about the thesis's sources, the
bibliography ranked **#1–#2** — and the pre-existing index answered such questions from discussion
passages that do not contain the works being asked about.

Excluding it therefore removed a real capability at no measured benefit. The project describes
itself as a literature review assistant; "which scholars does this thesis engage?" is a
literature-review question.

## Decision

The bibliography is **indexed and tagged**, not excluded. `apparatus_chapter_prefixes` replaces
`excluded_chapter_prefixes`; matching chunks carry `kind: "apparatus"` (all others `kind: "source"`).

The tag is not merely metadata — it is carried to both audiences:

- **To the model**, in the evidence block header: *"REFERENCE APPARATUS: a list of works cited, not
  the author's argument. Supports only what the thesis cites, never what it claims."*
- **To the reader**, in the citation: *"[reference list — what the thesis cites, not what it
  argues]"*, and in the web UI's `Sources:` line.

`prompts/system_grounded_v2.md` adds a *Reference apparatus* section: apparatus supports only
claims about what the thesis cites; a title is never evidence of its contents; apparatus alone
never establishes the author's position; and questions genuinely about sources are properly
answered from it. `v1` is left untouched so earlier runs stay reproducible.

## Consequences

The failure mode this guards against is **title-as-content fabrication** — mining a cited title for
substance the thesis never claimed. Verified directly: the bibliography contains *Political Islam
in Uzbekistan: Hizb ut-Tahrir al-Islami*, a topic the thesis never discusses. Asked what the thesis
concludes about it, the system refused, and reasoned explicitly that *"one passage in the collection
is reference apparatus... which could only establish what the thesis cites, not its conclusions."*

Asked which Izutsu works the thesis cites, it answered `partial`, observed that the retrieved
apparatus passage breaks off mid-entry, distinguished works *by* Izutsu from works *about* him, and
declined to enumerate bibliography entries it could not see.

Index grows from 266 to 294 chunks (28 apparatus, ~18,500 tokens).

## Caveat that may reverse this

The measurement is **dense-retrieval only**. `PLAN_V2` §8–10 specifies hybrid dense + BM25. Under
BM25 a bibliography chunk is a keyword magnet — some 700 tokens of proper nouns, titles and years —
so a query naming a cited author would match it on lexical overlap alone. The 0% displacement
result should not be assumed to survive that change. **Re-measure when hybrid retrieval lands**; if
displacement appears, the fix is retrieval-side (filtering or down-weighting `kind: "apparatus"` for
non-bibliographic questions), not re-exclusion, since the capability is now demonstrated.
