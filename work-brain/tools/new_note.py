#!/usr/bin/env python3
"""Create a NEW raw note from stdin. Refuses to overwrite: raw/ is append-only.

  python3 tools/new_note.py "<topic>" <<'EOF'
  note text...
  EOF
"""
import re
import sys
from datetime import date
from pathlib import Path

RAW = Path(__file__).resolve().parent.parent / "raw"


def main():
    if len(sys.argv) < 2:
        print("usage: new_note.py <topic>  (text on stdin)")
        return 2
    topic = " ".join(sys.argv[1:]).strip()
    body = sys.stdin.read().strip()
    if not body:
        print("new_note: empty text, nothing saved")
        return 2
    slug = re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")[:50] or "note"
    RAW.mkdir(exist_ok=True)
    base = f"{date.today().isoformat()}-{slug}"
    path, n = RAW / f"{base}.md", 2
    while path.exists():
        path, n = RAW / f"{base}-{n}.md", n + 1
    with open(path, "x", encoding="utf-8") as f:  # "x" = fail if it exists
        f.write(f"# {topic}\n\n{body}\n")
    print(f"saved {path.relative_to(RAW.parent).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
