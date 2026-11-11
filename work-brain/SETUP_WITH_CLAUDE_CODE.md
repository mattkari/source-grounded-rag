# Set up the Work Brain with Claude Code (step by step)

You have downloaded the `work-brain` folder. Claude Code does most of the setup; you do a few
clicks. Every prompt below is in a code block, so you can copy it as it is.

> Before you write real notes: check that your manager or data team is fine with a personal
> notes knowledge base, use only your **work** Claude Code login, and never type client data,
> credentials or production details into a note. `tools/guard.py` catches passwords and account
> numbers, but it can't recognise client names.

---

## Step 1: Put the folder in your vault (2 minutes, you do this)

1. In File Explorer, move `work-brain` to the **top level of your Obsidian vault** in OneDrive:
   `OneDrive - <Employer>\…\<YourVault>\work-brain\`
2. Right-click `work-brain` and choose **OneDrive → Always keep on this device**.
3. Open `work-brain` and check it contains `CLAUDE.md`, `README.md`, `.claude`, `tools`, `raw`,
   `wiki` and `examples`. Windows hides `.claude` by default; use **View → Show → Hidden items**.

## Step 2: Open a terminal in the folder

- **VS Code:** File → Open Folder → `work-brain`, then Terminal → New Terminal.
- **IntelliJ:** File → Open → `work-brain`, then the Terminal tab.

Every command below runs inside `work-brain`. Never start Claude Code from the vault root, or it
will see all your other notes.

## Step 3: Start Claude Code and check the login

```
claude
```

1. When it asks whether to trust the folder, choose **Yes**.
2. Type `/status`. It must show your **work** login (enterprise or Bedrock).
   **If it shows a personal account, stop here.**

## Step 4: Paste the setup prompt

```
Set up this work brain and check it works. Read README.md, CLAUDE.md and OBSIDIAN_ONEDRIVE_SETUP.md first.

1. Find which Python command works here: try `py --version`, then `python --version`. On Windows, ignore `python3` if it opens the Microsoft Store. Tell me the version, which must be 3.8 or newer.
2. Run tools/lint.py and tools/guard.py with that command. Expected: "Pages: 0  Errors: 0" and "guard: raw/ clean".
3. Check that .claude/commands contains compile.md, query.md, lint.md and ingest.md, and that .claude/settings.json is valid JSON.
4. Copy the 3 example notes from examples/ into raw/ using a shell copy command. Ask me before running it.
5. Run tools/guard.py again and tell me the result.

Rules: do not edit CLAUDE.md, tools/, or .claude/. No web access. Report each step as pass or fail in one line.
```

- It will ask permission for the Python and copy commands. Choose **Yes**.
- You want **5 passes**. If a step fails, the one-line result tells you which.

## Step 5: Practice compile

```
/compile
```

Expected: about **5 new pages** (decisions, defects, how-tos, systems), an updated
`wiki/index.md` and `wiki/log.md`, and a final lint with **0 errors**.

## Step 6: Practice questions

```
/query Why is the Karate suite limited to 6 threads?
```

The answer should cite pages such as `[[decisions/karate-max-six-threads]]`.

Then try a question the notes don't cover:

```
/query How do I rotate Kafka offsets in UAT?
```

The answer should start **"The wiki does not cover this"**. When it asks whether to file an
answer, say **no**.

## Step 7: Obsidian settings (2 minutes, you do this)

In Obsidian, open **Settings**:

1. **Core plugins → Daily notes:** New file location `work-brain/raw`, Date format `YYYY-MM-DD`.
2. **Files and links:** switch on **Use [[Wikilinks]]**.
3. Open `work-brain/wiki/index.md` and click through to the pages. Open the **graph view**.

## Step 8: Clear out the practice data

```
Reset to a clean start: delete the 3 example notes from raw/ (keep raw/.gitkeep), delete every page under wiki/ except index.md and log.md, reset wiki/index.md to just its header row, and reset wiki/log.md to "# Build log (append only)". Ask me before deleting. Then run tools/lint.py and confirm "Pages: 0  Errors: 0".
```

## Step 9: Daily use

| When | What |
|---|---|
| During the day | Write rough bullets in Obsidian's daily note (it now saves to `work-brain/raw`) |
| End of the day | `claude`, then `/compile` |
| When you're stuck | `/query <question>` |
| Fridays | `/lint` |

## If something goes wrong

| What you see | Fix |
|---|---|
| `python` or `py` not recognised | Install Python from Software Center / Company Portal |
| `/compile` stops with "guard: N finding(s)" | Remove the flagged value from that note and line, then run `/compile` again |
| Slash commands don't appear | You started `claude` outside `work-brain`. `cd` into it and restart |
| Claude asks permission for every command | Accept the trust prompt once in `work-brain` |
| Files show a cloud icon | OneDrive → Always keep on this device |
| `name-LAPTOP.md` copies appear | OneDrive sync conflict: keep the newest, delete the copy, run `/lint` |
