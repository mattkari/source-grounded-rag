# Obsidian and OneDrive setup (work laptop)

Your existing Obsidian vault is in OneDrive. Add the work brain to it as **one top-level folder**,
so Obsidian sees it and Claude Code only sees that folder.

```
OneDrive - <Employer>\Obsidian\<YourVault>\          <- vault root (Obsidian opens this)
├── .obsidian\                                    <- Obsidian settings (leave alone)
├── ...your existing notes...                     <- Claude Code never sees these
└── work-brain\                                   <- unzip the template here
    ├── CLAUDE.md   .claude\   tools\
    ├── raw\        <- you write here (Obsidian daily notes go here)
    └── wiki\       <- Claude writes here, you read it in Obsidian
```

**Always run Claude Code from inside `work-brain`, never from the vault root.** That keeps
your other notes out of every prompt.

## 1. Check this is the approved OneDrive (2 minutes)

- Use the **work** OneDrive. The folder is usually named `OneDrive - <Employer>` (your
  employer's name), not plain `OneDrive`, which is the personal one.
- The `work-brain` folder must not be shared with anyone. In File Explorer, right-click it,
  choose OneDrive, then Manage access, and check that only you are listed.
- OneDrive keeps every version, so a value you delete later still exists in its history. This is
  another reason the guard runs before every compile.

## 2. Unzip and open (5 minutes)

1. Unzip `work-brain-template.zip` into the vault root. You get `<YourVault>\work-brain\`.
2. Right-click `work-brain`, choose OneDrive, then **Always keep on this device**. Claude Code
   and the Python tools then read real files, not cloud placeholders.
3. Open a terminal in that folder:
   - **VS Code or IntelliJ:** File, then Open, then `work-brain`; then open the terminal.
   - **PowerShell:** `cd "$env:OneDriveCommercial\Obsidian\<YourVault>\work-brain"`
4. Check that Python works: `py --version` or `python --version` (needs 3.8 or later).
5. Run `claude`, accept the trust prompt, then type `/status` and confirm it shows your
   **enterprise or Bedrock** login, not a personal account.

## 3. Make Obsidian write into raw/ (3 minutes)

In Obsidian, go to **Settings**:

| Setting | Value | Why |
|---|---|---|
| Core plugins, then **Daily notes**, then New file location | `work-brain/raw` | Today's note goes straight into `raw/` |
| Daily notes, then Date format | `YYYY-MM-DD` | Matches the tool naming |
| Files and links, then **Default location for new notes** | `work-brain/raw` (optional) | New notes also land in `raw/` |
| Files and links, then **Use [[Wikilinks]]** | On | Links in `wiki/` work |
| Files and links, then **New link format** | Absolute path in vault | Optional; links inside `wiki/` already resolve |

**Daily routine:**
1. During the day, press the **Open today's daily note** icon and type notes as rough
   bullets. Adding to the same day's note all day is fine.
2. At the end of the day, in the terminal in `work-brain`, run `/compile`.
3. Read the result in Obsidian under `work-brain/wiki/`. Use graph view and backlinks there.
4. To ask a question, run `/query <question>` in the terminal.

## 4. Rules that matter with Obsidian

- **Don't edit files in `wiki/`.** Compile rewrites them. To correct something, add a
  correction note to `raw/` and run `/compile` again.
- **Don't rename or delete files in `raw/`.** The log tracks notes by name. Adding to a note is
  fine; the next compile picks up the new text.
- If a raw note was compiled before, adding to it marks it `changed` and it compiles again.
- Empty daily notes are ignored.
- `.obsidian/` belongs to Obsidian; Claude Code never touches it.

## 5. OneDrive problems and fixes

| What you see | Fix |
|---|---|
| Files show a cloud icon or tools say a file is not found | Right-click `work-brain`, then **Always keep on this device** |
| Files named `name-LAPTOP.md` or `name (1).md` appear | Sync conflict. Keep the newest, delete the copy, then run `/lint` |
| Compile is slow or files are locked | Pause OneDrive sync while `/compile` runs (OneDrive icon, then Pause syncing, 2 hours), then resume |
| `python` not recognised | Use `py`. Windows installs the launcher under that name |
| Claude asks permission for every command | Run `claude` once in `work-brain` and accept the trust prompt |

## 6. If you also open the vault on your phone

The OneDrive app on a phone doesn't sync folders that Obsidian mobile can open, and your
**work vault should stay off personal devices**. Read the wiki on the work laptop, or in
the browser through OneDrive if your bank's policy allows it.
