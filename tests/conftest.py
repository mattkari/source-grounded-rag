"""Shared fixtures for the offline suite (PLAN_V3 §6).

Nothing in this directory reaches a network, needs an API key, or contains a
word of the thesis. Every passage and question here is synthetic and says so
("FIXTURE ...").

Two boundaries are replaced, and only two:

  * `ask.call_model` — the generation model. Each test that needs it supplies
    its own stand-in, so the scripted behaviour is visible in the test.
  * `ask.embed_texts` — the embedding provider, replaced by a deterministic
    hashed bag-of-words (`fake_embed_texts`).

Everything between them is the real code: index loading, the cosine ranking in
`ask.retrieve`, `ask.validate`, citation resolution and rendering.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
import socket

import numpy as np
import pytest

import ask
import embeddings

EMBED_DIM = 64


def fake_embed_texts(texts, *, is_query: bool = False, progress: bool = False) -> np.ndarray:
    """Deterministic, offline, unit-normalised: one hashed dimension per word."""
    matrix = np.zeros((len(texts), EMBED_DIM), dtype=np.float32)
    for row, text in enumerate(texts):
        for token in re.findall(r"[a-z]+", text.lower()):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            matrix[row, int.from_bytes(digest[:4], "big") % EMBED_DIM] += 1.0
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


def _chunk(n, *, section, text, page_start, page_end, pdf_start, pdf_end, chapter="FIXTURE chapter", kind="source"):
    return {
        "chunk_id": f"fixture-document::{n:05d}::fixture",
        "document_id": "fixture-document",
        "kind": kind,
        "chapter": chapter,
        "section": section,
        "page_start": page_start,
        "page_end": page_end,
        "pdf_page_start": pdf_start,
        "pdf_page_end": pdf_end,
        "pages_unresolved": [] if page_start is not None else [pdf_start],
        "token_count": len(text.split()),
        "text": text,
    }


# Page labels follow the layout the checker expects: printed + 23 = pdf page.
FIXTURE_CHUNKS = [
    _chunk(0, section="FIXTURE lamp oil ledger", page_start="3", page_end="3", pdf_start=26, pdf_end=26,
           text="FIXTURE passage: the lighthouse keeper logged lamp oil deliveries every winter."),
    _chunk(1, section="FIXTURE grafting calendar", page_start="7", page_end="8", pdf_start=30, pdf_end=31,
           text="FIXTURE passage: the orchard grafting calendar lists apple and pear rootstock."),
    _chunk(2, section="FIXTURE tramway timetable", page_start="12", page_end="12", pdf_start=35, pdf_end=35,
           text="FIXTURE passage: the tramway timetable changed when the viaduct opened."),
    _chunk(3, section="FIXTURE unnumbered plate", page_start=None, page_end=None, pdf_start=28, pdf_end=28,
           text="FIXTURE passage: an unnumbered plate shows the harbour chart."),
    _chunk(4, section=None, chapter="Bibliography", kind="apparatus",
           page_start="15", page_end="15", pdf_start=38, pdf_end=38,
           text="FIXTURE reference list entry: Example, A. A synthetic title about beekeeping."),
    _chunk(5, section="FIXTURE canal survey", page_start="9", page_end="11", pdf_start=32, pdf_end=34,
           text="FIXTURE passage: the canal survey measured locks, weirs and towpaths."),
]

_ROMAN = ["i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x", "xi", "xii", "xiii", "xiv",
          "xv", "xvi", "xvii", "xviii", "xix", "xx", "xxi", "xxii"]


def fixture_page_rows() -> list[dict]:
    """A synthetic document shaped like the real one: an unnumbered title page,
    roman front matter, a body at pdf = printed + 23 with one page whose number
    did not print (pdf 28), and — after the body's pdf range — an appendix that
    reuses the labels i and ii."""
    rows = [{"pdf_page": 1, "printed_page": None}]
    rows += [{"pdf_page": 2 + i, "printed_page": label} for i, label in enumerate(_ROMAN)]
    rows += [{"pdf_page": 23 + n, "printed_page": None if n == 5 else str(n)} for n in range(1, 21)]
    for row in rows:
        row["running_header"] = None
    rows += [
        {"pdf_page": 282, "printed_page": "i", "running_header": "Appendix"},
        {"pdf_page": 283, "printed_page": "ii", "running_header": "Appendix"},
    ]
    for row in rows:
        row["text"] = "FIXTURE page text that the checker must never print."
    return rows


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """No test may reach a network or hold a credential."""

    def refuse(*args, **kwargs):
        raise AssertionError("an offline test attempted a network connection")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(ask, "_get_client", refuse)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


@pytest.fixture
def chunks() -> list[dict]:
    return [dict(chunk) for chunk in FIXTURE_CHUNKS]


@pytest.fixture
def items(chunks) -> list[ask.EvidenceItem]:
    """Evidence handles E1..E6 over the fixture chunks, in file order."""
    return [
        ask.EvidenceItem(handle=f"E{i + 1}", chunk=chunk, score=round(0.9 - 0.1 * i, 2))
        for i, chunk in enumerate(chunks)
    ]


@pytest.fixture
def answer():
    """Factory for a model payload that satisfies the contract and cites [E1]."""

    def build(**overrides) -> dict:
        payload = {
            "evidence_sufficiency": "sufficient",
            "answer": "FIXTURE answer about the lamp oil ledger [E1].",
            "limitations": [],
            "ai_interpretation": [],
            "unsupported_by_evidence": [],
            "citations_used": ["E1"],
        }
        payload.update(overrides)
        return payload

    return build


@pytest.fixture
def pages_path(tmp_path):
    path = tmp_path / "pages.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in fixture_page_rows()), encoding="utf-8")
    return path


@pytest.fixture
def fixture_index(tmp_path, monkeypatch, chunks):
    """A real on-disk index of the fixture chunks, loaded by the real
    `ask.load_index`, with the embedding provider replaced by the offline fake."""
    index_dir = tmp_path / "index"
    index_dir.mkdir()
    np.save(index_dir / "vectors.npy", fake_embed_texts([c["text"] for c in chunks]))
    (index_dir / "chunks.json").write_text(json.dumps(chunks), encoding="utf-8")
    manifest = {
        "document_id": "fixture-document",
        # Whatever config names — a test never writes a model string (hard rule 1).
        "embedding_model": embeddings.active_model_name(),
        "corpus_text_sha256": "fixture-corpus-hash",
        "chunk_count": len(chunks),
    }
    (index_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    monkeypatch.setattr(ask, "settings", dataclasses.replace(ask.settings, index_dir=index_dir))
    monkeypatch.setattr(ask, "embed_texts", fake_embed_texts)
    return manifest
