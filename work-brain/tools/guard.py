#!/usr/bin/env python3
"""Sensitive-data guard for the work brain. Stdlib only, Python 3.8+.

Scans raw/ (default) or wiki/ (--wiki) for values that must never be compiled:
credentials, card numbers, sort codes + account numbers, IBANs, emails, private keys.

Exit 0 = clean, 1 = findings (compile must stop). Values are never printed in full.

Add allowed false positives to tools/guard-allow.txt (one regex per line).
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PATTERNS = [
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("AWS access key", re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("JWT / bearer token", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}")),
    ("GitLab/GitHub token", re.compile(r"\b(glpat-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{30,})\b")),
    ("password/secret assignment",
     re.compile(r"(?i)\b(password|passwd|pwd|secret|api[_-]?key|token|client[_-]?secret)\b\s*[:=]\s*\S{4,}")),
    ("connection string with credentials", re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://[^\s:/@]+:[^\s@]+@")),
    ("IBAN", re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){3,7}(?: ?[A-Z0-9]{1,4})?\b")),
    ("sort code", re.compile(r"\b\d{2}-\d{2}-\d{2}\b")),
    ("email address", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("UK National Insurance number", re.compile(r"\b[A-CEGHJ-PR-TW-Z]{2}\s?\d{2}\s?\d{2}\s?\d{2}\s?[A-D]\b")),
]
CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")


def luhn_ok(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


def load_allow():
    f = ROOT / "tools" / "guard-allow.txt"
    if not f.exists():
        return []
    return [re.compile(x.strip()) for x in f.read_text(encoding="utf-8").splitlines()
            if x.strip() and not x.startswith("#")]


def mask(s: str) -> str:
    s = s.strip()
    return s[:3] + "…" if len(s) > 3 else "…"


def scan(folder: Path):
    allow = load_allow()
    findings = []
    for path in sorted(folder.rglob("*.md")):
        for n, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if any(a.search(line) for a in allow):
                continue
            for label, rx in PATTERNS:
                for m in rx.finditer(line):
                    findings.append((path, n, label, mask(m.group(0))))
            for m in CARD.finditer(line):
                digits = re.sub(r"\D", "", m.group(0))
                if 13 <= len(digits) <= 19 and luhn_ok(digits):
                    findings.append((path, n, "card number (Luhn valid)", mask(digits)))
    return findings


def main():
    target = "wiki" if "--wiki" in sys.argv else "raw"
    folder = ROOT / target
    if not folder.exists():
        print(f"guard: {target}/ not found")
        return 0
    findings = scan(folder)
    if not findings:
        print(f"guard: {target}/ clean")
        return 0
    print(f"guard: {len(findings)} finding(s) in {target}/. Remove these before compiling:")
    for path, n, label, shown in findings:
        print(f"  {path.relative_to(ROOT)}:{n}  {label}  ({shown})")
    return 1


if __name__ == "__main__":
    sys.exit(main())
