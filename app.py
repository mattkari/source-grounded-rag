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

Since PLAN_V4 the app has a second view, the thesis library, where the
researcher uploads another thesis, reads the audit of its extraction, confirms
its identity and approves or rejects it. That view is also a shell: every rule
(nothing embedded before approval, nothing cited before the identity is
confirmed) lives in upload.py and is tested there. One thesis is active at a
time and each question searches only that one.
"""

from __future__ import annotations

import re

import streamlit as st

import ask
import audit
import runs
import upload
from config import settings
from documents import Document, default_document

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

NOT_EVALUATED = (
    "Ingested and audited — **not evaluated**. The audit shows the extraction is "
    "faithful to the PDF; it says nothing about whether answers are correct."
)

VIEW_ASK, VIEW_LIBRARY = "Ask questions", "Thesis library"


# ---------------------------------------------------------------------------
# Collection — loaded once per server process, not once per interaction
# ---------------------------------------------------------------------------


@st.cache_resource(show_spinner="Loading the research collection…")
def load_collection(document_id: str):
    """Wraps ask.load_index so the index survives Streamlit's script reruns.
    Cached per document: switching the active thesis loads its own index."""
    return ask.load_index(upload.find_document(document_id))


def collection_or_stop(document: Document):
    try:
        return load_collection(document.document_id)
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


def belongs_to(record: dict, document: Document) -> bool:
    """Runs recorded before documents were named belong to the built-in thesis."""
    return record.get("document_id", settings.document_id) == document.document_id


def render_history_sidebar(chunks: list[dict], document: Document) -> dict | None:
    """Past runs, newest first. Returns a record to re-open, or None.

    History is read from disk, not from session state, so it survives a browser
    refresh and a container restart.
    """
    with st.sidebar:
        st.markdown("### Past questions")
        everything = [r for r in runs.load() if belongs_to(r, document)]
        records = everything[:HISTORY_LIMIT]

        if not records:
            st.caption("No questions yet. Ask one and it will be recorded here.")
            return None

        st.caption(
            f"{len(records)} most recent of {len(everything)} recorded for this thesis. "
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


def session_history(chunks: list[dict], document: Document) -> list[dict]:
    """The conversation, rebuilt from disk on first load.

    Streamlit's session_state is per-browser-session, so relying on it alone
    made the whole conversation vanish on a refresh while the records sat safely
    on disk. The recorded runs are the source of truth; session_state is just
    this tab's view of them.

    Entries are rehydrated through runs.as_outcome, so citations are resolved
    against the current index rather than replayed from stored text.
    """
    key = f"history::{document.document_id}"  # one conversation per thesis
    if key in st.session_state:
        return st.session_state[key]

    rebuilt: list[dict] = []
    for record in reversed(runs.load()):  # runs.load is newest-first
        if not belongs_to(record, document):
            continue  # a different thesis: not part of this conversation
        if record.get("error"):
            rebuilt.append({"question": record["question"], "error": record["error"]})
            continue
        outcome, unresolved = runs.as_outcome(record, chunks, document)
        rebuilt.append(
            {
                "question": record["question"],
                "outcome": outcome,
                "unresolved": unresolved,
                "timestamp": record.get("timestamp", ""),
            }
        )

    st.session_state[key] = rebuilt
    return rebuilt


# ---------------------------------------------------------------------------
# Thesis library — upload, review, approve (PLAN_V4 §6, §12)
# ---------------------------------------------------------------------------


def document_label(document: Document) -> str:
    return f"{document.short_title} (built-in)" if document.builtin else document.short_title


def choose_document() -> Document:
    """The sidebar picker: the built-in thesis first, then approved uploads."""
    documents = [default_document(settings)] + upload.ready_documents()
    by_id = {d.document_id: d for d in documents}
    if st.session_state.get("active_document") not in by_id:
        st.session_state.active_document = documents[0].document_id
    with st.sidebar:
        chosen = st.selectbox(
            "Thesis",
            options=list(by_id),
            format_func=lambda document_id: document_label(by_id[document_id]),
            key="active_document",
            help="One thesis is active at a time. Each question searches only that one.",
        )
    return by_id[chosen]


def attempt(action, *args, **kwargs) -> bool:
    """Run one upload step. A refusal is shown in plain words, never as a trace."""
    try:
        action(*args, **kwargs)
        return True
    except upload.UploadRefused as exc:
        st.session_state.library_message = ("error", str(exc))
        return False


def refresh() -> None:
    load_collection.clear()
    st.rerun()


def render_profile(record: dict) -> None:
    rows = ["| Measured value | Result | How it was reached |", "|---|---|---|"]
    evidence = record.get("layout_evidence") or {}
    for name, value in (record.get("layout") or {}).items():
        key = "heading_tiers" if name.endswith("_heading_min_size") else name
        rule = (evidence.get(key) or {}).get("rule", "")
        shown = "not found" if value is None else (", ".join(value) or "none") if isinstance(value, list) else value
        rows.append(f"| `{name}` | {shown} | {rule} |")
    st.markdown("\n".join(rows))
    with st.expander("Evidence behind each value"):
        st.json(evidence, expanded=False)


def render_identity_form(record: dict) -> None:
    proposal = record.get("identity_proposal") or {}
    confirmed = record["identity"]

    def start(name: str) -> str:
        return confirmed[name] or (proposal.get(name) or {}).get("value", "")

    st.markdown("**Who wrote this, and when?** Nothing is cited until you confirm these.")
    for name in ("title", "author", "year"):
        source = (proposal.get(name) or {}).get("source", "")
        value = (proposal.get(name) or {}).get("value", "")
        st.caption(f"{name.capitalize()} — proposed from {source}." if value else f"{name.capitalize()} — {source}.")
    hint = proposal.get("pdf_metadata") or {}
    if hint:
        st.caption(
            "The PDF's own metadata says "
            + "; ".join(f"{k}: “{v}”" for k, v in hint.items())
            + ". This is often wrong (it can come from a template) and is shown only as a hint."
        )

    key = record["document_id"]
    with st.form(f"identity-{key}"):
        author = st.text_input("Author, as it should appear in citations (for example: Surname, I.)",
                               value=start("author"), key=f"author-{key}")
        year = st.text_input("Year", value=start("year"), key=f"year-{key}")
        title = st.text_input("Title", value=start("title"), key=f"title-{key}")
        short_title = st.text_input(
            "Short title shown above each passage (leave blank to build it from the three above)",
            value=confirmed["short_title"], key=f"short-{key}",
        )
        if st.form_submit_button("Confirm identity"):
            if attempt(upload.confirm_identity, key, author=author, year=year, title=title,
                       short_title=short_title):
                st.session_state.library_message = ("success", "Identity confirmed.")
            refresh()
    if confirmed["confirmed"]:
        st.success(
            f"Confirmed: {confirmed['author']} ({confirmed['year']}), {confirmed['title']}", icon="✅"
        )


def render_remove(record: dict) -> None:
    key = record["document_id"]
    with st.expander("Remove this thesis"):
        st.caption(
            "Deletes the PDF, the extraction and the index from this machine. "
            "Recorded questions are kept, but their citations can no longer be shown."
        )
        sure = st.checkbox("Yes, delete all three", key=f"sure-{key}")
        if st.button("Remove", key=f"remove-{key}", disabled=not sure):
            if attempt(upload.remove, key):
                st.session_state.library_message = ("success", "Removed.")
            refresh()


def render_record(record: dict) -> None:
    key, state = record["document_id"], record["state"]
    name = record["identity"]["title"] or record["source_filename"]
    with st.container(border=True):
        st.markdown(f"#### {name}")
        st.caption(f"`{key}` · {record['pages_total']} pages · **{upload.STATE_LABELS[state]}**")

        if state == upload.RECEIVED:
            if st.button("Measure and audit", key=f"analyse-{key}"):
                with st.spinner("Measuring the layout and auditing the extraction…"):
                    attempt(upload.analyse, key)
                refresh()

        if state in {upload.AWAITING_REVIEW, upload.BLOCKED}:
            for flag in record["flags"]:
                st.warning(flag, icon="⚠️")
            result = upload.read_audit(key)
            if result:
                st.markdown("**Audit of the extraction against the PDF**")
                st.code(audit.format_report(result), language="text")
            if record.get("layout"):
                with st.expander("Measured layout profile"):
                    render_profile(record)

        if state == upload.BLOCKED:
            st.error("This thesis cannot be used. The reason is in the report above.", icon="⛔")

        if state == upload.AWAITING_REVIEW:
            render_identity_form(record)
            st.markdown("**Your decision.** There is no pass mark: you judge the report.")
            left, right = st.columns(2)
            with left:
                if st.button("Approve", key=f"approve-{key}", type="primary",
                             disabled=not record["identity"]["confirmed"]):
                    attempt(upload.approve, key)
                    refresh()
            with right:
                reason = st.text_input("Reason for rejecting (kept in the record)", key=f"reason-{key}")
                if st.button("Reject", key=f"reject-{key}"):
                    attempt(upload.reject, key, reason)
                    refresh()

        if state == upload.REJECTED:
            st.info(f"Rejected. Reason recorded: {record['review']['reason'] or '(none given)'}")

        if state == upload.APPROVED:
            failures = [h for h in record["history"] if h["stage"] == "index" and h["outcome"] == "failed"]
            if failures:
                st.warning(f"The last attempt to embed failed: `{failures[-1]['detail']}`", icon="⚠️")
            try:
                estimate = upload.estimate_cost(key)
            except upload.UploadRefused as exc:
                st.error(str(exc))
                estimate = None
            if estimate:
                cost = (
                    f"about **${estimate['estimated_cost']:.4f}** at ${estimate['price_per_million_tokens']:g} "
                    "per million tokens"
                    if estimate["estimated_cost"] is not None
                    else "no price is configured (`EMBEDDING_PRICE_PER_MTOK`), so only the token count is shown"
                )
                st.markdown(
                    f"**Embedding cost.** {estimate['passages']} passages, **{estimate['tokens']:,} tokens**, "
                    f"sent to `{estimate['embedding_model']}` — {cost}."
                )
                accepted = st.checkbox("I accept this cost", key=f"cost-{key}")
                if st.button("Embed and index", key=f"index-{key}", type="primary", disabled=not accepted):
                    with st.spinner("Embedding the passages…"):
                        if attempt(upload.build_index, key, cost_accepted=accepted):
                            st.session_state.library_message = ("success", "Indexed. The thesis can now be queried.")
                    refresh()

        if state == upload.READY:
            st.markdown(NOT_EVALUATED)
            if st.button("Ask questions of this thesis", key=f"open-{key}"):
                st.session_state.pending_document = key
                st.session_state.pending_view = VIEW_ASK
                st.rerun()

        render_remove(record)


def render_library() -> None:
    st.title("Thesis library")
    st.markdown(
        "Upload another thesis as a PDF. The system measures its layout, extracts it, and checks "
        "the extraction against the PDF. **You read the report and decide.** Nothing is sent for "
        "embedding, and nothing is spent, until you approve."
    )
    st.caption(
        "Theses with a text layer only — not journal articles, not scans. Uploads stay on this "
        "machine and are never committed or shared."
    )

    message = st.session_state.pop("library_message", None)
    if message:
        (st.error if message[0] == "error" else st.success)(message[1])

    uploaded = st.file_uploader("Thesis PDF", type=["pdf"], key="thesis_upload")
    if uploaded is not None and st.button("Add to the library", type="primary"):
        with st.spinner("Storing, measuring and auditing…"):
            try:
                record = upload.receive(uploaded.getvalue(), uploaded.name)
                upload.analyse(record["document_id"])
                st.session_state.library_message = ("success", "Analysed. Read the report below.")
            except upload.UploadRefused as exc:
                st.session_state.library_message = ("error", str(exc))
        refresh()

    records = upload.list_records()
    if not records:
        st.info("No thesis has been uploaded yet. The built-in thesis is always available.")
    for record in reversed(records):  # newest first
        render_record(record)


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------


def render_chat(document: Document) -> None:
    vectors, chunks, manifest = collection_or_stop(document)

    st.title(PAGE_TITLE)
    st.subheader(
        f"{document.short_title} — {manifest['chunk_count']} indexed passages",
        divider="grey",
    )
    if not document.builtin:
        st.info(NOT_EVALUATED, icon="ℹ️")
    st.markdown(EXPLAINER)

    history = session_history(chunks, document)

    jumped = render_history_sidebar(chunks, document)
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
            entry["outcome"] = ask.run_query(question, vectors, chunks, document=document)
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


def main() -> None:
    st.set_page_config(page_title=PAGE_TITLE, page_icon="📚", layout="centered")
    st.markdown(HIDE_CHROME, unsafe_allow_html=True)

    # A button elsewhere asked to open a thesis: apply it before the widgets
    # that own these keys are drawn.
    if "pending_document" in st.session_state:
        st.session_state.active_document = st.session_state.pop("pending_document")
    if "pending_view" in st.session_state:
        st.session_state.view = st.session_state.pop("pending_view")

    with st.sidebar:
        view = st.radio("View", [VIEW_ASK, VIEW_LIBRARY], key="view", label_visibility="collapsed")
    document = choose_document()

    if view == VIEW_LIBRARY:
        render_library()
    else:
        render_chat(document)


main()
