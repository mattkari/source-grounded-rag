"""Single validated settings object, read once at startup.

DEMO SCOPE: provider/model choice is hard-coded here deliberately. The full
provider abstraction (EmbeddingProvider / GenerationProvider interfaces,
EMBEDDING_PROVIDER / LLM_PROVIDER env switching) comes later — see
docs/plans/PLAN_V2.md §21. This module is the ONLY place a vendor model
string may appear (CLAUDE.md hard rule 1).

Credentials come from the environment only (hard rule 3).
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
    pdf_path: Path = ROOT / "data" / "thesis.pdf"
    index_dir: Path = ROOT / "index"
    canonical_dir: Path = ROOT / "data" / "canonical"
    prompt_path: Path = ROOT / "prompts" / "system_grounded_v1.md"

    # --- document identity (from the title page, not inferred) -------------
    document_id: str = "sonmez-2014-transparency"
    document_author: str = "Sönmez, M."
    document_year: str = "2014"
    document_title: str = (
        "The Role of Better Transparency Law in Corporate Governance and "
        "Financial Markets, and Its Practicability in Legal Systems: "
        "A Comparative Study Between the EU and Turkey"
    )
    document_short_title: str = "Sönmez (2014), Transparency Law thesis"

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
