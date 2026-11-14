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


def test_a_partly_resolved_passage_is_retrievable_by_its_label_but_cites_no_page(items, answer, pages_path):
    """A passage that runs from printed page 4 onto a page with no printed number."""
    pdf_to_label = check_gold.load_page_map(pages_path).pdf_to_label
    items[0].chunk.update(page_start="4", page_end=None, pdf_page_start=27, pdf_page_end=28)

    # Retrieval: the passage does cover printed page 4.
    assert evaluate.chunk_pages(items[0].chunk, pdf_to_label) == ["4"]

    # Citation: the renderer prints no page number for it, so no label is claimed.
    assert "[VERIFY]" in ask.footnote(1, items[0])
    assert evaluate.cited_chunk_pages(items[0].chunk, pdf_to_label) == []
    citations, cited_pages = evaluate._cited(answer(), items, pdf_to_label)
    assert citations == [{"handle": "E1", "chunk_id": items[0].chunk["chunk_id"], "pages": []}]
    assert cited_pages == []


def test_a_resolved_citation_carries_every_label_in_its_range(chunks, pages_path):
    pdf_to_label = check_gold.load_page_map(pages_path).pdf_to_label
    assert evaluate.cited_chunk_pages(chunks[5], pdf_to_label) == ["9", "10", "11"]


# ---------------------------------------------------------------------------
# The real index: passages on the PDF pages that carry no printed number
# ---------------------------------------------------------------------------

PRINTED_CITATION = re.compile(r"(?<!PDF )\bpp?\. ([0-9ivxlcdm]+)(?:–([0-9ivxlcdm]+))?")
PDF_CITATION = re.compile(r"PDF p\. (\d+)")


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

        # What the reader is shown: no printed page, a real PDF page, a request to verify.
        shown = f"page not printed on source page (PDF p. {chunk['pdf_page_start']}) [VERIFY]"
        assert shown in footnotes and shown in diagnostics

        for text in (footnotes, diagnostics):
            assert "None" not in text
            assert PRINTED_CITATION.findall(text) == []          # no printed page is claimed at all
            for pdf_page in PDF_CITATION.findall(text):
                assert int(pdf_page) in page_map.pdf_to_label    # the PDF page named exists

        # The evaluation record follows suit: findable by the label it has, citing none.
        assert evaluate.cited_chunk_pages(chunk, page_map.pdf_to_label) == []
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
        if not cited:
            assert phrase.endswith("[VERIFY]")
            assert int(PDF_CITATION.search(phrase).group(1)) in page_map.pdf_to_label
