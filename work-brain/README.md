# Work Brain: Karpathy-style LLM knowledge base for Claude Code

> **New here?** Follow [`SETUP_WITH_CLAUDE_CODE.md`](SETUP_WITH_CLAUDE_CODE.md): copy-paste prompts that let Claude Code set it up and test it.

You write rough notes. Claude Code compiles them into a linked wiki and answers questions from
it, citing the pages it used. There's no vector database, no background jobs and nothing to
install beyond Python and Claude Code.

```
raw/   your notes (append-only)  ->  /compile  ->  wiki/ (linked pages + index.md)
                                                  /query   answers cited to pages
                                                  /lint    health checks
```

## Before you use it at work (do this first)

1. **Use only your bank-approved Claude Code**, through the enterprise login or Amazon
   Bedrock, never a personal account. Check with `claude` → `/status`.
2. **Put the folder only where your team allows**, such as your work laptop or an internal
   GitLab repo. Never use personal GitHub or a personal cloud drive.
3. **Never paste client data, credentials, production details or colleagues' personal data.**
   `tools/guard.py` blocks common patterns, but it's a safety net, not a guarantee.
4. If you're unsure whether this is allowed, ask your line manager or the data-protection
   team before your first note.

## Set up (5 minutes)

```bash
# 1. copy this folder to your work machine and open it
cd work-brain
git init && git add -A && git commit -m "work brain skeleton"   # optional, internal remote only

# 2. check python (stdlib only, 3.8+)
python3 --version        # Windows: python --version

# 3. open Claude Code here once and accept the trust prompt
claude
```

In IntelliJ or VS Code, open the folder and use the Claude Code panel or terminal. The
commands are the same.
To browse the wiki, use **Obsidian → Open folder as vault → work-brain/wiki**.
**Vault in OneDrive?** Follow `OBSIDIAN_ONEDRIVE_SETUP.md`: put `work-brain` inside your vault
and point Obsidian's daily notes at `work-brain/raw`.

## Daily use

| When | Do |
|---|---|
| You learn something | `/ingest <rough note>`, or create `raw/YYYY-MM-DD-topic.md` yourself |
| End of day or week | `/compile` |
| You need an answer | `/query how do we reset SIT test data?` |
| Weekly | `/lint` |

**Good notes:** fixes to recurring failures, why something was decided, setup gotchas, how a
service is tested, commands you'll forget.

## How it protects you

- `/compile` runs `tools/guard.py` first and **stops** if a note has a password, token, key,
  card number, sort code, IBAN, email or National Insurance number. It shows the file and line
  but never the value.
- Claude can't edit `raw/`, `CLAUDE.md`, `tools/` or `.claude/`, and web tools are switched
  off (`.claude/settings.json`). New notes are created by `tools/new_note.py`, which refuses to
  overwrite an existing file.
- When two notes disagree, both pages are marked `status: needs-check`; Claude doesn't guess
  which is right. Anything Claude inferred is labelled `(inferred)`.
- `/query` says "The wiki does not cover this" rather than answering from general knowledge.

False positive in the guard? Add a regex for that line to `tools/guard-allow.txt`.

## Files

| Path | Purpose |
|---|---|
| `CLAUDE.md` | The schema: ownership, data rules, page format |
| `.claude/commands/` | `/ingest`, `/compile`, `/query`, `/lint` |
| `.claude/settings.json` | Permissions: read all, write `wiki/` only, no web |
| `tools/guard.py` | Sensitive-data scanner (exit 1 = stop) |
| `tools/lint.py` | Broken links, orphans, uncompiled notes, missing front matter |
| `tools/new_note.py` | Creates raw notes and refuses to overwrite |
| `wiki/index.md`, `wiki/log.md` | Catalogue and build log |

## Limits

- Index-guided retrieval suits up to a few hundred pages. Beyond that, add search.
- Compiled pages are summaries. Check anything important against the source or the code.
- The guard matches patterns. It can't recognise a client name or a production hostname, so
  those depend on you and on the data rules in `CLAUDE.md`.
