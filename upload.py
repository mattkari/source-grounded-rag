"""What happens to an uploaded thesis — the stages of PLAN_V4 §6.

    receive -> analyse -> confirm identity -> approve / reject -> build index -> ready

Each document lives in one folder under the library directory:

    library/<document_id>/
      source.pdf            the upload, byte for byte
      record.json           state, identity, layout profile, how each value was reached
      canonical/pages.jsonl per-page extraction — written once (hard rule 7)
      audit.json            the audit the researcher approved or rejected
      index/                vectors.npy, chunks.json, manifest.json

Rules this module enforces:

  * Nothing is embedded, and no credit is spent, before the researcher has
    approved the audit and accepted the cost.
  * Nothing is cited before the researcher has confirmed the identity.
  * What is indexed is exactly what was audited: the extraction is re-derived
    at index time and must match the stored one, hash for hash.
  * Every stage outcome is written to the record. A failure is a recorded
    state with a reason; nothing is retried on its own (hard rule 9).
  * The built-in thesis is never touched from here.

These are plain functions over a folder so the web UI is a thin shell on top
of them and every rule can be tested without a browser.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pymupdf

import audit as audit_module
import identity
import ingest
import layout as layout_module
from config import settings
from documents import Document, LayoutProfile, default_document
from embeddings import active_model_name

SCHEMA_VERSION = 1

RECEIVED = "received"
AWAITING_REVIEW = "awaiting_review"
BLOCKED = "blocked"          # a hard stop: cannot be approved
REJECTED = "rejected"
APPROVED = "approved"
READY = "ready"

STATE_LABELS = {
    RECEIVED: "received — not yet analysed",
    AWAITING_REVIEW: "analysed — waiting for your review",
    BLOCKED: "cannot be used",
    REJECTED: "rejected",
    APPROVED: "approved — not yet indexed",
    READY: "ingested and audited — not evaluated",
}

ID_PREFIX = "thesis-"


class UploadRefused(Exception):
    """The upload cannot proceed. The message says why, in plain words."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def library_dir() -> Path:
    return settings.library_dir


def _folder(document_id: str) -> Path:
    if not document_id.startswith(ID_PREFIX) or "/" in document_id or ".." in document_id:
        raise UploadRefused(f"{document_id!r} is not an uploaded document.")
    return library_dir() / document_id


def _log(event: dict) -> None:
    """Every attempt is written down, including the ones that leave no folder."""
    library_dir().mkdir(parents=True, exist_ok=True)
    with (library_dir() / "upload_log.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"at": _now(), **event}, ensure_ascii=False) + "\n")


def _save(record: dict) -> dict:
    folder = _folder(record["document_id"])
    temporary = folder / "record.json.tmp"
    temporary.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(temporary, folder / "record.json")
    return record


def _step(record: dict, stage: str, outcome: str, detail: str = "") -> None:
    record["history"].append({"stage": stage, "outcome": outcome, "at": _now(), "detail": detail})


def load(document_id: str) -> dict:
    path = _folder(document_id) / "record.json"
    if not path.exists():
        raise UploadRefused(f"No uploaded document {document_id!r} in the library.")
    return json.loads(path.read_text(encoding="utf-8"))


def list_records() -> list[dict]:
    """Every uploaded document, oldest first."""
    if not library_dir().exists():
        return []
    records = []
    for folder in sorted(library_dir().iterdir()):
        if folder.is_dir() and (folder / "record.json").exists():
            records.append(json.loads((folder / "record.json").read_text(encoding="utf-8")))
    return sorted(records, key=lambda r: r.get("created_at", ""))


def _require(record: dict, *states: str) -> None:
    if record["state"] not in states:
        raise UploadRefused(
            f"This step is not available: the document is '{STATE_LABELS[record['state']]}'."
        )


# ---------------------------------------------------------------------------
# Stages 1–2: receive and pre-flight
# ---------------------------------------------------------------------------


def receive(pdf_bytes: bytes, filename: str) -> dict:
    """Store an uploaded PDF. Refuses, with a reason, anything that cannot be
    ingested; a refused upload leaves no folder behind."""
    digest = hashlib.sha256(pdf_bytes).hexdigest()
    document_id = ID_PREFIX + digest[:12]

    def refuse(reason: str) -> UploadRefused:
        _log({"event": "refused", "filename": filename, "sha256": digest, "reason": reason})
        return UploadRefused(reason)

    if not pdf_bytes.startswith(b"%PDF-"):
        raise refuse("This file is not a PDF.")

    builtin = default_document(settings)
    if builtin.pdf_path.exists() and hashlib.sha256(builtin.pdf_path.read_bytes()).hexdigest() == digest:
        raise refuse("This is the built-in thesis. It is already available and is kept frozen.")

    folder = library_dir() / document_id
    if folder.exists():
        state = STATE_LABELS[load(document_id)["state"]]
        raise refuse(
            f"This PDF is already in the library ({state}). Remove it first to ingest it again."
        )

    try:
        pdf = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:  # a file that starts like a PDF but cannot be opened
        raise refuse(f"This PDF could not be opened ({type(exc).__name__}).") from exc
    if pdf.is_encrypted or pdf.needs_pass:
        raise refuse("This PDF is password-protected. Remove the protection and upload it again.")
    if pdf.page_count == 0:
        raise refuse("This PDF has no pages.")
    if not any(pdf[i].get_text().strip() for i in range(pdf.page_count)):
        raise refuse(
            "This PDF has no text layer — it is a scan. Scanned documents need OCR, "
            "which is outside what this system does."
        )

    folder.mkdir(parents=True)
    (folder / "source.pdf").write_bytes(pdf_bytes)
    record = {
        "schema_version": SCHEMA_VERSION,
        "document_id": document_id,
        "source_filename": Path(filename).name,
        "sha256": digest,
        "pages_total": pdf.page_count,
        "state": RECEIVED,
        "created_at": _now(),
        "history": [],
        "layout": None,
        "layout_evidence": {},
        "flags": [],
        "identity_proposal": None,
        "identity": {"author": "", "year": "", "title": "", "short_title": "", "confirmed": False},
        "audit_summary": None,
        "audited_corpus_sha256": None,
        "review": None,
    }
    _step(record, "receive", "stored", f"{pdf.page_count} pages")
    _log({"event": "received", "filename": record["source_filename"], "document_id": document_id})
    return _save(record)


# ---------------------------------------------------------------------------
# Stages 3–6: measure, dry run, audit, identity proposal
# ---------------------------------------------------------------------------


def _provisional_document(record: dict, layout: LayoutProfile) -> Document:
    """The document as the pipeline needs it. Identity may still be unconfirmed:
    it is not part of any chunk, only of the embedding header and the citation."""
    folder = _folder(record["document_id"])
    who = record["identity"]
    return Document(
        document_id=record["document_id"],
        author=who["author"],
        year=who["year"],
        title=who["title"],
        short_title=who["short_title"],
        layout=layout,
        pdf_path=folder / "source.pdf",
        canonical_dir=folder / "canonical",
        index_dir=folder / "index",
        builtin=False,
    )


def extract_and_chunk(document: Document):
    """The real extractor and chunker, run with the document's own profile."""
    pages = ingest.extract_document(document.pdf_path, document.layout)
    segments = ingest.build_segments(pages, document.layout)
    records = ingest.build_chunks(segments, document)
    return pages, segments, records


def analyse_pdf(pdf_path, document_id: str) -> dict:
    """Measure, dry-run and audit one PDF without writing anything.

    Shared by the upload stage below and by scripts/measure_thesis.py, so the
    command-line trial and the web UI cannot drift apart.
    """
    measurement = layout_module.measure(pdf_path)
    if measurement.layout is None:
        return {"measurement": measurement, "layout": None}

    provisional = Document(
        document_id=document_id, author="", year="", title="", short_title="",
        layout=measurement.layout, pdf_path=Path(pdf_path),
        canonical_dir=Path(pdf_path).parent, index_dir=Path(pdf_path).parent,
    )
    pages = ingest.extract_document(pdf_path, measurement.layout)
    chapters = sorted({s.chapter for s in ingest.build_segments(pages, measurement.layout) if s.chapter})
    apparatus = layout_module.apparatus_prefixes(chapters)
    measurement.evidence["apparatus_chapter_prefixes"] = {
        "rule": "chapters whose printed title marks a bibliography or reference list",
        "chapters_found": len(chapters),
        "marked_as_reference_apparatus": list(apparatus),
    }
    final_layout = dataclasses.replace(measurement.layout, apparatus_chapter_prefixes=apparatus)
    document = dataclasses.replace(provisional, layout=final_layout)

    pages, segments, records = extract_and_chunk(document)
    rows = ingest.canonical_rows(pages)
    result = audit_module.audit(pdf_path, rows, records, final_layout)
    return {
        "measurement": measurement,
        "layout": final_layout,
        "pages": pages,
        "rows": rows,
        "segments": segments,
        "records": records,
        "audit": result,
        "corpus_sha256": ingest.corpus_hash(records),
    }


def analyse(document_id: str) -> dict:
    """Stages 3–6. Ends in `awaiting_review`, or in `blocked` with the reason."""
    record = load(document_id)
    _require(record, RECEIVED)
    folder = _folder(document_id)

    try:
        analysis = analyse_pdf(folder / "source.pdf", document_id)
    except Exception as exc:  # recorded, not hidden: the document cannot go further
        record["state"] = BLOCKED
        record["flags"] = [f"The analysis could not be completed ({type(exc).__name__})."]
        _step(record, "measure", "failed", f"{type(exc).__name__}: {' '.join(str(exc).split())[:300]}")
        _save(record)
        raise UploadRefused(
            f"This thesis could not be analysed ({type(exc).__name__}). It has been marked as unusable."
        ) from exc
    measurement = analysis["measurement"]
    record["flags"] = list(measurement.flags)
    record["layout_evidence"] = measurement.evidence

    if analysis["layout"] is None:
        record["state"] = BLOCKED
        _step(record, "measure", "stopped", "no text to measure")
        return _save(record)

    record["layout"] = analysis["layout"].to_json()
    _step(record, "measure", "done", f"{len(measurement.flags)} flag(s)")

    ingest.write_canonical(analysis["pages"], folder / "canonical", exclusive=True)
    _step(record, "dry run", "done", f"{len(analysis['records'])} passages")

    result = analysis["audit"]
    (folder / "audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    record["audit_summary"] = {
        "pages": {k: v for k, v in result["pages"].items() if isinstance(v, int)},
        "chunks_total": result["chunks"]["total"],
        "hard_stops": result["hard_stops"],
    }
    record["audited_corpus_sha256"] = analysis["corpus_sha256"]
    _step(record, "audit", "stopped" if result["hard_stops"] else "done", "; ".join(result["hard_stops"]))

    record["identity_proposal"] = identity.propose(folder / "source.pdf")
    _step(record, "identity", "proposed", "waiting for confirmation")

    record["state"] = BLOCKED if result["hard_stops"] else AWAITING_REVIEW
    return _save(record)


def read_audit(document_id: str) -> dict | None:
    path = _folder(document_id) / "audit.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


# ---------------------------------------------------------------------------
# Stage 6–7: the researcher confirms identity and decides
# ---------------------------------------------------------------------------


def default_short_title(author: str, year: str, title: str) -> str:
    return f"{author} ({year}), {title}"


def confirm_identity(document_id: str, *, author: str, year: str, title: str, short_title: str = "") -> dict:
    """Record the identity the researcher confirmed. Until this is done the
    document cannot be approved, so an unconfirmed name can never be cited."""
    record = load(document_id)
    _require(record, AWAITING_REVIEW)
    author, year, title = author.strip(), year.strip(), title.strip()
    if not author or not title:
        raise UploadRefused("Author and title are both needed before the thesis can be cited.")
    if not (year.isdecimal() and len(year) == 4):
        raise UploadRefused("The year must be four digits, as printed on the title page.")
    record["identity"] = {
        "author": author,
        "year": year,
        "title": title,
        "short_title": short_title.strip() or default_short_title(author, year, title),
        "confirmed": True,
        "confirmed_at": _now(),
        "confirmed_via": "researcher, in the web UI",
    }
    _step(record, "identity", "confirmed", "by the researcher")
    return _save(record)


def approve(document_id: str) -> dict:
    record = load(document_id)
    _require(record, AWAITING_REVIEW)
    if not record["identity"]["confirmed"]:
        raise UploadRefused("Confirm the author, year and title before approving.")
    record["state"] = APPROVED
    record["review"] = {"decision": "approved", "at": _now(), "reason": ""}
    _step(record, "review", "approved", "by the researcher")
    return _save(record)


def reject(document_id: str, reason: str = "") -> dict:
    record = load(document_id)
    _require(record, AWAITING_REVIEW)
    record["state"] = REJECTED
    record["review"] = {"decision": "rejected", "at": _now(), "reason": reason.strip()}
    _step(record, "review", "rejected", reason.strip())
    return _save(record)


# ---------------------------------------------------------------------------
# Stages 8–10: cost, index, ready
# ---------------------------------------------------------------------------


def as_document(record: dict) -> Document:
    """The record as a `Document` the pipeline can use."""
    if record["layout"] is None:
        raise UploadRefused("This document has no measured layout.")
    return _provisional_document(record, LayoutProfile.from_json(record["layout"]))


def _audited_chunks(record: dict):
    """Re-derive the chunks and prove they are the ones that were audited."""
    document = as_document(record)
    pages, segments, records = extract_and_chunk(document)
    stored = [
        json.loads(line)
        for line in (document.canonical_dir / "pages.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    if ingest.canonical_rows(pages) != stored or ingest.corpus_hash(records) != record["audited_corpus_sha256"]:
        raise UploadRefused(
            "The extraction no longer matches the one that was audited and approved. "
            "Nothing was indexed. Remove this thesis and upload it again."
        )
    return document, pages, segments, records


def estimate_cost(document_id: str) -> dict:
    """What embedding this thesis will send. A price is shown only if one is configured."""
    record = load(document_id)
    _require(record, APPROVED)
    document, _, _, records = _audited_chunks(record)
    tokens = sum(ingest.ntokens(ingest.embed_text(r, document)) for r in records)
    price = settings.embedding_price_per_mtok
    return {
        "passages": len(records),
        "tokens": tokens,
        "embedding_model": active_model_name(),
        "price_per_million_tokens": price,
        "estimated_cost": None if price is None else round(tokens / 1_000_000 * price, 4),
    }


def build_index(document_id: str, *, cost_accepted: bool) -> dict:
    """Embed and index an approved thesis. A provider error leaves the document
    approved and un-indexed, with the failure recorded; calling this again is a
    deliberate new attempt by the researcher, not a retry."""
    record = load(document_id)
    _require(record, APPROVED)
    if not cost_accepted:
        raise UploadRefused("Embedding spends API credit. Accept the cost estimate first.")

    document, pages, segments, records = _audited_chunks(record)
    try:
        vectors = ingest.embed_all(records, document, progress=False)
    except (Exception, SystemExit) as exc:
        _step(record, "index", "failed", f"{type(exc).__name__}: {' '.join(str(exc).split())[:300]}")
        _save(record)
        raise UploadRefused(
            f"Embedding failed ({type(exc).__name__}). Nothing was indexed. "
            "The thesis is still approved; you can try this step again."
        ) from exc

    manifest = ingest.build_manifest(
        document, pages, segments, records, vectors,
        ingest.text_but_no_body_pages(document.pdf_path, pages),
    )
    ingest.write_index(document.index_dir, records, vectors, manifest)
    record["state"] = READY
    _step(record, "index", "done", f"{len(records)} passages embedded with {manifest['embedding_model']}")
    return _save(record)


def ready_documents() -> list[Document]:
    """Uploaded theses that can be queried, oldest first."""
    return [as_document(record) for record in list_records() if record["state"] == READY]


def find_document(document_id: str | None) -> Document:
    """The built-in thesis for None or its own id; otherwise a ready upload."""
    builtin = default_document(settings)
    if document_id is None or document_id == builtin.document_id:
        return builtin
    record = load(document_id)
    if record["state"] != READY:
        raise UploadRefused(
            f"{document_id} cannot be queried yet: it is '{STATE_LABELS[record['state']]}'."
        )
    return as_document(record)


# ---------------------------------------------------------------------------
# Removal
# ---------------------------------------------------------------------------


def remove(document_id: str) -> None:
    """Delete an uploaded thesis: its PDF, its extraction and its index.

    Run records are kept; runs.py reports their citations as unresolvable.
    The built-in thesis is not in the library and cannot be removed.
    """
    if document_id == default_document(settings).document_id:
        raise UploadRefused("The built-in thesis is frozen and cannot be removed.")
    folder = _folder(document_id)
    if not folder.exists():
        raise UploadRefused(f"No uploaded document {document_id!r} in the library.")
    shutil.rmtree(folder)
    _log({"event": "removed", "document_id": document_id})
