"""Durable run records — every query written to disk as evidence.

The web UI keeps conversation state in `st.session_state`, which lives only as
long as a browser session: a refresh loses it. That is fine for chat, and wrong
for research. PLAN_V2 treats runs as evidence, so a question asked yesterday
must still be inspectable today.

One record per query, appended as JSON Lines. The shape deliberately matches
`ask.py --json` so a run captured from the web UI and one captured from the CLI
are the same artefact.

What is NOT stored, and why:

  * No answer text is treated as authoritative on reload. Page numbers and
    citations are re-resolved from `index/chunks.json` at render time via
    `ask.page_phrase` / `ask.footnote`, so a stale record can never put a page
    number on screen that the canonical extraction does not support (hard rule 2).
  * No credentials, and no environment dump. Only the question, the model's
    structured result, evidence chunk ids with their scores, and the validation
    outcome.
  * Chunk *text* is not duplicated. Records carry `chunk_id` and the index
    remains the single source of provenance (hard rule 7).

A record whose chunk ids no longer exist in the index — because the corpus was
re-ingested — is reported as unresolvable rather than rendered against the wrong
document. Silently matching it to a different corpus would be a provenance lie.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from config import settings

SCHEMA_VERSION = 1


def _path() -> Path:
    return settings.runs_path


def append(
    *,
    question: str,
    result: dict,
    items: list,
    failures: list[str],
    prompt_hash: str,
    manifest: dict,
    error: str | None = None,
) -> dict:
    """Append one run record and return it.

    Never raises into the caller's request path: failing to persist history must
    not lose the answer the user is waiting for. A write failure is reported in
    the returned record so the UI can say so honestly.
    """
    record = {
        "schema_version": SCHEMA_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "question": question,
        "model": settings.llm_model,
        "provider": settings.llm_provider,
        "embedding_model": manifest.get("embedding_model"),
        "corpus_text_sha256": manifest.get("corpus_text_sha256"),
        "document_id": manifest.get("document_id"),
        "prompt_sha256_12": prompt_hash,
        "evidence": [
            {"handle": i.handle, "chunk_id": i.chunk["chunk_id"], "score": float(i.score)}
            for i in items
        ],
        "result": result,
        "validation_failures": list(failures),
    }
    if error:
        record["error"] = error

    try:
        path = _path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        record["_persist_error"] = f"{type(exc).__name__}: {exc}"

    return record


def load(limit: int | None = None) -> list[dict]:
    """Newest first. A corrupt line is skipped, not fatal — one bad write must
    not make the whole history unreadable."""
    path = _path()
    if not path.exists():
        return []

    records: list[dict] = []
    try:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []

    records.reverse()
    return records[:limit] if limit else records


def rehydrate(record: dict, chunks: list[dict]):
    """Rebuild EvidenceItems from stored chunk ids against the CURRENT index.

    Returns (items, unresolved_ids). Provenance is re-read from the index rather
    than trusted from the record, so citations rendered from history are subject
    to exactly the same guarantees as a live answer.
    """
    import ask

    by_id = {c["chunk_id"]: c for c in chunks}
    items, unresolved = [], []
    for entry in record.get("evidence", []):
        chunk = by_id.get(entry["chunk_id"])
        if chunk is None:
            unresolved.append(entry["chunk_id"])
            continue
        items.append(
            ask.EvidenceItem(handle=entry["handle"], chunk=chunk, score=entry["score"])
        )
    return items, unresolved


def as_outcome(record: dict, chunks: list[dict]):
    """A stored record rendered through the same path as a live answer.

    Returns (QueryOutcome, unresolved_chunk_ids).
    """
    import ask

    items, unresolved = rehydrate(record, chunks)
    outcome = ask.QueryOutcome(
        question=record["question"],
        result=record["result"],
        items=items,
        failures=record.get("validation_failures", []),
        prompt_hash=record.get("prompt_sha256_12", ""),
    )
    return outcome, unresolved


def export_jsonl() -> str:
    """The whole history as JSONL text, for download."""
    path = _path()
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def clear() -> bool:
    """Delete the history file. Returns True when it is gone afterwards."""
    path = _path()
    try:
        path.unlink(missing_ok=True)
        return True
    except OSError:
        return not path.exists()


def count() -> int:
    return len(load())
