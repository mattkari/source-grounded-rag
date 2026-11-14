# CLAUDE.md: Work Brain (LLM knowledge base, Karpathy pattern)

This repository is a personal work knowledge base. You (Claude Code) are its **compiler and
librarian**. The human writes rough notes; you turn them into a linked, queryable wiki.

```
raw/      = source code   (human notes, append-only)       -> written by the HUMAN only
wiki/     = executable    (compiled, linked pages)         -> written by YOU only
/lint     = test suite    (health checks)
/query    = runtime       (answers cited to wiki pages)
```

## Ownership rule (non-negotiable)

| Path | Only writer | Rule |
|---|---|---|
| `raw/` | human | Never edit, rename or delete. Read only. |
| `wiki/` | Claude | Rewrite freely. Everything here can be regenerated from `raw/`. |
| `wiki/index.md` | Claude | Updated on every compile. The retrieval entry point. |
| `wiki/log.md` | Claude | Append only. |
| `CLAUDE.md`, `tools/`, `.claude/` | human | Do not modify. |

## Data rules (this is a bank: these override everything)

1. **No client or customer data.** Names, account numbers, sort codes, IBANs, card numbers,
   addresses, dates of birth, deal or trade identifiers tied to a client.
2. **No credentials.** Passwords, tokens, keys, connection strings, cookies.
3. **No production data or production hostnames.** Test environments by role only (SIT, UAT).
4. **Colleagues are referred to by role, not name**, unless the human wrote the name in a
   decision record on purpose.
5. If a raw note contains any of the above, **do not copy it into the wiki**. Write the
   knowledge without the value (e.g. "the SIT DB user is in the team vault") and report the
   file and line to the human.
6. Never use web tools in this repo. Knowledge comes from `raw/` only.

## Page types (folders under `wiki/`)

| Folder | One page per | Example slug |
|---|---|---|
| `systems/` | service, component or environment | `payments-api.md` |
| `howto/` | repeatable procedure | `reset-sit-test-data.md` |
| `decisions/` | decision with reason (ADR-style) | `xray-three-tier-tagging.md` |
| `defects/` | recurring failure pattern and its fix | `flaky-playwright-login.md` |
| `concepts/` | idea, pattern or domain term | `iso20022-pacs008.md` |
| `qa/` | answered question filed back by /query | `how-to-run-karate-in-parallel.md` |

## Page format

Every page has YAML front matter, then these sections:

```markdown
---
title: "Payments API"
type: system            # system | howto | decision | defect | concept | qa
tags: [payments, api]
sources: ["raw/2026-10-22-standup.md"]
created: 2026-10-22
updated: 2026-10-22
status: current         # current | needs-check | superseded
---

# Payments API

2–4 sentence summary a new joiner could understand.

## Key points
- Self-contained bullets.

## Details
Plain paragraphs. Commands in code blocks.

## Related
- [[systems/xray]]: how it connects

## Sources
- raw/2026-10-22-standup.md: what this source contributed
```

Rules:
- Links are Obsidian `[[folder/slug]]` without `.md`. Every page links to at least one other page.
- File names: lowercase, hyphens.
- Prefer **updating** an existing page over creating a near-duplicate.
- If two sources disagree, keep both claims, mark `status: needs-check`, and say so in Details.
  **Never resolve a contradiction by guessing.**
- Write only what the sources say. If something is your inference, label it `(inferred)`.

## wiki/index.md format

```markdown
# Index
| Page | Type | Summary | Updated |
|---|---|---|---|
| [[systems/payments-api]] | system | REST API for payment initiation; test via Karate suite | 2026-10-22 |
```

## wiki/log.md format (append only)

```markdown
## 2026-10-22T09:15 compile
- Source: raw/2026-10-22-standup.md (sha 3f9a1c2b7d10)
- Created: [[howto/reset-sit-test-data]]
- Updated: [[systems/payments-api]]
- Withheld: raw/2026-10-22-standup.md line 14 (credential)
```

The `- Source:` lines, with the hash printed by `tools/lint.py --uncompiled`, are how `/lint` knows
which raw files are compiled. A note that grows later (an Obsidian daily note) gets a new hash
and is offered for compile again. Always write them exactly.

`raw/` may be written by the human in Obsidian at any time, including appending to today's note.
Pages in `wiki/` are rewritten by compile, so human edits there may be lost.

## Commands

| Command | What it does |
|---|---|
| `/ingest <text>` | Saves a new raw note (the only time Claude writes to `raw/`, and only new files) |
| `/compile` | Guard, then compile uncompiled raw notes into wiki pages |
| `/query <question>` | Answer from the wiki with citations; offers to file the answer back |
| `/lint` | Structural checks plus a contradiction review |
