# ITCC-2026 — Speaker notes and run sheet

**Source-Grounded Research Assistant** · 20 minutes · 14 August 2026, 15:30–16:30 (online)

16 slides. Timings are cumulative and assume a 20-minute slot with questions at the end.

## Slide 1 — Source-Grounded Research Assistant

0:00–0:45 — Opening.

Good afternoon. My name is [name], from [affiliation]. Thank you to the organising committee.

Today I want to show you a research tool, and one design decision inside it that I think matters for anyone in this room who works with documents: this assistant refuses to answer when its document collection does not support an answer.

TECH CHECK before you start: share the browser window, not the whole screen. Zoom to 125–150%.

## Slide 2 — Asking a general chatbot about the literature

0:45–2:30 — The problem.

Three failures, and they compound.

(1) Fluency without sourcing. A language model produces text that has the register of scholarship without the apparatus of scholarship.

(2) Invented citations. This is the one most of us have seen — a citation with the right shape, the right author, a plausible year, and no referent.

(3) No audit trail. This is the deepest one. Even when the answer is correct, you cannot demonstrate that it is correct.

Land the bottom line slowly — it is the sentence the whole talk hangs on.

## Slide 3 — Why this matters for cooperative research

2:30–4:00 — Why this audience.

I am not presenting a general-purpose chatbot. I am presenting an instrument for working with a defined body of documents — and cooperatives are, institutionally, a disclosure problem.

Member control means nothing if members cannot verify. An audit finding that cannot point at a page is an opinion. And in our own work as researchers, a citation that does not resolve is a defect, not a stylistic choice.

So the requirement I set myself was: every sentence the system produces must be traceable to a page.

## Slide 4 — “When the collection does not contain sufficient evidence, the system 

4:00–5:00 — The commitment. Slow down here; this is the thesis of the talk.

Every other design decision follows from this one sentence.

Note the second line carefully, because it is a claim about epistemics, not about engineering: when this system refuses, it is not telling you the answer is unknowable. It is telling you that THIS collection does not contain it. Those are different statements, and conflating them would be its own kind of dishonesty.

Pause after the quote. Let it sit.

## Slide 5 — What it is

5:00–6:15 — What it is.

The corpus is deliberately small — one thesis — because the point of the prototype is the discipline of the pipeline, not the size of the library.

The important word on this slide is 'authorised'. The collection is declared in advance. The system cannot reach outside it, and it cannot quietly supplement it from what the model happens to know.

Point at the screenshot: the collection and its size are printed above the chat box, permanently.

## Slide 6 — One question, five stages

6:15–8:00 — The pipeline. Walk left to right, roughly 20 seconds per stage.

(1) Ingest: provenance is captured at extraction time, and it is never rewritten afterwards. A chunk is never allowed to straddle a chapter boundary — a passage that spans two chapters would produce a citation that is false at one end.

(2) Retrieve: cosine similarity, five passages. Deliberately simple and inspectable.

(3) Ground: this is the stage the next slide is about.

(4) Validate: blocking checks, before display.

(5) Resolve: the page numbers are produced here, by code — not by the model.

The banner matters for reproducibility: the demo you are about to see is not a separate implementation of the research tool. It is the same pipeline with a different front end.

## Slide 7 — The model never sees a page number

8:00–9:45 — The mechanism. This is the technical heart of the talk. Take your time.

On the left is literally what the generation model is given: the passage text, the chapter, the section — and no page number anywhere in its input.

The model refers to evidence by an opaque handle, E1. It cannot cite a page, because it has never been told one.

On the right, after generation, the renderer replaces that handle with a footnote number and looks the page up in the stored provenance.

So the usual failure — a fabricated page reference — is not made unlikely by better prompting. It is made structurally impossible. That distinction is the contribution.

If one idea survives this talk, make it this slide.

## Slide 8 — Three answers, not one

9:45–10:45 — Three outcomes.

Most systems have one outcome: an answer. This one has three, and the third is treated as a first-class result rather than an error path.

'Partial' matters more than it looks. Real scholarly questions are usually half-covered by any given source, and a system that has to choose between answering fully and refusing fully will overreach.

Last line: because the refusal is assembled by code from retrieval metadata, it does not depend on the model's willingness to decline. Prompt pressure cannot dissolve it.

## Slide 9 — A grounded answer

10:45–12:15 — Demo 1. Screenshots, not a live call — deliberately, so the timing is exact.

Read one sentence of the answer aloud so the room hears the register: it is careful, it attributes, and it does not overstate.

Then walk the four annotations. The one to dwell on is the third: the system volunteers the limits of its own answer. That is not politeness — it is the part a reviewer needs.

If someone asks whether the prose is the model's: yes. What is NOT the model's is every page number on that screen.

## Slide 10 — Every marker resolves to a citation

12:15–13:00 — Citations.

This is what a reader opens when they want to check a claim, and it is the reason I built the provenance layer first.

Worth stating explicitly: these are the PRINTED page numbers from the thesis, not PDF page indices. The two differ by the front matter, and a citation that quietly used the wrong one would be useless to anyone trying to verify it.

Where a page number was not printed on the source page, the system says so and flags it for human verification rather than guessing.

## Slide 11 — The refusal

13:00–14:30 — Demo 2. This is the slide I most want people to remember.

Ask the room, rhetorically: what would your usual assistant do with this question? It would answer. Fluently. With confident structure. And nothing in the output would tell you the source said nothing.

Notice the wording on screen: 'This collection does not contain sufficient evidence.' Not 'I don't know', not 'there is no research on this'. It is a claim about the collection, and it is one a reader can check.

The colour choice is deliberate and I would defend it: refusals rendered as errors teach users to treat them as malfunctions to be worked around.

## Slide 12 — Where the assistant is inferring, it says so

14:30–16:00 — Demo 3.

This question is harder than it looks: the thesis describes both models, but it does not rank them on transparency. So an honest system has to do two things at once — report what is stated, and mark what it inferred.

Read the second bullet on the screenshot aloud. Note the phrase 'which is an inference from the structures described, not the author's published position'.

For a literature review this is the difference between a usable draft and an unusable one. If the tool blended inference into attribution, every sentence would need re-checking against the source — and the tool would have saved nobody any time.

## Slide 13 — What sits behind the answer

16:00–17:15 — Evaluator view.

Everything on the left is one click below the answer. The design principle: a lecturer should never have to look at it, and an examiner should never have to ask for it.

The caption on the table is doing real work — 'similarity scores are diagnostics, not a measure of confidence'. Cosine similarity tells you a passage is lexically and semantically close. It does not tell you the answer is true, and presenting it as a percentage confidence would be a category error.

The four checks on the right run before anything is displayed. If one fails, the answer is shown with a plain warning that it is not certified grounded — because in a research instrument, a failed check is itself a finding.

## Slide 14 — Where the prototype stands

17:15–18:00 — Status. Be straightforward here; an audience of researchers respects a clear boundary between what is built and what is claimed.

Left: what runs today, end to end.

Right: say this out loud rather than skipping it. One document. English only. The retrieval is the simplest thing that works. And the comparison that would actually test my research question — the same model answering with and without retrieved evidence — is designed but not yet run.

If someone presses on effectiveness claims, this slide is your honest answer: I am presenting an instrument and its design rationale, not an evaluation result.

## Slide 15 — Where this goes — and what it could hold

18:00–19:00 — Next steps.

The first column is the one that connects back to this congress: nothing in the pipeline is specific to a law thesis. Point it at a cooperative's statutes, its audit reports, or a national cooperatives act, and the same guarantees hold — page-level citation, refusal when the corpus is silent.

The second column is the real experiment, and the design constraint on it is strict: the two conditions must differ in exactly one variable, the presence of retrieved evidence. Anything else that differs invalidates the comparison.

Third: what I would measure. Note that refusal correctness needs questions the corpus genuinely cannot answer — building that set honestly is harder than it sounds.

## Slide 16 — A system that can refuse is a system whose answers mean something.

19:00–20:00 — Close and questions.

Return to the opening: the problem was never that these systems are sometimes wrong. It is that being wrong looks exactly like being right. Grounding and refusal are how you tell the two apart.

LIKELY QUESTIONS:
· 'Does it hallucinate?' — Fabricated PAGE references are structurally impossible; the model never sees a page. Misreading a passage is still possible, which is why the verbatim source is one click away.
· 'Which model?' — Configurable. Embedding and generation are separate roles, and the index records which embedding model built it, so a mismatched model cannot query it.
· 'Can it read Turkish?' — Not yet tested; extraction is language-agnostic, embeddings are the open question. Say so plainly.
· 'Cost / can I run it?' — Runs on a laptop; the corpus is small; the index is a single file.
· 'Is it public?' — Yes, repository link on screen.
