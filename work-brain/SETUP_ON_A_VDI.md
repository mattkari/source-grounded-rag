# Set up the Work Brain on a fresh Windows VDI with Claude Code

Use this guide on a new or temporary Windows virtual desktop (for example a hackathon or project
VDI) where Claude Code already works. It needs no Obsidian and no OneDrive. It takes about 20
minutes. Claude Code does the work; you paste the prompts and answer its questions.

> **Before you start:** use only the Claude Code login that your employer or the event gave you.
> Keep the folder on the VDI. Never push notes to a personal GitHub account or a personal cloud
> drive. A temporary VDI may be wiped at the end, so ask before you copy notes anywhere else.

---

## Step 1: Make a folder and start Claude Code (you do this)

Open PowerShell and run:

```
mkdir $HOME\brain-setup
cd $HOME\brain-setup
claude
```

1. When Claude Code asks whether to trust the folder, choose **Yes**.
2. Type `/status`. It must show your **work or event login** (enterprise, Amazon Bedrock,
   Google Vertex or Microsoft Foundry). **If it shows a personal account, stop here.**

## Step 2: Download the template (paste into Claude Code)

```
Set up a work-brain folder from a public template. Work only inside the current folder.

1. Download https://github.com/mattkari/source-grounded-rag/archive/refs/heads/feature/work-brain-template.zip into the current folder, using whatever shell command works here (PowerShell Invoke-WebRequest, or curl). Ask me before running it.
2. Extract the zip. The template is in source-grounded-rag-feature-work-brain-template/work-brain. Move that work-brain folder into the current folder.
3. Delete the zip and everything else that was extracted. Keep only the work-brain folder. Ask me before deleting.
4. List work-brain including hidden items. Expected: .claude/commands with compile.md, ingest.md, lint.md and query.md; .claude/settings.json; .gitignore; CLAUDE.md; README.md; SETUP_WITH_CLAUDE_CODE.md; SETUP_ON_A_VDI.md; SUPERVISED_SESSIONS.md; OBSIDIAN_ONEDRIVE_SETUP.md; examples with 3 notes; raw with .gitkeep; tools with guard.py, lint.py and new_note.py; wiki with index.md and log.md.

Rules: do not open or run any other file from the zip. Do not push anything to GitHub or to any cloud storage. If the download is blocked, stop and tell me; do not try another route. Report each step as pass or fail in one line.
```

You want **4 passes**.

## Step 3: Restart Claude Code inside work-brain (you do this)

```
/exit
```

Then in PowerShell:

```
cd $HOME\brain-setup\work-brain
claude
```

1. Choose **Yes** to trust the folder.
2. Type `/` and check that **compile**, **ingest**, **lint** and **query** appear in the list.

Always start Claude Code inside `work-brain`. Its rules and slash commands load only there.

## Step 4: Check the setup (paste into Claude Code)

```
Set up this work brain and check it works. Read README.md and CLAUDE.md first.

1. Find which Python command works here: try `py --version`, then `python --version`. On Windows, ignore `python3` if it opens the Microsoft Store. Tell me the version, which must be 3.8 or newer.
2. Run tools/lint.py and tools/guard.py with that command. Expected: "Pages: 0  Errors: 0" and "guard: raw/ clean".
3. Check that .claude/commands contains compile.md, query.md, lint.md and ingest.md, and that .claude/settings.json is valid JSON.
4. Copy the 3 example notes from examples/ into raw/ using a shell copy command. Ask me before running it.
5. Run tools/guard.py again and tell me the result.

Rules: do not edit CLAUDE.md, tools/, or .claude/. No web access. Report each step as pass or fail in one line.
```

You want **5 passes**. Choose **Yes** when it asks to run the Python and copy commands.

## Step 5: Practise compile

```
/compile
```

Expected: about **5 new pages** (decisions, defects, how-tos, systems), an updated
`wiki/index.md` and `wiki/log.md`, and a final lint with **0 errors**.

## Step 6: Practise questions

```
/query Why is the Karate suite limited to 6 threads?
```

The answer should cite pages such as `[[decisions/karate-max-six-threads]]`.

Then ask something the notes do not cover:

```
/query How do I rotate Kafka offsets in UAT?
```

The answer should start **"The wiki does not cover this"**. When it asks whether to file an
answer, say **no**.

## Step 7: Clear out the practice data

```
Reset to a clean start: delete the 3 example notes from raw/ (keep raw/.gitkeep), delete every page under wiki/ except index.md and log.md, reset wiki/index.md to just its header row, and reset wiki/log.md to "# Build log (append only)". Ask me before deleting. Then run tools/lint.py and confirm "Pages: 0  Errors: 0".
```

## Step 8: Daily use without Obsidian

| When | What |
|---|---|
| You learn something | `/ingest <your rough note>` |
| End of the day | `/compile` |
| You are stuck | `/query <question>` |
| Once a week | `/lint` |

Several Claude Code sessions at once (for example an API coder and a UI coder)? Add the
orchestrator from [`SUPERVISED_SESSIONS.md`](SUPERVISED_SESSIONS.md).

## If something goes wrong

| What you see | Fix |
|---|---|
| The download is blocked | Stop. Ask the VDI owner how approved files reach the machine. Do not try another route |
| `py` or `python` not recognised | Install Python from Software Center or Company Portal, or ask the VDI owner |
| Slash commands do not appear | You started `claude` outside `work-brain`. `cd` into it and start again |
| `/compile` stops with "guard: N finding(s)" | Remove the flagged value from that note and line, then run `/compile` again |
| Claude asks permission for every command | Accept the trust prompt once inside `work-brain` |
| `.claude` is missing from File Explorer | It is hidden: View, then Show, then Hidden items |
