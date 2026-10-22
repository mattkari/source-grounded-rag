---
description: Health-check the wiki (structure + contradictions)
allowed-tools: Read, Glob, Grep, Edit, Bash(python tools/lint.py:*), Bash(python3 tools/lint.py:*), Bash(python tools/guard.py:*), Bash(python3 tools/guard.py:*)
---

1. Run `python3 tools/guard.py --wiki` (or `python`) and report any sensitive values found in `wiki/`.
2. Run `python3 tools/lint.py` and show its report.
3. Read the pages and look for **contradictions** between them (different values, steps or
   decisions for the same thing). For each one, list both pages and the conflicting claims.
   Do not fix contradictions; mark both pages `status: needs-check`.
4. List pages whose `updated` date is more than 90 days old as "possibly stale".
5. Offer fixes for broken links and orphan pages. Apply them only if the human says yes.

$ARGUMENTS
