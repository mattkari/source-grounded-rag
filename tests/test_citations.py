"""Citation resolution (hard rule 2, PLAN_V3 §6).

A page number shown as a citation comes from the chunk's stored provenance. It
is never taken from anything the model wrote.

What these tests do NOT claim: that a sentence in which the model wrote "p. 99"
is deleted from the rendered prose. It is not — the shells print the answer and
then a VALIDATION FAILED banner. What is pinned here is that such a number can
never become a citation, never enters the evaluation record's cited pages, and
always fails validation.
"""

from __future__ import annotations

import json
import re

import ask
import evaluate
from scripts import check_gold

FOOTNOTE_RULE = "─" * 30


def footnote_block(rendered: str) -> str:
    """The citation footnotes: between the short rule and the diagnostics."""
    after_rule = rendered.split("\n" + FOOTNOTE_RULE + "\n", 1)[1]
    return after_rule.split("\nRETRIEVAL DIAGNOSTICS", 1)[0]


def test_page_phrase_uses_the_stored_label_for_a_single_page(chunks):
    assert ask.page_phrase(chunks[0]) == "p. 3"


def test_page_phrase_uses_the_stored_labels_for_a_range(chunks):
    assert ask.page_phrase(chunks[1]) == "pp. 7–8"


def test_an_unresolved_page_is_flagged_for_verification_not_guessed(chunks):
    phrase = ask.page_phrase(chunks[3])
    assert phrase == "page not printed on source page (PDF p. 28) [VERIFY]"


def unnumbered(chunks, **overrides) -> dict:
    """A fixture chunk with its page provenance replaced."""
    chunk = dict(chunks[0])
    chunk.update(overrides)
    return chunk


def test_a_passage_that_runs_onto_an_unnumbered_page_names_that_page_and_keeps_its_label(chunks):
    """Printed 4 on PDF 27, then PDF 28 with no number: PDF 27 must not be called unprinted."""
    chunk = unnumbered(chunks, page_start="4", page_end=None, pdf_page_start=27, pdf_page_end=28,
                       pages_unresolved=[28])

    assert ask.page_phrase(chunk) == "p. 4 and PDF p. 28, which has no printed number [VERIFY]"


def test_a_passage_that_starts_on_an_unnumbered_page_names_that_page_and_keeps_its_label(chunks):
    chunk = unnumbered(chunks, page_start=None, page_end="6", pdf_page_start=28, pdf_page_end=29,
                       pages_unresolved=[28])

    assert ask.page_phrase(chunk) == "p. 6 and PDF p. 28, which has no printed number [VERIFY]"


def test_a_blank_page_inside_the_range_is_not_named_as_unnumbered(chunks):
    """The real case: printed 42 on PDF 65, PDF 66 blank, PDF 67 with text and no number."""
    chunk = unnumbered(chunks, page_start="42", page_end=None, pdf_page_start=65, pdf_page_end=67,
                       pages_unresolved=[67])
    phrase = ask.page_phrase(chunk)

    assert phrase == "p. 42 and PDF p. 67, which has no printed number [VERIFY]"
    assert "65" not in phrase and "66" not in phrase


def test_a_range_of_unnumbered_pages_names_every_one_of_them(chunks):
    chunk = unnumbered(chunks, page_start=None, page_end=None, pdf_page_start=66, pdf_page_end=67,
                       pages_unresolved=[66, 67])

    assert ask.page_phrase(chunk) == "page not printed on source page (PDF pp. 66–67) [VERIFY]"


def test_unnumbered_pages_that_are_not_adjacent_are_listed_not_spanned(chunks):
    chunk = unnumbered(chunks, page_start=None, page_end=None, pdf_page_start=28, pdf_page_end=31,
                       pages_unresolved=[28, 31])

    assert ask.page_phrase(chunk) == "page not printed on source page (PDF pp. 28, 31) [VERIFY]"


def test_several_unnumbered_pages_beside_a_label_take_the_plural(chunks):
    chunk = unnumbered(chunks, page_start="4", page_end=None, pdf_page_start=27, pdf_page_end=29,
                       pages_unresolved=[28, 29])

    assert ask.page_phrase(chunk) == "p. 4 and PDF pp. 28–29, which have no printed number [VERIFY]"


def test_an_index_that_never_recorded_its_unnumbered_pages_says_only_what_it_knows(chunks):
    """Older indexes carry no `pages_unresolved`. The stored PDF range is named,
    without claiming which of its pages is the one with no number."""
    whole = unnumbered(chunks, page_start=None, page_end=None, pdf_page_start=28, pdf_page_end=29)
    part = unnumbered(chunks, page_start="4", page_end=None, pdf_page_start=27, pdf_page_end=28)
    del whole["pages_unresolved"], part["pages_unresolved"]

    assert ask.page_phrase(whole) == "page not printed on source page (PDF pp. 28–29) [VERIFY]"
    assert ask.page_phrase(part) == (
        "p. 4 and PDF pp. 27–28, at least one of which has no printed number [VERIFY]"
    )


def test_no_page_label_is_ever_made_up_for_an_unnumbered_page(chunks):
    """Hard rule 2: the only printed label in the phrase is the one that was stored."""
    chunk = unnumbered(chunks, page_start="42", page_end=None, pdf_page_start=65, pdf_page_end=67,
                       pages_unresolved=[67])
    phrase = ask.page_phrase(chunk)
    printed = [label for match in PRINTED_CITATION.findall(phrase) for label in match if label]

    assert printed == ["42"]
    assert "None" not in phrase
    assert "43" not in phrase and "44" not in phrase


def test_fully_numbered_passages_are_cited_exactly_as_before(chunks):
    assert ask.page_phrase(chunks[0]) == "p. 3"
    assert ask.page_phrase(chunks[1]) == "pp. 7–8"
    assert ask.page_phrase(chunks[5]) == "pp. 9–11"


def test_footnote_is_built_from_configured_identity_and_stored_provenance(items):
    line = ask.footnote(1, items[0])
    assert line == (
        f"1. {ask.settings.document_author} ({ask.settings.document_year}), "
        "Ch. “FIXTURE chapter”, § FIXTURE lamp oil ledger, p. 3."
    )


def test_a_reference_list_citation_says_what_it_can_support(items):
    line = ask.footnote(2, items[4])
    assert line.endswith("p. 15. [reference list — what the thesis cites, not what it argues]")


def test_footnotes_are_numbered_by_first_use_and_resolve_to_stored_pages(items, answer):
    result = answer(answer="FIXTURE claim [E2], then another [E1], then the first again [E2].")
    rendered = ask.render("FIXTURE: question?", result, items, verbose=False)

    assert "FIXTURE claim ¹, then another ², then the first again ¹." in rendered
    footnotes = footnote_block(rendered).strip().splitlines()
    assert len(footnotes) == 2
    assert footnotes[0].startswith("1. ") and footnotes[0].endswith("pp. 7–8.")
    assert footnotes[1].startswith("2. ") and footnotes[1].endswith("p. 3.")


def test_an_unknown_handle_gets_no_footnote_and_no_number(items, answer):
    result = answer(answer="FIXTURE claim [E1] and an invented source [E9].")

    assert ask.assign_order(result, items) == {"E1": 1}
    rendered = ask.render("FIXTURE: question?", result, items, verbose=False)
    assert "an invented source [E9]." in rendered  # left visible, never given a citation number
    assert len(footnote_block(rendered).strip().splitlines()) == 1


def test_a_page_number_written_by_the_model_never_becomes_a_citation(items, answer, pages_path):
    result = answer(answer="FIXTURE claim, which the model places on p. 99 [E1].")

    # 1. It is a blocking validation failure.
    assert any(f.startswith("invented_page_reference") for f in ask.validate(result, items))

    # 2. The footnote carries the stored label, not the model's number.
    footnotes = footnote_block(ask.render("FIXTURE: question?", result, items, verbose=False))
    assert "p. 3." in footnotes
    assert "99" not in footnotes

    # 3. The evaluation record's cited pages come from provenance alone.
    pdf_to_label = check_gold.load_page_map(pages_path).pdf_to_label
    _, cited_pages = evaluate._cited(result, items, pdf_to_label)
    assert cited_pages == ["3"]


def test_the_model_is_never_shown_a_page_number(items):
    block = ask.render_evidence_block(items)

    assert ask.PAGE_CLAIM_RE.findall(block) == []
    for item in items:
        assert ask.page_phrase(item.chunk) not in block
        assert f"[{item.handle}]" in block
    assert "REFERENCE APPARATUS" in block  # the bibliography chunk is labelled as such


def test_chunk_pages_lists_every_printed_label_in_the_stored_range(chunks, pages_path):
    pdf_to_label = check_gold.load_page_map(pages_path).pdf_to_label

    assert evaluate.chunk_pages(chunks[0], pdf_to_label) == ["3"]
    assert evaluate.chunk_pages(chunks[5], pdf_to_label) == ["9", "10", "11"]


def test_chunk_pages_gives_no_label_for_a_page_whose_number_did_not_print(chunks, pages_path):
    pdf_to_label = check_gold.load_page_map(pages_path).pdf_to_label
    assert evaluate.chunk_pages(chunks[3], pdf_to_label) == []


def test_a_partly_numbered_passage_is_cited_under_the_one_label_the_reader_is_shown(items, answer, pages_path):
    """A passage that runs from printed page 4 onto a page with no printed number.
    The citation shows "p. 4", so the evaluation record carries label 4 and no other."""
    pdf_to_label = check_gold.load_page_map(pages_path).pdf_to_label
    items[0].chunk.update(page_start="4", page_end=None, pdf_page_start=27, pdf_page_end=28,
                          pages_unresolved=[28])

    assert evaluate.chunk_pages(items[0].chunk, pdf_to_label) == ["4"]
    assert ask.footnote(1, items[0]).endswith("p. 4 and PDF p. 28, which has no printed number [VERIFY].")
    assert evaluate.cited_chunk_pages(items[0].chunk, pdf_to_label) == ["4"]
    citations, cited_pages = evaluate._cited(answer(), items, pdf_to_label)
    assert citations == [{"handle": "E1", "chunk_id": items[0].chunk["chunk_id"], "pages": ["4"]}]
    assert cited_pages == ["4"]


def test_a_passage_with_no_printed_label_at_either_end_is_cited_under_none(chunks, pages_path):
    pdf_to_label = check_gold.load_page_map(pages_path).pdf_to_label
    chunk = unnumbered(chunks, page_start=None, page_end=None, pdf_page_start=28, pdf_page_end=28,
                       pages_unresolved=[28])

    assert evaluate.cited_chunk_pages(chunk, pdf_to_label) == []


def test_a_resolved_citation_carries_every_label_in_its_range(chunks, pages_path):
    pdf_to_label = check_gold.load_page_map(pages_path).pdf_to_label
    assert evaluate.cited_chunk_pages(chunks[5], pdf_to_label) == ["9", "10", "11"]


# ---------------------------------------------------------------------------
# The real index: passages on the PDF pages that carry no printed number
# ---------------------------------------------------------------------------

PRINTED_CITATION = re.compile(r"(?<!PDF )\bpp?\. ([0-9ivxlcdm]+)(?:–([0-9ivxlcdm]+))?")
PDF_CITATION = re.compile(r"PDF pp?\. (\d+)(?:–(\d+))?")


def test_citing_a_passage_on_the_real_unnumbered_pages_shows_no_page_that_does_not_exist(answer):
    """Hard rule 2, against the committed index and canonical page labels.

    Body pages whose number did not print (PDF 66 and 67) have no printed label.
    A passage that touches them must be cited without one — never as 43 or 44,
    never as "None", never as a range with an invented end.
    """
    page_map = check_gold.load_page_map(check_gold.DEFAULT_PAGES)
    body_pdf = range(
        ask.settings.body_first_printed_page + ask.settings.body_pdf_page_offset,
        ask.settings.body_last_printed_page + ask.settings.body_pdf_page_offset + 1,
    )
    unnumbered = [pdf for pdf in body_pdf if page_map.pdf_to_label.get(pdf) is None]
    assert unnumbered == [66, 67]

    chunks = json.loads((ask.settings.index_dir / "chunks.json").read_text(encoding="utf-8"))
    touching = [
        c for c in chunks if any(c["pdf_page_start"] <= pdf <= c["pdf_page_end"] for pdf in unnumbered)
    ]
    assert touching, "expected at least one indexed passage on the unnumbered pages"

    for chunk in touching:
        item = ask.EvidenceItem(handle="E1", chunk=chunk, score=0.5)
        rendered = ask.render("FIXTURE: question?", answer(), [item], verbose=False)
        footnotes = footnote_block(rendered)
        diagnostics = rendered.split("RETRIEVAL DIAGNOSTICS", 1)[1]

        # What the reader is shown: the one label the passage has, and the PDF
        # page that really has no printed number — 67, not the passage's first page.
        shown = "p. 42 and PDF p. 67, which has no printed number [VERIFY]"
        assert shown in footnotes and shown in diagnostics
        stored = [label for label in (chunk["page_start"], chunk["page_end"]) if label is not None]

        for text in (footnotes, diagnostics):
            assert "None" not in text
            printed = [label for match in PRINTED_CITATION.findall(text) for label in match if label]
            assert printed == stored                              # only the stored label is printed
            assert all(label in page_map.label_to_pdf for label in printed)
            named = [int(n) for pair in PDF_CITATION.findall(text) for n in pair if n]
            assert named == chunk["pages_unresolved"]            # exactly the unnumbered pages
            assert all(page_map.pdf_to_label[n] is None for n in named)

        # The evaluation record follows the renderer: cited under the label shown.
        assert evaluate.cited_chunk_pages(chunk, page_map.pdf_to_label) == stored
        for label in evaluate.chunk_pages(chunk, page_map.pdf_to_label):
            assert label in page_map.label_to_pdf


def test_every_indexed_passage_cites_only_page_labels_that_exist():
    """No chunk in the committed index can render a printed page that is not in
    the canonical extraction, and every printed range it renders is resolved."""
    page_map = check_gold.load_page_map(check_gold.DEFAULT_PAGES)
    chunks = json.loads((ask.settings.index_dir / "chunks.json").read_text(encoding="utf-8"))
    assert len(chunks) > 100

    for chunk in chunks:
        phrase = ask.page_phrase(chunk)
        assert "None" not in phrase
        cited = [label for match in PRINTED_CITATION.findall(phrase) for label in match if label]
        for label in cited:
            assert label in page_map.label_to_pdf
        if "[VERIFY]" in phrase:
            named = [int(n) for pair in PDF_CITATION.findall(phrase) for n in pair if n]
            assert named and all(page_map.pdf_to_label[n] is None for n in named)
