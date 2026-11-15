"""Sentences as the unit of checking — ADR 0008.

A note that covers six sentences cannot be judged with one verdict: three of
the six may be wrong. The article writer therefore works sentence by sentence.
This module splits a section's prose into sentences with stable ids, and (for
the review) finds the passage sentences that best match one, by plain word
overlap. No model is involved anywhere here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_HANDLE = re.compile(r"\[E(\d+)\]")
_BOUNDARY = re.compile(r"[.!?][\"'’”)]*(?:\s?\[E?\d+\])*\s+")
_LAST_WORD = re.compile(r"([^\W\d_][\w’'-]*)[\"'’”)]*$")
# A full stop after one of these does not end a sentence.
_ABBREVIATIONS = {
    "e.g", "i.e", "cf", "vol", "vols", "no", "nos", "p", "pp", "d", "b", "c", "ca", "ed", "eds", "trans", "vs",
    "viz", "st", "dr", "mr", "mrs", "ms", "prof", "fig", "ch", "sec", "par", "ibid", "op", "cit", "n", "r",
}


def split(text: str) -> list[str]:
    """Sentences of one paragraph. A note marker that trails the full stop stays
    with its sentence; an abbreviation or an initial does not end one."""
    found, start = [], 0
    for match in _BOUNDARY.finditer(text):
        if text[match.start()] == ".":
            word = _LAST_WORD.search(text[start:match.start()])
            before = text[start:match.start()].rstrip("\"'’”)")
            dotted = re.search(r"((?:[^\W\d_]\.)+[^\W\d_])$", before)           # "e.g", "i.e"
            last = (dotted.group(1) if dotted else word.group(1) if word else "").lower()
            initial = bool(word) and len(word.group(1)) == 1 and word.group(1).isupper()
            if last in _ABBREVIATIONS or initial:
                continue
        found.append(text[start:match.end()].strip())
        start = match.end()
    tail = text[start:].strip()
    if tail:
        found.append(tail)
    return found


def handles(text: str) -> list[str]:
    """The evidence handles in a sentence, in order, without repeats."""
    return list(dict.fromkeys(f"E{n}" for n in _HANDLE.findall(text)))


@dataclass(frozen=True)
class Unit:
    sid: str            # "<section index>.<sentence index>": stable for a given draft text
    paragraph: int
    text: str


def units(section: int, text: str) -> list[Unit]:
    """A section's prose as sentences, in order, each with its id and paragraph."""
    found: list[Unit] = []
    for paragraph, line in enumerate(line for line in text.split("\n") if line.strip()):
        for sentence in split(line):
            found.append(Unit(f"{section}.{len(found)}", paragraph, sentence))
    return found
