"""Streamlit web chat interface for the source-grounded research assistant.

    streamlit run app.py

This is a shell, not a pipeline — the third one, after ask.py (single question)
and main.py (interactive CLI). Every question goes through ask.run_query, so
retrieval, grounded generation, validation and citation resolution exist in
exactly one place. Nothing here resolves a page number: the page phrases and
footnotes rendered below come from ask.page_phrase / ask.footnote, which read
stored provenance (hard rule 2).

The audience is non-technical. Nothing technical is hidden or softened, but the
default view carries the answer and its sources; evidence handles, retrieval
scores and validation outcomes live one click away.
"""

from __future__ import annotations

import re

import streamlit as st

import ask
import runs
from config import settings

PAGE_TITLE = "Source-Grounded Research Assistant"

# Streamlit's own chrome (Deploy button, hamburger menu) is developer furniture;
# it has no meaning for a lecturer watching the demo.
HIDE_CHROME = """
<style>
  [data-testid="stToolbar"], #MainMenu, footer {visibility: hidden;}
</style>
"""

SUPERSCRIPTS = "⁰¹²³⁴⁵⁶⁷⁸⁹"

EXPLAINER = (
    "This assistant only answers using the document collection shown above. "
    "If the collection does not contain enough evidence, it will say so rather "
    "than guessing."
)

REFUSAL_HEADING = (
    "This collection does not contain sufficient evidence to answer this question."
)

INTERPRETATION_HEADING = (
    "**AI interpretation — the assistant's own inference, not the author's stated "
    "position.**"
)

GENERIC_ERROR = (
    "Something went wrong retrieving the answer — please try the question again."
)

UNGROUNDED_NOTICE = (
    "This answer did not pass the automatic grounding checks, so it is not "
    "certified as source-grounded. Details are in the technical section below."
)

DIAGNOSTICS_LABEL = "Technical details (for evaluators)"

HISTORY_LIMIT = 50


# ---------------------------------------------------------------------------
# Collection — loaded once per server process, not once per interaction
# ---------------------------------------------------------------------------


@st.cache_resource(show_spinner="Loading the research collection…")
def load_collection():
    """Wraps ask.load_index so the index survives Streamlit's script reruns."""
    return ask.load_index()


def collection_or_stop():
    try:
        return load_collection()
    except BaseException as exc:  # SystemExit (no index / model mismatch) included
        st.error(
            "The research collection could not be loaded, so no questions can be "
            "answered yet."
        )
        with st.expander(DIAGNOSTICS_LABEL):
            st.code(f"{type(exc).__name__}: {exc}")
        st.stop()


# ---------------------------------------------------------------------------
# Translating ask.py's plain-text rendering into UI elements
# ---------------------------------------------------------------------------


def marked(text: str, order: dict[str, int]) -> str:
    """ask.substitute_markers, plus a non-breaking space so a lone superscript
    reference can never wrap to a line of its own."""
    return re.sub(
        rf"\s+([{SUPERSCRIPTS}]+)", " \\1", ask.substitute_markers(text, order)
    )


def sources_line(order: dict[str, int], items: list[ask.EvidenceItem]) -> str:
    """"Sources: [1] pp. 88–89, [2] p. 86" — pages from provenance, never invented.

    A reference-list source is marked here too, not only in the full citation:
    the short line is the one a reader actually reads.
    """
    parts = []
    for handle, n in sorted(order.items(), key=lambda kv: kv[1]):
        item = next(i for i in items if i.handle == handle)
        tag = " *(reference list)*" if ask.is_apparatus(item.chunk) else ""
        parts.append(f"**[{n}]** {ask.page_phrase(item.chunk)}{tag}")
    return "Sources: " + ", ".join(parts)


def bullets(lines: list[str], order: dict[str, int]) -> str:
    return "\n".join(f"- {marked(line, order)}" for line in lines)


def render_diagnostics(outcome: ask.QueryOutcome) -> None:
    """Collapsed by default: scores are diagnostics, never a confidence figure."""
    with st.expander(DIAGNOSTICS_LABEL):
        if not outcome.grounded:
            st.markdown("**Validation failures**")
            st.markdown("\n".join(f"- `{f}`" for f in outcome.failures))

        st.markdown("**Retrieval diagnostics** — similarity scores are diagnostics, "
                    "not a measure of confidence.")
        rows = ["| Evidence | Score | Pages | Chapter / section |",
                "|---|---|---|---|"]
        for item in outcome.items:
            chunk = item.chunk
            label = chunk["section"] or chunk["chapter"] or "—"
            label = label if len(label) <= 60 else label[:57] + "…"
            label = label.replace("|", "\\|")
            rows.append(
                f"| {item.handle} | {item.score:.4f} | {ask.page_phrase(chunk)} | {label} |"
            )
        st.markdown("\n".join(rows))

        st.markdown(
            f"**Run** — evidence sufficiency `{outcome.result['evidence_sufficiency']}` · "
            f"generation model `{settings.llm_model}` · "
            f"prompt `sha256:{outcome.prompt_hash}` · "
            f"passages retrieved `{len(outcome.items)}`"
        )


def copy_block(outcome: ask.QueryOutcome, key: str) -> None:
    """A copy button. The text is ask.render's — answer plus its sources — so a
    pasted answer cannot arrive somewhere without its citations."""
    with st.popover("📋 Copy", use_container_width=False):
        st.code(outcome.rendered(), language="text", wrap_lines=True)


def render_outcome(outcome: ask.QueryOutcome, key: str = "live") -> None:
    result, items = outcome.result, outcome.items
    order = ask.assign_order(result, items)
    sufficiency = result["evidence_sufficiency"]

    if sufficiency == "insufficient" or result.get("answer") is None:
        # A refusal is correct behaviour, not a system failure — st.warning, and
        # the notice is composed by ask.refusal_notice from retrieval metadata.
        notice = ask.refusal_notice(items).split("\n\n")
        body = [p for p in notice if not p.startswith("REFUSAL")]  # heading says it
        st.warning(f"**{REFUSAL_HEADING}**\n\n" + "\n\n".join(body), icon="⚖️")
    else:
        if sufficiency == "partial":
            st.caption("Partial evidence — the collection answers part of this question.")
        st.markdown(marked(result["answer"], order))

    if result.get("limitations"):
        st.markdown("**Limits of this answer**")
        st.markdown(bullets(result["limitations"], order))

    if result.get("unsupported_by_evidence"):
        st.markdown("**Not covered by the collection**")
        st.markdown("\n".join(f"- {line}" for line in result["unsupported_by_evidence"]))

    if result.get("ai_interpretation"):
        st.info(
            INTERPRETATION_HEADING + "\n\n" + bullets(result["ai_interpretation"], order),
            icon="🧠",
        )

    if order:
        st.markdown(sources_line(order, items))
        with st.expander("Show full citation details"):
            for handle, n in sorted(order.items(), key=lambda kv: kv[1]):
                item = next(i for i in items if i.handle == handle)
                st.markdown(ask.footnote(n, item))

    if not outcome.grounded:
        # Hard rule 9: a validation failure is a recorded result, not something
        # to hide — but it is stated in plain language, not as a stack trace.
        st.warning(UNGROUNDED_NOTICE, icon="⚠️")

    copy_block(outcome, key)
    render_diagnostics(outcome)


def render_error(entry: dict) -> None:
    st.error(GENERIC_ERROR)
    with st.expander(DIAGNOSTICS_LABEL):
        st.code(entry["error"])


def render_turn(entry: dict, key: str = "live") -> None:
    if "error" in entry:
        render_error(entry)
    else:
        render_outcome(entry["outcome"], key)


def render_history_sidebar(chunks: list[dict]) -> dict | None:
    """Past runs, newest first. Returns a record to re-open, or None.

    History is read from disk, not from session state, so it survives a browser
    refresh and a container restart.
    """
    with st.sidebar:
        st.markdown("### Past questions")
        records = runs.load(limit=HISTORY_LIMIT)

        if not records:
            st.caption("No questions yet. Ask one and it will be recorded here.")
            return None

        st.caption(
            f"{len(records)} most recent of {runs.count()} recorded. "
            "Saved to disk — they survive a refresh."
        )

        selected = None
        for index, record in enumerate(records):
            stamp = record.get("timestamp", "")[:16].replace("T", " ")
            question = record.get("question", "(no question)")
            label = question if len(question) <= 70 else question[:67] + "…"
            sufficiency = (record.get("result") or {}).get("evidence_sufficiency", "?")
            mark = {"sufficient": "✅", "partial": "◐", "insufficient": "⚖️"}.get(
                sufficiency, "•"
            )
            if record.get("validation_failures"):
                mark = "⚠️"
            if st.button(
                f"{mark} {label}",
                key=f"hist-{index}",
                use_container_width=True,
                help=f"{stamp} UTC · {sufficiency} · {record.get('model', '?')}",
            ):
                selected = record

        st.divider()
        st.download_button(
            "Download all runs (JSONL)",
            data=runs.export_jsonl(),
            file_name="runs.jsonl",
            mime="application/x-ndjson",
            use_container_width=True,
        )
        st.caption(
            "⚠️ = the answer did not pass grounding validation. "
            "⚖️ = the collection could not answer."
        )
        return selected


def session_history(chunks: list[dict]) -> list[dict]:
    """The conversation, rebuilt from disk on first load.

    Streamlit's session_state is per-browser-session, so relying on it alone
    made the whole conversation vanish on a refresh while the records sat safely
    on disk. The recorded runs are the source of truth; session_state is just
    this tab's view of them.

    Entries are rehydrated through runs.as_outcome, so citations are resolved
    against the current index rather than replayed from stored text.
    """
    if "history" in st.session_state:
        return st.session_state.history

    rebuilt: list[dict] = []
    for record in reversed(runs.load()):  # runs.load is newest-first
        if record.get("document_id") and record["document_id"] != settings.document_id:
            continue  # a different corpus: not part of this conversation
        if record.get("error"):
            rebuilt.append({"question": record["question"], "error": record["error"]})
            continue
        outcome, unresolved = runs.as_outcome(record, chunks)
        rebuilt.append(
            {
                "question": record["question"],
                "outcome": outcome,
                "unresolved": unresolved,
                "timestamp": record.get("timestamp", ""),
            }
        )

    st.session_state.history = rebuilt
    return rebuilt


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------


def main() -> None:
    st.set_page_config(page_title=PAGE_TITLE, page_icon="📚", layout="centered")
    st.markdown(HIDE_CHROME, unsafe_allow_html=True)

    vectors, chunks, manifest = collection_or_stop()

    st.title(PAGE_TITLE)
    st.subheader(
        f"{settings.document_short_title} — {manifest['chunk_count']} indexed passages",
        divider="grey",
    )
    st.markdown(EXPLAINER)

    history = session_history(chunks)

    jumped = render_history_sidebar(chunks)
    if jumped is not None:
        st.session_state.jump_to = jumped.get("timestamp", "")

    if history:
        st.caption(f"{len(history)} earlier question(s) in this collection — scroll to read.")

    jump_to = st.session_state.pop("jump_to", None)
    for index, entry in enumerate(history):
        anchor = entry.get("timestamp", "")
        is_target = jump_to and anchor == jump_to
        if is_target:
            st.divider()
            st.caption("↓ the question you selected")
        with st.chat_message("user"):
            st.markdown(entry["question"])
        with st.chat_message("assistant"):
            if entry.get("unresolved"):
                st.warning(
                    "Some passages from this run are no longer in the collection, "
                    "so their citations are not shown.",
                    icon="⚠️",
                )
            render_turn(entry, key=f"turn-{index}")
        if is_target:
            st.divider()

    question = st.chat_input("Ask a question about this collection…")
    if not question or not question.strip():
        return

    question = question.strip()

    entry: dict = {"question": question}
    with st.spinner("Searching the collection…"):
        try:
            entry["outcome"] = ask.run_query(question, vectors, chunks)
        except BaseException as exc:  # provider error, auth, network, bad output
            entry["error"] = f"{type(exc).__name__}: {exc}"

    # Persist first: the record on disk is the evidence, session_state is only
    # what this tab is showing.
    outcome = entry.get("outcome")
    record = runs.append(
        question=question,
        result=outcome.result if outcome else {},
        items=outcome.items if outcome else [],
        failures=outcome.failures if outcome else [],
        prompt_hash=outcome.prompt_hash if outcome else "",
        manifest=manifest,
        error=entry.get("error"),
    )
    entry["timestamp"] = record.get("timestamp", "")
    if record.get("_persist_error"):
        st.warning(
            "This answer could not be saved to the query history: "
            f"`{record['_persist_error']}`",
            icon="⚠️",
        )

    history.append(entry)
    st.rerun()


main()
