---
description: Compile uncompiled raw notes into wiki pages (guard runs first)
allowed-tools: Read, Write, Edit, Glob, Grep, Bash(python tools/guard.py:*), Bash(python3 tools/guard.py:*), Bash(python tools/lint.py:*), Bash(python3 tools/lint.py:*)
---

Follow CLAUDE.md exactly.

1. Run `python3 tools/guard.py` (use `python` if `python3` is not found).
   - If it exits non-zero, **stop**. Show the findings and tell the human to remove those
     values from the raw notes. Do not compile anything.
2. Run `python3 tools/lint.py --uncompiled`. Each line is `raw/<file> (sha <hash>) new|changed`.
   If it prints "Nothing to compile", say so and stop.
   - `new`: compile the whole note.
   - `changed`: the note was compiled before and has had text added (e.g. an Obsidian daily
     note). Read it in full, then fold only the new material into the pages.
3. Read `wiki/index.md`, then the existing pages it points to that look relevant.
4. For each uncompiled raw file, oldest first:
   - Extract systems, how-tos, decisions, defects and concepts.
   - Update existing pages where they cover the topic; create new pages only for new topics.
   - Apply the data rules: never carry a sensitive value into the wiki.
   - Mark disagreements between sources `status: needs-check`.
5. Update `wiki/index.md` (one row per page, sorted by type then page).
6. Append one entry per raw file to `wiki/log.md` with `- Source:`, `- Created:`, `- Updated:`
   and `- Withheld:` lines. The Source line must copy the hash exactly as listed in step 2:
   `- Source: raw/<file> (sha <hash>)`. Without it the note is offered for compile again.
7. Run `python3 tools/lint.py` and fix any broken links you introduced.
8. Report: files compiled, pages created, pages updated, anything withheld, anything marked
   needs-check. Keep it short.

$ARGUMENTS
