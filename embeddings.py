"""The embedding role, isolated behind one function.

DEMO SCOPE: this is the seed of the `EmbeddingProvider` interface in
PLAN_V2 §21 — deliberately minimal. It exists as its own module because
ingest.py and ask.py must embed with the *same* model, and because the
provider is the one thing likely to be swapped (PLAN_V2 §8.3 names
BAAI/bge-m3 as the offline alternative and the Sprint 3 swap-test).

An index built with model A can never be queried with model B; ask.py
enforces that against index/manifest.json.
"""

from __future__ import annotations

import numpy as np

from config import settings

# BGE-family models expect an instruction prefix on the query side only.
_BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

_local_model = None


def _load_local():
    global _local_model
    if _local_model is None:
        from sentence_transformers import SentenceTransformer

        _local_model = SentenceTransformer(settings.local_embedding_model)
    return _local_model


def _normalise(matrix: np.ndarray) -> np.ndarray:
    """Unit length at write time; similarity is then a plain dot product."""
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (matrix / norms).astype(np.float32)


def embed_texts(texts: list[str], *, is_query: bool = False, progress: bool = False) -> np.ndarray:
    provider = settings.embedding_provider

    if provider == "openai":
        from openai import OpenAI

        client = OpenAI(api_key=settings.openai_api_key)
        vectors: list[list[float]] = []
        batch = settings.embedding_batch_size
        for i in range(0, len(texts), batch):
            response = client.embeddings.create(
                model=settings.embedding_model, input=texts[i : i + batch]
            )
            vectors.extend(item.embedding for item in response.data)
            if progress:
                print(f"  embedded {min(i + batch, len(texts))}/{len(texts)}", flush=True)
        return _normalise(np.asarray(vectors, dtype=np.float32))

    if provider == "local":
        model = _load_local()
        prepared = texts
        if is_query and "bge" in settings.local_embedding_model.lower():
            prepared = [_BGE_QUERY_PREFIX + t for t in texts]
        matrix = model.encode(
            prepared,
            batch_size=settings.embedding_batch_size,
            show_progress_bar=progress,
            convert_to_numpy=True,
        )
        return _normalise(np.asarray(matrix, dtype=np.float32))

    raise RuntimeError(f"Unknown EMBEDDING_PROVIDER: {provider!r}")


def active_model_name() -> str:
    if settings.embedding_provider == "openai":
        return settings.embedding_model
    return settings.local_embedding_model
