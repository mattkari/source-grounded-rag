SUPPORT TASK. This replaces the usual task of answering a question.

The EVIDENCE block holds one passage, `[E1]`. Under SENTENCE is one sentence that cites it. Say
whether the passage supports the sentence, reading strictly: would a careful reader, given only
this passage, agree "according to the passage, <the sentence>"? Do not use anything you know from
elsewhere. Do not give the benefit of the doubt.

Look in particular for: a claim the passage gives to a named person that the sentence states as the
author's own; an actor changed; a number or a scope changed; a hedge dropped; a conclusion the
passage does not draw.

Answer with the schema's fields, used like this:

- The passage supports all of the sentence: `evidence_sufficiency` "sufficient"; in `answer`, one
  sentence saying what in the passage supports it, ending with `[E1]`.
- The passage supports part of it: `evidence_sufficiency` "partial"; in `answer`, one sentence on
  what is supported, ending with `[E1]`; in `limitations`, one sentence on what is not.
- The passage does not support it: `evidence_sufficiency` "insufficient"; `answer` null; in
  `unsupported_by_evidence`, one sentence on what the sentence says that the passage does not.

Never write a page number. One marker per bracket. Leave `ai_interpretation` empty.
