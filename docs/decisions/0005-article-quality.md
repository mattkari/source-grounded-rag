# ADR 0005 — Making a drafted article readable without weakening its grounding

Date: 15 November 2026. Status: proposed (awaiting the researcher's approval).

## The problem

The first real draft (three sections, six notes) passed every validation check and still did not
read as an article: note numbers stood as the subjects of sentences, five "the evidence does not…"
lines sat in the body, five commentary blocks appeared in three sections and one of them changed
who acts in the source, section 3 quoted several full sentences in a row, the voice measures missed
the researcher's own, a restart lost a paid draft, and there was no command-line entry point.

## What the sources say

Each was opened and read unless marked otherwise. Quotations are from the source.

| Source | What it says | Used here for |
|---|---|---|
| Gao, L. et al., *RARR: Researching and Revising What Language Models Say, Using Language Models*, ACL 2023, arXiv 2210.08726 | Post-edits a model's output to fix unsupported content "while preserving the original output as much as possible". Measures attribution and **preservation** separately, and warns that "one can sacrifice preservation for higher attribution": an editor could reach full attribution "by simply replacing the input". Preservation is intent (human) times a character-level Levenshtein measure. | The editorial pass is judged on what it **keeps**, not only on what it produces. |
| Rashkin et al., *Measuring Attribution in Natural Language Generation Models*, Computational Linguistics 49(4), 2023, arXiv 2112.12870 | A statement is attributable to a source if a generic hearer would affirm "According to P, s". Annotation is two-stage: is the statement interpretable on its own, then is all of it attributable. It is a **human** judgement. | The researcher's verdict per note stays the measure of support. |
| Gao, T. et al., *Enabling Large Language Models to Generate Text with Citations* (ALCE), EMNLP 2023, arXiv 2305.14627 | Citation recall is per statement, citation precision per citation, both decided by an NLI model. | Why a note belongs to one statement. |
| Liu et al., *Evaluating Verifiability in Generative Search Engines*, Findings of EMNLP 2023, arXiv 2304.09848 | In the systems studied, "a mere 51.5% of generated sentences are fully supported by citations". Also: "a single in-line citation's scope is often ambiguous (e.g., a cite marker after two statements could be interpreted as either supporting both statements, or merely the final one)". | A note goes at the end of the clause it supports. |
| Min et al., *FActScore*, EMNLP 2023, arXiv 2305.14251 | Splits text into atomic facts, each "a short sentence conveying one piece of information", and scores the share supported. Precision only. The automatic estimator is close in aggregate but "is not perfect in individual judgments", and its errors mostly mark unsupported facts as supported. | Rejected as a gate (below). |
| Laban et al., *SummaC*, TACL 2022, arXiv 2111.09525; Honovich et al., *TRUE*, NAACL 2022, arXiv 2204.04991 | NLI-based consistency checks work best sentence by sentence. TRUE reports that "the best-performing metrics fail to detect subtle inconsistencies" and degrade on longer texts. | Rejected as a gate (below). |
| Laban et al., *LLMs as Factual Reasoners* (SummEdits), 2023, arXiv 2305.14540 | "the entity modification and antonym error types generally see the lowest rate of detection by models across the board". | A changed actor is the error a model check is least likely to catch. |
| Chicago Manual of Style 14.21 (16th ed.), as quoted on the publisher's own blog | "A note number should generally be placed at the end of a sentence or at the end of a clause." It follows punctuation. | Placement at the end of the clause. |
| Wikipedia, *Manual of Style* and *Citing sources* | A citation goes "close to the material it supports", usually at "the end of the clause, sentence, or paragraph", after punctuation. | Same. |
| IEEE Editorial Style Manual (a third-party copy) | Bracketed numbers sit "inside the punctuation" and may be used "as nouns: as demonstrated in [3]". | The one guide found that allows the form this ADR forbids. |
| Reuters Handbook of Journalism (a third-party copy) | "You should generally lead your story on the news, not the source", except for allegations and doubtful reports. | Claim first, note after. |

## Decisions

1. **A note marker closes the clause it supports and is never a word of the sentence.** "[5]
   states…", "according to [2]" and "as [3] shows" block the section. IEEE permits the noun form;
   it is rejected here because the article is for general readers and because a marker used as a
   subject hides who is speaking. The marker stays **before** the full stop, the convention for
   bracketed numbers; Chicago and Wikipedia put superscript numbers after it.
2. **Limits are gathered into one closing list**, "What this article does not cover", at most one
   line per section, written for a reader. Every limitation and every gap stays in the record.
3. **Commentary is off by default, one paragraph per section at most, and never auto-accepted.**
   Whether a commentary sentence is faithful cannot be decided offline, so each printed commentary
   needs the researcher's own verdict, separate from the note's. A pattern check raises sentences
   that give an act to a named agent, for the researcher to look at. It is a prompt to read, not a
   verdict (hard rule 12).
4. **A direct quotation is at most 25 words, and quotations at most one fifth of a section's
   words.** The share is this ADR's choice: enough for a phrase per paragraph, too little for a
   section built from the source's sentences.
5. **The editorial pass is optional, off by default, and kept only if it preserves.** A rewrite is
   accepted only when every paragraph carries exactly the handles it carried before, no name,
   number or transliterated term appears that the original did not have, there is no em dash, and
   the usual validation and checks of form pass. Otherwise the original stands and the rejection
   is recorded. A similarity ratio between the two texts is recorded; no threshold is set on it.
6. **Each step is saved when it finishes**, and an unfinished article is resumed from its record.

## Rejected

- **An entailment (NLI) model or atomic-fact scoring as an automatic gate.** Both need a model that
  the offline tests cannot run and that the deployment does not have (hard rule 10). The sources
  above report their weakest results on the errors that matter most here: changed entities, subtle
  inconsistencies, and unsupported facts scored as supported. A check that passes those would be
  treated as proof (hard rule 12).
- **A second model as judge of the rewrite.** The same objection, and a second opinion from the
  thing being checked.
- **A Levenshtein threshold on the rewrite.** RARR measures it; no value is known to be right for
  this text, so the number is recorded and not enforced.

## Not verified

- The Chicago Manual itself (login wall); the wording above is the publisher's blog quoting the
  16th edition. The current edition was not checked.
- The IEEE and Reuters texts were read from third-party copies, not the publishers' sites.
- AMA, AP, BBC and *Science* guidance was not reached. No rule against a citation number as a
  grammatical subject was found in any guide; decision 1 is this project's, not a cited rule.
- No primary source was found on agent or role swaps specifically; SummEdits covers changed
  entities. No paper specifically on citation-preserving paraphrase was found beyond RARR.
- Venues for RARR, ALCE, FActScore, SummaC and TRUE are as stated on arXiv, not checked against the
  proceedings. The venues of SummEdits were not checked.
- The researcher's voice profile was reported as eight checks. Two targets were given (connectives
  at 12 or more per 1,000 words; no em dashes in the body) and are built in. The other six were
  not supplied and are not invented.
