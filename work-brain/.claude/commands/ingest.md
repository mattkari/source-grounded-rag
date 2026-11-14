---
description: Save a new raw note (new file only, never edits)
allowed-tools: Bash(python tools/new_note.py:*), Bash(python3 tools/new_note.py:*), Bash(python tools/guard.py:*), Bash(python3 tools/guard.py:*)
---

Save the text below as a new raw note. Do not use Write or Edit on `raw/`; use the script, which
refuses to overwrite:

```
python3 tools/new_note.py "<short topic>" <<'EOF'
<the text, verbatim>
EOF
```

(Use `python` if `python3` is not found.) Then run `python3 tools/guard.py` and report any
findings. Do not compile. Reply with the saved file name in one line.

Text:
$ARGUMENTS
