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
    pdf_path: Path = ROOT / "data" / "leung-2019-ai-governance.pdf"
    index_dir: Path = ROOT / "index"
    canonical_dir: Path = ROOT / "data" / "canonical"
    prompt_path: Path = ROOT / "prompts" / "system_grounded_v1.md"

    # --- document identity (from the title page, not inferred) -------------
    document_id: str = "leung-2019-ai-governance"
    document_author: str = "Leung, J."
    document_year: str = "2019"
    document_title: str = (
        "Who Will Govern Artificial Intelligence? Learning from the History "
        "of Strategic Politics in Emerging Technologies"
    )
    document_short_title: str = "Leung (2019), Who Will Govern AI? thesis"

    # --- layout profile — MEASURED from this PDF, never guessed -------------
    # Body text is 12.0pt Garamond. Footnotes are 10.0pt and carry ~22% of the
    # document's characters; filtering at 11pt drops the whole footnote
    # apparatus, which is what keeps reference lists out of quotable evidence.
    body_min_size: float = 11.0

    # This thesis prints NO running header — there is no text above y=60 on any
    # page. The band is kept (and stays empty) so that a document which does
    # print one still records it as provenance.
    header_band_y: float = 60.0

    # Printed page numbers sit at y0=780; the highest genuine body block starts
    # at y0=755. 770 separates them. Getting this wrong costs every citation:
    # at 780 the number is read as body text and no page resolves at all.
    footnote_band_y: float = 770.0

    # Heading scale, measured: 24pt = chapter, 16pt = section, 14pt bold =
    # subsection, 12pt bold = sub-subsection.
    heading_min_size: float = 13.0
    heading_fonts: tuple[str, ...] = ("Garamond-Bold",)
    chapter_heading_min_size: float = 20.0
    section_heading_min_size: float = 15.0

    # Which printed feature carries the chapter:
    #   "heading"        — chapter titles printed at chapter_heading_min_size
    #   "running_header" — the header printed on every page
    # Both read structure the document itself prints; neither infers one.
    chapter_source: str = "heading"

    # Chapters excluded from the evidence index. Reference apparatus is not a
    # source claim (hard rule 5), and a 64-page bibliography would otherwise
    # surface reference lists as quotable evidence. Excluded pages are still
    # extracted into the canonical record and are listed in the manifest —
    # dropped from evidence, never silently discarded.
    excluded_chapter_prefixes: tuple[str, ...] = ("Appendix B",)

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
