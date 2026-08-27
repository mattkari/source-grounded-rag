"""Single validated settings object, read once at startup.

DEMO SCOPE: provider/model choice is hard-coded here deliberately. The full
provider abstraction (EmbeddingProvider / GenerationProvider interfaces,
EMBEDDING_PROVIDER / LLM_PROVIDER env switching) comes later — see
docs/plans/PLAN_V2.md §21. This module is the ONLY place a vendor model
string may appear (CLAUDE.md hard rule 1).

Credentials come from the environment only (hard rule 3).

This module also carries the DOCUMENT PROFILE and the LAYOUT PROFILE. The
layout profile holds the constants that are true of one particular PDF —
type sizes, header/footer band positions, which printed feature carries the
chapter. They live here rather than in ingest.py so that swapping the corpus
is a settings change plus a measurement run, not a code edit. Every value
below was measured from the PDF named in `pdf_path`; none is a guess. When
you change the document, re-measure them.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Settings:
    # --- paths -------------------------------------------------------------
    pdf_path: Path = ROOT / "data" / "karimov-2017-quranic-justice.pdf"
    index_dir: Path = ROOT / "index"
    canonical_dir: Path = ROOT / "data" / "canonical"
    prompt_path: Path = ROOT / "prompts" / "system_grounded_v2.md"

    # --- document identity (from the title page, not inferred) -------------
    # Taken from the title page, not from the PDF metadata: that metadata
    # names a second author inherited from the template it was written in,
    # and an unverified field is not identity (hard rule 6).
    document_id: str = "karimov-2017-quranic-justice"
    document_author: str = "Karimov, D."
    document_year: str = "2017"
    document_title: str = (
        "The Qur’anic Concept of Justice (al-ʿAdl) from a Nursian Perspective"
    )
    document_short_title: str = "Karimov (2017), Qur’anic Concept of Justice thesis"

    # --- layout profile — MEASURED from this PDF, never guessed -------------
    # Body text is 12.0pt TimesNewRomanPSMT. Block quotations — the Qur’anic
    # passages the whole argument is built on — are 11.0pt and indented, so
    # the threshold sits at 11.0 to keep them. The footnote apparatus is
    # 9-10pt and its reference markers 7pt, all of which this drops.
    body_min_size: float = 11.0

    # Running headers print the chapter title at y=36; body text starts at
    # y=71 at the earliest.
    header_band_y: float = 60.0

    # Printed page numbers sit at y0=794. The lowest-starting genuine block is
    # a footnote at y0=757. Getting this wrong costs every citation its page.
    footnote_band_y: float = 770.0

    # Heading scale, measured: 16pt bold = chapter title, 14pt bold = the
    # "Chapter N" line, 12pt bold = numbered section headings. The 12pt
    # headings are below heading_min_size, so the bold face is what
    # distinguishes them from body text.
    heading_min_size: float = 13.0
    heading_fonts: tuple[str, ...] = ("TimesNewRomanPS-BoldMT",)
    chapter_heading_min_size: float = 20.0
    section_heading_min_size: float = 15.0

    # Which printed feature carries the chapter:
    #   "heading"        — chapter titles printed at chapter_heading_min_size
    #   "running_header" — the header printed on every page
    # Both read structure the document itself prints; neither infers one.
    # This thesis prints the chapter title as a running header on every page,
    # which is the stronger signal: it is stored provenance, not inference.
    chapter_source: str = "running_header"

    # Chapters indexed as reference APPARATUS rather than as source claims.
    # A bibliography entry asserts nothing about the thesis's subject: it can
    # support "the thesis cites this work" and nothing else. Tagging rather
    # than excluding keeps bibliographic questions answerable while stopping a
    # cited title from being read as a claim the author made (hard rule 5).
    # The tag reaches the model in the evidence block and the reader in the
    # citation, so neither can mistake a reference list for an argument.
    apparatus_chapter_prefixes: tuple[str, ...] = ("Bibliography",)

    # --- embedding role ----------------------------------------------------
    # "openai" (hosted) or "local" (sentence-transformers, offline).
    embedding_provider: str = os.environ.get("EMBEDDING_PROVIDER", "openai")
    embedding_model: str = "text-embedding-3-large"
    local_embedding_model: str = os.environ.get("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
    embedding_batch_size: int = 64

    # --- generation role ---------------------------------------------------
    # Anthropic offers no embeddings endpoint, so the two roles necessarily
    # use different vendors. That is a real constraint, not an oversight.
    llm_provider: str = "anthropic"
    llm_model: str = "claude-opus-5"
    llm_max_tokens: int = 16000

    # --- chunking ----------------------------------------------------------
    chunk_target_tokens: int = 700
    chunk_max_tokens: int = 900
    chunk_overlap_tokens: int = 100
    chunk_min_tokens: int = 40

    # --- retrieval ---------------------------------------------------------
    top_k: int = 5

    @property
    def openai_api_key(self) -> str:
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY is not set in the environment.")
        return key

    @property
    def anthropic_api_key(self) -> str:
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set in the environment.")
        return key


settings = Settings()
