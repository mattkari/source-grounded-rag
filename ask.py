"""Ask a question against the authorised research collection.

    python ask.py "What were the main causes of the Imar Bank scandal?"
    python ask.py --verbose-provenance "..."      # show chunk ids + verbatim passages
    python ask.py --json "..."                    # machine-readable run record

The model sees opaque evidence handles ([E1], [E2], ...) and NEVER sees a page
number. Page numbers in the output are resolved by this renderer from stored
provenance, so a page number that is not in the canonical extraction cannot
reach the output (hard rule 2 / PLAN_V2 §11.2 P2).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass

import numpy as np
from anthropic import Anthropic

from config import settings
from embeddings import active_model_name, embed_texts

MARKER_RE = re.compile(r"\[E(\d+)\]")
PAGE_CLAIM_RE = re.compile(r"\b(?:p{1,2})\.\s*\d+", re.IGNORECASE)
SUPERSCRIPTS = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")

ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "evidence_sufficiency": {
            "type": "string",
            "enum": ["sufficient", "partial", "insufficient"],
        },
        "answer": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "limitations": {"type": "array", "items": {"type": "string"}},
        "ai_interpretation": {"type": "array", "items": {"type": "string"}},
        "unsupported_by_evidence": {"type": "array", "items": {"type": "string"}},
        "citations_used": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "evidence_sufficiency",
        "answer",
        "limitations",
        "ai_interpretation",
        "unsupported_by_evidence",
        "citations_used",
    ],
    "additionalProperties": False,
}


@dataclass
class EvidenceItem:
    handle: str          # "E1"
    chunk: dict          # full provenance record
    score: float         # retrieval diagnostic — NEVER a confidence figure


# ---------------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------------


def load_index() -> tuple[np.ndarray, list[dict], dict]:
    vec_path = settings.index_dir / "vectors.npy"
    chunk_path = settings.index_dir / "chunks.json"
    manifest_path = settings.index_dir / "manifest.json"
    if not vec_path.exists():
        raise SystemExit("No index found. Run:  python ingest.py")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    # An index built with model A can never be queried with model B.
    if manifest["embedding_model"] != active_model_name():
        raise SystemExit(
            f"Index/model mismatch — refusing to start.\n"
            f"  index was built with : {manifest['embedding_model']}\n"
            f"  current setting is   : {active_model_name()}\n"
            f"Re-run ingest.py to rebuild the index."
        )
    return (
        np.load(vec_path),
        json.loads(chunk_path.read_text(encoding="utf-8")),
        manifest,
    )


def retrieve(question: str, vectors: np.ndarray, chunks: list[dict], k: int) -> list[EvidenceItem]:
    query = embed_texts([question], is_query=True)[0]
    scores = vectors @ query  # both sides unit-normalised -> cosine
    order = np.argsort(-scores)[:k]
    return [
        EvidenceItem(handle=f"E{i + 1}", chunk=chunks[j], score=float(scores[j]))
        for i, j in enumerate(order)
    ]


# ---------------------------------------------------------------------------
# Model-facing evidence (no page numbers, by construction)
# ---------------------------------------------------------------------------


def is_apparatus(chunk: dict) -> bool:
    """Older indexes predate the tag; absent means an ordinary source passage."""
    return chunk.get("kind") == "apparatus"


def render_evidence_block(items: list[EvidenceItem]) -> str:
    lines = []
    for item in items:
        c = item.chunk
        header = f"[{item.handle}] {settings.document_short_title}"
        if c["chapter"]:
            header += f" — Chapter: {c['chapter']}"
        if c["section"]:
            header += f" — Section: {c['section']}"
        if is_apparatus(c):
            # The model must not read a cited title as a claim the author made.
            header += (
                " — REFERENCE APPARATUS: a list of works cited, not the author's"
                " argument. Supports only what the thesis cites, never what it claims."
            )
        lines.append(f"{header}\n\"{c['text']}\"")
    return "\n\n".join(lines)


_client: Anthropic | None = None
_prompt_cache: tuple[str, str] | None = None


def _get_client() -> Anthropic:
    """One client for the process — main.py's loop must not rebuild it per question."""
    global _client
    if _client is None:
        _client = Anthropic(api_key=settings.anthropic_api_key)
    return _client


def _get_prompt() -> tuple[str, str]:
    global _prompt_cache
    if _prompt_cache is None:
        text = settings.prompt_path.read_text(encoding="utf-8")
        _prompt_cache = (text, hashlib.sha256(text.encode("utf-8")).hexdigest()[:12])
    return _prompt_cache


def call_model(question: str, items: list[EvidenceItem]) -> tuple[dict, str]:
    system_prompt, prompt_hash = _get_prompt()
    user_content = (
        f"EVIDENCE\n========\n{render_evidence_block(items)}\n\n"
        f"QUESTION\n========\n{question}"
    )

    if settings.llm_provider == "ollama":
        return _call_ollama(system_prompt, user_content), prompt_hash

    client = _get_client()
    response = client.messages.create(
        model=settings.llm_model,
        max_tokens=settings.llm_max_tokens,
        system=[{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}],
        output_config={"format": {"type": "json_schema", "schema": ANSWER_SCHEMA}},
        messages=[{"role": "user", "content": user_content}],
    )

    if response.stop_reason == "refusal":
        raise SystemExit(f"Model declined the request: {response.stop_details}")

    text = next((b.text for b in response.content if b.type == "text"), None)
    if text is None:
        raise SystemExit(f"No text block in response (stop_reason={response.stop_reason})")
    return json.loads(text), prompt_hash


def _call_ollama(system_prompt: str, user_content: str) -> dict:
    """Generation against a local Ollama server — a fallback, not the default.

    Why this exists: it removes the API dependency entirely, so the pipeline can
    be demonstrated with no credentials and no spend.

    Why it is NOT the default: measured on a Raspberry Pi 5, the only model that
    fits in available RAM produces ~8 tokens/second, so a ~700-token answer takes
    roughly 90 seconds. More importantly, the grounding contract — emit opaque
    [En] handles, never a page number, answer `insufficient` rather than guess —
    depends on strict instruction-following that a small model does not reliably
    deliver. A wrong handle or an invented page number is a worse failure here
    than a slow answer, and validation will record it as one (hard rule 9).

    Ollama enforces the JSON schema itself via `format`, so a malformed payload
    surfaces as a recorded failure rather than a silent retry.
    """
    import urllib.error
    import urllib.request

    payload = json.dumps(
        {
            "model": settings.llm_model,
            "stream": False,
            "format": ANSWER_SCHEMA,
            "options": {"temperature": 0, "num_predict": settings.ollama_num_predict},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
        }
    ).encode("utf-8")

    request = urllib.request.Request(
        f"{settings.ollama_host.rstrip('/')}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(request, timeout=settings.ollama_timeout) as response:
            body = json.loads(response.read())
    except urllib.error.URLError as exc:
        raise SystemExit(
            f"Local model at {settings.ollama_host} is unreachable: {exc}. "
            "Start it with `ollama serve`, or set LLM_PROVIDER=anthropic."
        ) from exc
    except TimeoutError as exc:
        raise SystemExit(
            f"Local model did not answer within {settings.ollama_timeout}s. "
            "Small models on a Pi are slow; raise OLLAMA_TIMEOUT or use a hosted provider."
        ) from exc

    content = (body.get("message") or {}).get("content")
    if not content:
        raise SystemExit(f"Local model returned no content: {body!r}")

    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        # Not retried: malformed output is a recorded result, never hidden.
        raise SystemExit(
            f"Local model returned output that is not valid JSON ({exc}). "
            "This is a recorded failure, not a transient error."
        ) from exc


# ---------------------------------------------------------------------------
# Post-generation validation (blocking) — PLAN_V2 §13.5
# ---------------------------------------------------------------------------


def validate(result: dict, items: list[EvidenceItem]) -> list[str]:
    failures: list[str] = []
    supplied = {item.handle for item in items}

    body = " ".join(
        [result.get("answer") or ""]
        + result.get("ai_interpretation", [])
        + result.get("limitations", [])
    )
    used = {f"E{n}" for n in MARKER_RE.findall(body)} | {
        c.strip("[]") for c in result.get("citations_used", [])
    }
    unresolvable = sorted(u for u in used if u not in supplied)
    if unresolvable:
        failures.append(f"citation_hallucination: {unresolvable} not in the evidence set")

    sufficiency = result.get("evidence_sufficiency")
    if sufficiency == "insufficient":
        if result.get("answer") is not None:
            failures.append("contract: insufficient requires answer=null")
        if result.get("citations_used"):
            failures.append("contract: insufficient requires empty citations_used")
    if sufficiency == "partial" and not result.get("limitations"):
        failures.append("contract: partial requires non-empty limitations")

    # A claim of sufficiency with nothing cited is ungrounded prose, whatever
    # its provenance. Without this check an answer that never references the
    # evidence it was given passes validation and is presented as
    # source-grounded — the exact failure this project exists to prevent.
    # Observed from a small local model, which produced fluent text carrying no
    # [En] handle at all.
    if sufficiency in {"sufficient", "partial"} and not used:
        failures.append(
            f"ungrounded_answer: evidence_sufficiency={sufficiency} but no evidence handle "
            "was cited in the answer, interpretation or limitations"
        )

    # The model never receives a page number, so any it emits is fabricated.
    invented = PAGE_CLAIM_RE.findall(body)
    if invented:
        failures.append(f"invented_page_reference: model emitted {invented}")

    return failures


# ---------------------------------------------------------------------------
# Reader-facing rendering — the ONLY place page numbers are produced
# ---------------------------------------------------------------------------


def page_phrase(chunk: dict) -> str:
    start, end = chunk["page_start"], chunk["page_end"]
    if start is None or end is None:
        return f"page not printed on source page (PDF p. {chunk['pdf_page_start']}) [VERIFY]"
    return f"p. {start}" if start == end else f"pp. {start}–{end}"


def footnote(index: int, item: EvidenceItem) -> str:
    c = item.chunk
    parts = [f"{settings.document_author} ({settings.document_year})"]
    if c["chapter"]:
        parts.append(f"Ch. “{c['chapter']}”")
    if c["section"]:
        parts.append(f"§ {c['section']}")
    parts.append(page_phrase(c))
    suffix = " [reference list — what the thesis cites, not what it argues]" if is_apparatus(c) else ""
    return f"{index}. " + ", ".join(parts) + "." + suffix


def substitute_markers(text: str, order: dict[str, int]) -> str:
    def swap(match: re.Match) -> str:
        handle = f"E{match.group(1)}"
        n = order.get(handle)
        return str(n).translate(SUPERSCRIPTS) if n else match.group(0)

    return MARKER_RE.sub(swap, text)


def assign_order(result: dict, items: list[EvidenceItem]) -> dict[str, int]:
    supplied = {item.handle for item in items}
    body = " ".join(
        [result.get("answer") or ""]
        + result.get("ai_interpretation", [])
        + result.get("limitations", [])
    )
    order: dict[str, int] = {}
    for n in MARKER_RE.findall(body):
        handle = f"E{n}"
        if handle in supplied and handle not in order:
            order[handle] = len(order) + 1
    return order


def refusal_notice(items: list[EvidenceItem]) -> str:
    """Composed from retrieval metadata by code — not written by the model."""
    seen: list[str] = []
    for item in items:
        label = item.chunk["section"] or item.chunk["chapter"] or "untitled section"
        label = label if len(label) < 70 else label[:67] + "..."
        if label not in seen:
            seen.append(label)
    searched = "; ".join(seen[:4])
    return (
        "REFUSAL — the authorised research collection does not contain sufficient "
        "evidence to answer this question.\n\n"
        f"Retrieval searched the whole collection and returned passages from: {searched}. "
        "None of them address the question as asked.\n\n"
        "This is a statement about the collection, not about the topic."
    )


def render(question: str, result: dict, items: list[EvidenceItem], verbose: bool) -> str:
    out: list[str] = []
    rule = "─" * 74
    out.append(rule)
    out.append(f"QUESTION: {question}")
    out.append(rule)

    sufficiency = result["evidence_sufficiency"]
    out.append(f"\nEvidence sufficiency: {sufficiency.upper()}\n")

    order = assign_order(result, items)

    if sufficiency == "insufficient" or result.get("answer") is None:
        out.append(refusal_notice(items))
    else:
        out.append(substitute_markers(result["answer"], order))

    if result.get("limitations"):
        out.append("\nLIMITS OF THIS ANSWER")
        for line in result["limitations"]:
            out.append(f"  • {substitute_markers(line, order)}")

    if result.get("unsupported_by_evidence"):
        out.append("\nNOT COVERED BY THE COLLECTION")
        for line in result["unsupported_by_evidence"]:
            out.append(f"  • {line}")

    if result.get("ai_interpretation"):
        out.append("\n[AI INTERPRETATION] — inference beyond what the source states;")
        out.append("not the author's published position.")
        for line in result["ai_interpretation"]:
            out.append(f"  • {substitute_markers(line, order)}")

    if order:
        out.append("\n" + "─" * 30)
        for handle, n in sorted(order.items(), key=lambda kv: kv[1]):
            item = next(i for i in items if i.handle == handle)
            out.append(footnote(n, item))
            if verbose:
                out.append(f"     chunk_id: {item.chunk['chunk_id']}")
                out.append(f"     retrieval score (diagnostic, not confidence): {item.score:.4f}")
                out.append(f"     verbatim: “{item.chunk['text'][:400]}…”")

    out.append("\nRETRIEVAL DIAGNOSTICS (not a confidence measure)")
    for item in items:
        c = item.chunk
        label = (c["section"] or c["chapter"] or "—")[:52]
        out.append(f"  {item.handle}  score={item.score:.4f}  {page_phrase(c):<14} {label}")

    return "\n".join(out)


# ---------------------------------------------------------------------------
# The one pipeline. ask.py (single question) and main.py (interactive loop)
# are both thin shells over run_query — retrieval, generation, validation and
# citation resolution exist in exactly one place.
# ---------------------------------------------------------------------------


@dataclass
class QueryOutcome:
    question: str
    result: dict
    items: list[EvidenceItem]
    failures: list[str]
    prompt_hash: str

    @property
    def grounded(self) -> bool:
        return not self.failures

    def rendered(self, verbose: bool = False) -> str:
        return render(self.question, self.result, self.items, verbose)


def run_query(
    question: str,
    vectors: np.ndarray,
    chunks: list[dict],
    top_k: int | None = None,
) -> QueryOutcome:
    """Retrieve -> ground -> validate. No printing, no process control."""
    items = retrieve(question, vectors, chunks, top_k or settings.top_k)
    result, prompt_hash = call_model(question, items)
    return QueryOutcome(
        question=question,
        result=result,
        items=items,
        failures=validate(result, items),
        prompt_hash=prompt_hash,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Query the authorised research collection.")
    parser.add_argument("question", help="the question to ask")
    parser.add_argument("-k", "--top-k", type=int, default=settings.top_k)
    parser.add_argument("--verbose-provenance", action="store_true",
                        help="print chunk ids and verbatim passages under each footnote")
    parser.add_argument("--json", action="store_true", help="emit the raw run record")
    args = parser.parse_args()

    vectors, chunks, manifest = load_index()
    outcome = run_query(args.question, vectors, chunks, args.top_k)
    result, items, failures = outcome.result, outcome.items, outcome.failures
    prompt_hash = outcome.prompt_hash

    if args.json:
        print(json.dumps(
            {
                "question": args.question,
                "model": settings.llm_model,
                "embedding_model": manifest["embedding_model"],
                "prompt_sha256_12": prompt_hash,
                "corpus_text_sha256": manifest["corpus_text_sha256"],
                "evidence": [
                    {"handle": i.handle, "chunk_id": i.chunk["chunk_id"], "score": i.score}
                    for i in items
                ],
                "result": result,
                "validation_failures": failures,
            },
            indent=1, ensure_ascii=False,
        ))
        return 1 if failures else 0

    print(outcome.rendered(args.verbose_provenance))

    # A validation failure is a recorded research result, not a silent retry.
    if failures:
        print("\n" + "!" * 74)
        print("VALIDATION FAILED — this answer is not certified grounded:")
        for f in failures:
            print(f"  ✗ {f}")
        print("!" * 74)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
