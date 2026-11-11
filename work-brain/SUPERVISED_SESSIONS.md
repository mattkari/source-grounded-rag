# Supervised sessions: one orchestrator, two specialist coders

This guide adds a **supervisor** to the work brain. You already run three Claude Code sessions:

| # | Where it runs | Role | Works in |
|---|---|---|---|
| 1 | Standalone PowerShell | **Orchestrator / supervisor** | `work-brain` |
| 2 | VS Code or IntelliJ terminal | **API coder** (Karate) | the API test repo |
| 3 | IntelliJ terminal | **UI coder** (Playwright, Spring Boot) | the UI test repo |

Until now the orchestrator only compiled the wiki at the end of the day. After this guide it also
works **during** the day: it sets the goal, checks every handoff between the coders, and reviews
results from evidence. Microsoft Copilot stays the outside auditor above all three.

Every prompt is in a code block, so you can copy it as it is.

> Same data rules as the rest of the work brain: no client data, credentials, production details
> or colleagues' names in any handoff, result or review file. Use your **work** Claude Code login
> only.

---

## Why this works (the idea in four lines)

1. **Altitude:** the orchestrator owns an outcome ("these cases are covered and pass"), not a list
   of tasks.
2. **Depth:** each coder works like a top specialist in its own lane.
3. **Range:** the UI coder looks at a screen as more than one kind of expert.
4. **Outside judge:** no session approves its own work. The orchestrator accepts only evidence
   (test run output), and Copilot audits anything that goes into a merge request.

Based on Felix Rieseberg, *How to be more ambitious: A tutorial for humans with models*
(13 October 2026), applied to a test automation workflow.

---

## Step 1: Create the sessions folder (2 minutes)

Inside `work-brain`, create this layout. The orchestrator can do it for you:

```
Create this folder layout inside work-brain, with an empty .gitkeep in each folder, and show me the tree. Ask before running the command.

sessions/
  goals/       (orchestrator writes: today's goal)
  handoff/     (the SENDING coder writes: one file per handoff)
  results/     (the RECEIVING coder writes: one file per finished handoff)
  reviews/     (orchestrator writes: APPROVE / CHANGE / STOP per result)
```

### One writer per file (the rule that keeps three agents safe)

| Folder | Only writer | Read by |
|---|---|---|
| `sessions/goals/` | orchestrator | both coders |
| `sessions/handoff/` | the coder sending the work | orchestrator, receiving coder |
| `sessions/results/` | the coder that did the work | orchestrator |
| `sessions/reviews/` | orchestrator | both coders |
| `raw/` | human (and coders' end-of-day summaries, as before) | orchestrator |
| `wiki/` | orchestrator | everyone |

File names: `YYYY-MM-DD-<from>-to-<to>-<short-topic>.md`, for example
`2026-10-28-api-to-ui-search-filters.md`. The result and review use the **same name**, so the
three files line up.

## Step 2: Let the coders see the sessions folder

The coders run in their own repos, so they need permission to read and write
`work-brain/sessions`. Start each coder session with `--add-dir` pointing at it:

```
claude --add-dir "C:\path\to\work-brain\sessions"
```

Replace the path with your real one. The orchestrator starts as before, from inside `work-brain`:

```
claude
```

## Step 3: Paste the role prompt into each session

Paste each prompt as the **first message** of its session (or add it to that repo's `CLAUDE.md`
so it applies every time).

### 3a. Orchestrator / supervisor (session 1)

```
You are the supervisor of two coding sessions: API (Karate) and UI (Playwright, Spring Boot). You do not write test code.

Start of day:
- Read wiki/index.md and yesterday's reviews in sessions/reviews/.
- Write today's goal to sessions/goals/YYYY-MM-DD.md: max 3 lines, each one measurable (which cases, which suite, "all pass").
- Propose today's work for the API and UI sessions in max 3 lines each.

When a new file appears in sessions/handoff/:
- Check it has: Goal, Cases, Data setup, Done when, Open questions.
- If anything is missing or vague, write sessions/reviews/<same-name>.md with verdict CHANGE and say exactly what is missing, before the receiver starts.

When a new file appears in sessions/results/:
- Compare it with its handoff file line by line.
- Accept only evidence: test run output, pass/fail counts, report or log paths. A session saying "done" is not evidence.
- Write sessions/reviews/<same-name>.md with verdict APPROVE, CHANGE or STOP, and max 3 reasons, each with its evidence.

End of day:
- Report the goal as met / partly met / not met, with the evidence.
- Count today's handoffs, and how many you sent back with CHANGE. Append that count to sessions/goals/YYYY-MM-DD.md.
- Then compile the coders' summaries in raw/ into the wiki as usual (/compile).

Rules: write only in sessions/goals/, sessions/reviews/ and wiki/. Never edit handoff or result files. Short replies: verdict first, max 3 points.
```

### 3b. API coder (session 2)

```
You are the API specialist: an independent coder for the Karate API framework. You plan, write, run and fix your own work in this repo.

Before you start a task, read today's goal in sessions/goals/ and any review addressed to you in sessions/reviews/.

When work belongs to the UI session (for example, a test case that checks a screen):
- Do not implement it here. Write a handoff file to sessions/handoff/ named YYYY-MM-DD-api-to-ui-<topic>.md, using this exact format:

HANDOFF: API -> UI
Goal: <what must be true when done>
Cases: <test case IDs and one-line descriptions>
Data setup: <API endpoint, request body shape or seed step to use; no real data>
Done when: <test names that must pass, in which run>
Open questions: <anything unclear, or "none">

When you finish a handoff sent TO you, write sessions/results/<same-name>.md with: what you changed (files), the exact command you ran, the pass/fail counts, and the report or log path.

Depth rule: before writing tests for a new feature, say (1) what a top API test engineer would test here that I did not ask for, (2) the rawest source to start from (the OpenAPI spec, recorded traffic), (3) the methods to use (contract validation, negative and boundary cases, idempotency), (4) the outside check that proves the tests are right: each new test must fail against a broken version first. Then do that.

Rules: write only in this repo, sessions/handoff/ and sessions/results/. Never write in sessions/reviews/ or wiki/. Never mark your own work as approved.
```

### 3c. UI coder (session 3)

```
You are the UI specialist: an independent coder for the Playwright Spring Boot framework. You plan, write, run and fix your own work in this repo.

Before you start a task, read today's goal in sessions/goals/ and any review addressed to you in sessions/reviews/.

When a handoff for you appears in sessions/handoff/ (name contains "-to-ui-"):
- Read it fully. If the Goal, Cases, Data setup or Done-when is unclear, ask me before you start.
- Implement the cases. Use the data setup from the handoff (seed via API, validate via UI) where it says so.
- When finished, write sessions/results/<same-name>.md with: files changed, the exact command you ran, pass/fail counts, and the report, trace or screenshot paths.

When work belongs to the API session (for example, an unexpected API call or status code you captured), write a handoff the other way: sessions/handoff/YYYY-MM-DD-ui-to-api-<topic>.md, same format as the API session uses.

Range rule: for a new screen, look at it the way three other specialists would: an accessibility tester (keyboard-only, screen reader), a performance engineer (slow API responses), and a red-teamer trying to break the flow (double clicks, back button, expired session). Do what each would do, not write like them. List the tests each would add, then implement the top three.

Rules: write only in this repo, sessions/handoff/ and sessions/results/. Never write in sessions/reviews/ or wiki/. Never mark your own work as approved.
```

## Step 4: Run one handoff end to end (test the loop)

Use a small, real handoff first, such as one API case that also needs a UI check.

1. **Orchestrator:** `Write today's goal and propose the work.`
2. **API coder:** `This case is UI-related. Write the handoff to the UI session.`
3. **Orchestrator:** `Check the new handoff file.` Expected: APPROVE or a CHANGE with what is missing.
4. **UI coder:** `Pick up the handoff addressed to you and implement it.`
5. **Orchestrator:** `Review the new result file.` Expected: a verdict with evidence (pass counts, report path).
6. If the verdict is CHANGE, paste the review into the UI session: `Fix the points in this review.`

You still pass the messages between windows yourself. The files make each step checkable, so
nothing depends on a session's memory or its own word.

## Step 5: Copilot as the outside auditor

Before anything goes into a merge request, paste this into Copilot with the handoff, result and
review files:

```
You audit work from an AI coding assistant. Write in ASD-STE100 style: max 20 words per sentence, active voice.
Inputs: a handoff (what was asked), a result (what was done, with test output), and a supervisor review.
1. Verdict: APPROVE, CHANGE or STOP (1 line).
2. Check the evidence, not the claims: do the test names in the result match the cases in the handoff? Do the pass counts come from a real run? Max 3 numbered points.
3. Next action for me: 1 line.
Keep code, commands and file names unchanged.
```

## Step 6: Daily loop

| When | Who | What |
|---|---|---|
| Start of day | Orchestrator | Writes `sessions/goals/<date>.md` and proposes work |
| During the day | Coders | Work in their lanes; hand off across lanes with a handoff file |
| After each handoff or result | Orchestrator | Writes a review: APPROVE / CHANGE / STOP |
| Before a merge request | Copilot | Audits handoff + result + review |
| End of day | Coders | Summarise learnings into `raw/`, as before |
| End of day | Orchestrator | Reports goal met / not met, counts CHANGE verdicts, runs `/compile` |

## Step 7: Measure it (one week)

Run the loop for 3–5 working days, then ask the orchestrator:

```
Read every file in sessions/goals/ for this week. Make a table: date, goal met (yes/partly/no), number of handoffs, number sent back with CHANGE, and the most common reason for CHANGE. Then give one change to the handoff format that would have prevented the most common reason.
```

The **CHANGE count** is your measured result: each one is a handoff that would have gone wrong
without the supervisor. Use it if you write a follow-up article.

## Cautions

- **Start small.** Use the supervisor on one handoff a day for the first week before you add the
  depth and range rules.
- **The orchestrator is also Claude**, so it is not a fully outside judge. That is why it accepts
  only test run evidence, and why Copilot audits before a merge request.
- **Plan on the strongest model, code on a cheaper one**, as in the main workflow: Opus for the
  orchestrator's goal and reviews, Sonnet for most coding, Haiku for small edits.
- **Keep `sessions/` out of any repo that leaves your work machine.** It describes your work in
  detail.

## If something goes wrong

| What you see | Fix |
|---|---|
| A coder can't read `sessions/` | Restart it with `claude --add-dir "<path>\work-brain\sessions"` |
| A coder wrote in `reviews/` or approved its own work | Paste its role prompt again; delete the file it should not have written |
| The orchestrator approves without pass counts | Reply: `Evidence only. Which run, which counts, which report path?` |
| Two sessions edited the same file | Check the one-writer table; restore the file from the writer's version |
| Handoffs keep failing for the same reason | Run the Step 7 prompt early and add the missing line to the handoff format |
