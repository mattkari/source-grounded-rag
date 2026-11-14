---
description: Answer a question from the wiki, cited to pages
allowed-tools: Read, Glob, Grep, Write, Edit
---

Question: $ARGUMENTS

Follow CLAUDE.md.

1. Read `wiki/index.md` first. Pick the 3–10 pages most likely to answer the question.
2. Read those pages in full. Use `raw/` only if the wiki is silent, and say so.
3. Answer in plain language. After each claim, cite the page as `[[folder/slug]]`.
4. If the wiki does not contain the answer, say **"The wiki does not cover this"** and name the
   closest pages. Do not answer from general knowledge without labelling it `(not from wiki)`.
5. If any cited page has `status: needs-check`, say so.
6. End by asking: "File this answer to wiki/qa/? (yes/no)". If the human says yes, write the
   `qa/` page, add it to `wiki/index.md`, and append a `query` entry to `wiki/log.md`.
