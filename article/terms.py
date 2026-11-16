"""Terms an article uses in more than one section — ADR 0009.

One English term named the faculty of anger in one section of the first
published article and the faculty of desire in another. The source uses it both
ways, on different pages, so each sentence was faithful to its passage and
every check passed. Only a reader who sees both uses side by side can tell.

This module puts them side by side. It finds the terms that occur in two or
more sections and lists each sentence that uses one, by section. It decides
nothing: whether a term means the same thing each time is the researcher's to
read. No model is involved.

A term here is a word carrying transliteration marks, a phrase the text puts
in quotation marks, or a run of two or three content words that recurs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from article.sentences import _STOP, _WORD

SHOWN = 12                      # terms listed, most widely used first
_NOTE = re.compile(r"\[E?\d+\]")
_QUOTED = re.compile(r"[“\"‘']([^”\"’']{3,60})[”\"’']")
_COMMON = _STOP | set("""
thesis author argues argue states state describes describe notes note writes holds view according
first second third also thus hence however therefore moreover three four five several many some
the and for are was were has had not but its his her him she they them you our one two all any can may
who how why what when where which that this these those with from into onto upon over under than then
does did done been being have will would shall should could might must each both such only very more most
out off per via yet nor too own same other another also about after before between among against within
""".split())


_JOINERS = {"of", "and", "in", "for", "to"}       # the small words a term may hold in its middle


@dataclass
class Term:
    term: str
    uses: dict[int, list[dict]] = field(default_factory=dict)      # section index -> [{sid, sentence}]

    @property
    def sections(self) -> int:
        return len(self.uses)

    @property
    def count(self) -> int:
        return sum(len(found) for found in self.uses.values())


def _content(word: str) -> bool:
    return len(word) >= 3 and word.lower() not in _COMMON


def candidates(sentence: str) -> set[str]:
    """The terms one sentence offers, lower-cased."""
    plain = _NOTE.sub(" ", sentence)
    found = {match.strip().lower() for match in _QUOTED.findall(plain) if _content(match.strip())}
    for clause in re.split(r"[,;:.!?()—]", plain):
        words = _WORD.findall(clause)
        found |= {word.lower() for word in words if any(ord(char) > 127 for char in word) and len(word) >= 3}
        for size in (2, 3):
            for start in range(len(words) - size + 1):
                run = words[start:start + size]
                # "doctrine of the mean" is a term; "keeper the lamp" is two words that met.
                joined = all(_content(word) or word.lower() in _JOINERS for word in run[1:-1])
                if _content(run[0]) and _content(run[-1]) and joined:
                    found.add(" ".join(word.lower() for word in run))
    return found


def shared_terms(pairs: list[dict], own_words: list[dict] | None = None) -> list[Term]:
    """Terms used in two or more sections, with every sentence that uses each.

    `pairs` are an article's sentence-and-note pairs; a sentence is counted once
    however many notes it carries. A phrase contained in a longer one that occurs
    in exactly the same sentences is dropped, so the longest form is shown.
    """
    sentences: dict[str, dict] = {}
    for entry in [*pairs, *(own_words or [])]:
        if not entry["sid"].endswith(".L"):
            sentences.setdefault(entry["sid"], {"sid": entry["sid"], "section": entry["section"],
                                                "sentence": entry.get("sentence") or entry.get("text", "")})
    terms: dict[str, Term] = {}
    for use in sentences.values():
        for term in candidates(use["sentence"]):
            terms.setdefault(term, Term(term)).uses.setdefault(use["section"], []).append(
                {"sid": use["sid"], "sentence": use["sentence"]})
    shared = [term for term in terms.values() if term.sections >= 2]

    def where(term: Term) -> frozenset:
        return frozenset(use["sid"] for found in term.uses.values() for use in found)

    kept = [term for term in shared
            if not any(other is not term and term.term in other.term and where(other) == where(term) for other in shared)]
    kept.sort(key=lambda term: (-term.sections, -len(term.term.split()), -term.count, term.term))
    return kept[:SHOWN]


def as_record(terms: list[Term]) -> list[dict]:
    """For the record: the term and where it is used. Sentences are held once, under `pairs`."""
    return [{"term": term.term, "sections": sorted(term.uses),
             "sentences": sorted(use["sid"] for found in term.uses.values() for use in found)} for term in terms]
