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


# ---------------------------------------------------------------------------
# Which sentences of the cited passage to show beside a drafted sentence
# ---------------------------------------------------------------------------

_WORD = re.compile(r"[^\W\d_][\w’'ʿʾ-]*")
_STOP = set("""
about above after again against also although among another because been before being below between both
could does doing down during each either from further have having here however into itself just more most
much must neither nor only other others ought over rather same shall should since some such than that their
theirs them themselves then there these they this those through thus under until upon very were what when
where whereas which while whom whose will with within without would your yours thesis according
""".split())
MATCHES_SHOWN = 3


def content_words(text: str) -> set[str]:
    """The words a sentence is about: lower-cased, four letters or more, no function words."""
    plain = re.sub(r"\[E?\d+\]", " ", text)
    return {word.lower() for word in _WORD.findall(plain) if len(word) >= 4 and word.lower() not in _STOP}


@dataclass(frozen=True)
class Match:
    text: str               # one sentence of the passage, as stored
    shared: frozenset       # the content words it shares with the drafted sentence
    share: float            # shared words as a share of the drafted sentence's content words


def best_matches(sentence: str, passage: str, limit: int = MATCHES_SHOWN) -> list[Match]:
    """Up to `limit` sentences of the passage that share most words with `sentence`,
    best first. This chooses what to put in front of the reader. It says nothing about
    whether the passage supports the sentence: shared words are not shared meaning."""
    wanted = content_words(sentence)
    found = []
    for position, candidate in enumerate(split(" ".join(passage.split()))):
        shared = wanted & content_words(candidate)
        if shared:
            found.append((-len(shared), position, Match(candidate, frozenset(shared), len(shared) / len(wanted))))
    return [match for _, _, match in sorted(found)[:limit]]


_MARKDOWN = re.compile(r"([\\`*_{}\[\]()#+\-!|>~$<&])")


def highlight(text: str, shared: frozenset | set) -> str:
    """`text` as Markdown with the shared words in bold. Every character that
    Markdown could read as formatting is escaped first: the passage is shown, never run."""
    pieces, position = [], 0
    for match in _WORD.finditer(text):
        pieces.append(_MARKDOWN.sub(r"\\\1", text[position:match.start()]))
        word = _MARKDOWN.sub(r"\\\1", match.group(0))
        pieces.append(f"**{word}**" if match.group(0).lower() in shared else word)
        position = match.end()
    pieces.append(_MARKDOWN.sub(r"\\\1", text[position:]))
    return "".join(pieces)
