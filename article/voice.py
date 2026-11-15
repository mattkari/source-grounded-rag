"""Surface measures of writing voice — PLAN_V6 §10.

The answer prompt writes in a report register. Whether a drafted section
sounds like the researcher is measured here against the researcher's own
writing, by plain counting. No model is involved.

These are surface counts. Matching them does not make a draft sound like the
researcher; missing them shows that it does not. No single score is computed
and no threshold is set here: what counts as close enough is the researcher's
decision, made from a real comparison.
"""

from __future__ import annotations

import re
from statistics import median

FIRST_PERSON = re.compile(r"\b(i|me|my|mine|we|us|our|ours)\b", re.IGNORECASE)
# Words that open a sentence by tying it to the one before.
CONNECTIVES = (
    "but", "and", "so", "yet", "however", "still", "then", "thus", "therefore", "moreover",
    "instead", "meanwhile", "indeed", "in other words", "for example", "for instance",
    "in short", "that said", "even so", "after all", "by contrast", "as a result",
)
# The report register of the answer prompt.
REPORT_PHRASES = (
    "the collection states", "the collection does not", "the thesis states", "the evidence indicates",
    "the evidence states", "the passage states", "according to the collection", "the collection describes",
)
# Connectives counted anywhere in a sentence, for the rate per thousand words. The
# short ones ("and", "but", "so") are counted only where they open a sentence, since
# inside one they mostly join words, not thoughts. This list is this module's own:
# a rate computed elsewhere from another list will differ.
ANYWHERE = (
    "however", "therefore", "thus", "moreover", "furthermore", "hence", "consequently", "nevertheless",
    "nonetheless", "accordingly", "similarly", "likewise", "instead", "meanwhile", "indeed", "finally",
    "in other words", "for example", "for instance", "in short", "that said", "even so", "after all",
    "by contrast", "in contrast", "as a result", "in addition", "in turn", "on the other hand",
    "for this reason", "that is", "in this way",
)
OPENING_ONLY = ("but", "and", "so", "yet", "still", "then", "first", "second", "third")
EM_DASH = re.compile(r"—|(?<=\w)\s--\s(?=\w)")
# The targets of the researcher's voice profile that were given to this project
# (ADR 0005). Two of its eight checks; the other six were not supplied.
PROFILE = (
    ("connectives_per_1000_words", "at least", 12.0),
    ("em_dashes", "at most", 0),
)
_SENTENCE_END = re.compile(r"(?<=[.!?])[\"'’”)\]]*\s+")
_MARKERS = re.compile(r"\[\d+\]|\[E\d+\]")
_WORD = re.compile(r"[A-Za-zÀ-ÿʿʾ’'-]+")


def sentences(text: str) -> list[str]:
    plain = _MARKERS.sub("", text)
    parts = [part.strip() for block in plain.split("\n") for part in _SENTENCE_END.split(block)]
    return [part for part in parts if _WORD.search(part)]


def measure(text: str) -> dict:
    """Counts for one text. Rates are per hundred sentences, or per thousand words."""
    found = sentences(text)
    lengths = sorted(len(_WORD.findall(s)) for s in found)
    words = sum(lengths)
    lowered = text.lower()

    def opens_with_connective(sentence: str) -> bool:
        start = sentence.lower().lstrip("“\"'(")
        return any(re.match(rf"{re.escape(c)}\b", start) for c in CONNECTIVES)

    connectives = sum(len(re.findall(rf"\b{re.escape(c)}\b", lowered)) for c in ANYWHERE) + sum(
        1 for s in found if re.match(rf"[“\"'(]*(?:{'|'.join(OPENING_ONLY)})\b", s.lower()))
    count = len(found)
    per_hundred = (lambda n: round(100 * n / count, 1)) if count else (lambda n: 0.0)
    quarter = lengths[len(lengths) // 4] if lengths else 0
    three_quarters = lengths[(3 * len(lengths)) // 4] if lengths else 0
    return {
        "sentences": count,
        "words": words,
        "sentence_length_median": median(lengths) if lengths else 0,
        "sentence_length_middle_half": [quarter, three_quarters],
        "first_person_per_100_sentences": per_hundred(sum(1 for s in found if FIRST_PERSON.search(s))),
        "connective_openings_per_100_sentences": per_hundred(sum(1 for s in found if opens_with_connective(s))),
        "report_phrases_per_1000_words": round(
            1000 * sum(lowered.count(phrase) for phrase in REPORT_PHRASES) / words, 1
        ) if words else 0.0,
        "connectives_per_1000_words": round(1000 * connectives / words, 1) if words else 0.0,
        "em_dashes": len(EM_DASH.findall(text)),
    }


def profile_checks(measures: dict) -> list[dict]:
    """Each known target of the voice profile, the value measured, and whether it is met."""
    return [
        {"check": key, "target": f"{rule} {target}", "value": measures[key],
         "met": measures[key] >= target if rule == "at least" else measures[key] <= target}
        for key, rule, target in PROFILE
    ]


ROWS = (
    ("Sentences", "sentences"),
    ("Sentence length, median (words)", "sentence_length_median"),
    ("Sentence length, middle half (words)", "sentence_length_middle_half"),
    ("First person, per 100 sentences", "first_person_per_100_sentences"),
    ("Connective openings, per 100 sentences", "connective_openings_per_100_sentences"),
    ("Report-register phrases, per 1,000 words", "report_phrases_per_1000_words"),
    ("Connectives, per 1,000 words (target 12 or more)", "connectives_per_1000_words"),
    ("Em dashes (target 0)", "em_dashes"),
)


def format_comparison(columns: dict[str, dict]) -> str:
    """Plain-text table of measures, one column per text. No score, no verdict."""
    names = list(columns)

    def cell(value) -> str:
        return f"{value[0]}–{value[1]}" if isinstance(value, list) else str(value)

    width = max(len(label) for label, _ in ROWS)
    lines = [f"{'':<{width}}  " + "  ".join(f"{name:>18}" for name in names)]
    for label, key in ROWS:
        lines.append(f"{label:<{width}}  " + "  ".join(f"{cell(columns[name][key]):>18}" for name in names))
    return "\n".join(lines)
