#!/usr/bin/env python3
"""Structural lint for the work brain. Stdlib only, Python 3.8+. No LLM calls.

Checks: broken links, orphan pages, uncompiled raw notes, pages missing from the index,
missing front matter fields, sparse pages.

  python3 tools/lint.py               full report (exit 1 if errors)
  python3 tools/lint.py --uncompiled  list raw files new or changed since last compile

A raw file counts as compiled when wiki/log.md has "- Source: raw/<file> (sha <hash>)" with
its CURRENT hash. Appending to a note (e.g. an Obsidian daily note) changes the hash, so the
note is offered for compile again. Empty notes are skipped.
"""
import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW, WIKI = ROOT / "raw", ROOT / "wiki"
SPECIAL = {"index.md", "log.md"}
LINK = re.compile(r"\[\[([^\]|#]+)(?:[#|][^\]]*)?\]\]")
REQUIRED = ("title", "type", "sources", "created", "updated")


def pages():
    return sorted(p for p in WIKI.rglob("*.md") if p.name not in SPECIAL or p.parent != WIKI)


def slug(p: Path) -> str:
    return p.relative_to(WIKI).with_suffix("").as_posix()


def front_matter(text: str) -> dict:
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    out = {}
    for line in text[3:end].splitlines():
        if ":" in line and not line.startswith(" "):
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip()
    return out


SOURCE = re.compile(r"^- Source:\s*(raw/\S+?)(?:\s*\(sha ([0-9a-f]{6,})\))?\s*$", re.M)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def compiled_sources() -> dict:
    """raw path -> set of hashes compiled ("" = legacy entry without a hash)."""
    log = WIKI / "log.md"
    out = {}
    if log.exists():
        for path, h in SOURCE.findall(log.read_text(encoding="utf-8")):
            out.setdefault(path, set()).add(h or "")
    return out


def uncompiled():
    """List of (raw path, current sha, 'new' | 'changed')."""
    done = compiled_sources()
    raws = sorted(p for p in RAW.rglob("*.md") if p.name.lower() != "readme.md") if RAW.exists() else []
    todo = []
    for p in raws:
        if not p.read_text(encoding="utf-8", errors="replace").strip():
            continue
        rel, h = p.relative_to(ROOT).as_posix(), sha(p)
        seen = done.get(rel)
        if seen is None:
            todo.append((rel, h, "new"))
        elif h not in seen and "" not in seen:
            todo.append((rel, h, "changed"))
    return todo


def main():
    if "--uncompiled" in sys.argv:
        todo = uncompiled()
        if not todo:
            print("Nothing to compile")
        for rel, h, state in todo:
            print(f"{rel} (sha {h}) {state}")
        return 0

    errors, warnings, notes = [], [], []
    all_pages = pages()
    known = {slug(p) for p in all_pages}
    inbound = {s: 0 for s in known}
    index_text = (WIKI / "index.md").read_text(encoding="utf-8") if (WIKI / "index.md").exists() else ""
    indexed = set(LINK.findall(index_text))

    for p in all_pages:
        text = p.read_text(encoding="utf-8")
        s = slug(p)
        fm = front_matter(text)
        missing = [k for k in REQUIRED if k not in fm]
        if missing:
            errors.append(f"{s}: front matter missing {', '.join(missing)}")
        for target in LINK.findall(text):
            t = target.strip()
            if t.endswith(".md"):
                t = t[:-3]
            if t.startswith("raw/"):
                continue
            if t not in known:
                errors.append(f"{s}: broken link [[{t}]]")
            elif t != s:
                inbound[t] += 1
        if s not in indexed:
            warnings.append(f"{s}: not listed in wiki/index.md")
        if fm.get("status") == "needs-check":
            notes.append(f"{s}: status needs-check")
        body_words = len(re.sub(r"^---.*?\n---", "", text, flags=re.S).split())
        if body_words < 80:
            notes.append(f"{s}: sparse ({body_words} words)")

    for s, n in sorted(inbound.items()):
        if n == 0 and not s.startswith("qa/"):
            warnings.append(f"{s}: orphan (no other page links to it)")
    for rel, h, state in uncompiled():
        warnings.append(f"{rel}: {'not compiled yet' if state == 'new' else 'changed since last compile'}")

    print(f"Pages: {len(all_pages)}  Errors: {len(errors)}  Warnings: {len(warnings)}  Notes: {len(notes)}")
    for label, items in (("ERROR", errors), ("WARN", warnings), ("NOTE", notes)):
        for i in items:
            print(f"  {label}  {i}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
