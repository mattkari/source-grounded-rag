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

Since PLAN_V6 there is a third view, "Write an article". It too is a shell:
sections are drafted by ask.run_query on the filtered sources, and every rule
(what may be drafted from, what blocks a section, when an article stops being
a draft) lives in the `article` package and is tested there.
"""

from __future__ import annotations

import copy
import html
import json
import re

import streamlit as st

import ask
import audit
import runs
import upload
from article import assemble, pipeline, sentences as article_sentences, sources as article_sources
from article import explorer, terms as article_terms, topics as article_topics, trace as article_trace, voice
from config import settings
from documents import Document, default_document

PAGE_TITLE = "Source-Grounded Research Assistant"

# Page style. Three jobs, each found by auditing the page at phone and laptop
# size (docs/decisions/0004-ui-accessibility.md):
#
#   1. Hide Streamlit's developer furniture (Deploy button, main menu) and
#      nothing else. The button that opens the sidebar lives in the same
#      toolbar; on a phone the sidebar starts closed, so hiding the whole
#      toolbar left no way to change view or thesis.
#   2. Contrast. Captions and quoted sentences were drawn in a grey below the
#      4.5:1 minimum. They now take the theme's own text colour, which holds in
#      light and dark themes alike; captions stay smaller, not fainter.
#   3. Phones. Less empty space above the title, headings that fit the width,
#      and controls tall enough for a finger.
PAGE_STYLE = """
<style>
  [data-testid="stToolbarActions"], [data-testid="stMainMenu"],
  [data-testid="stAppDeployButton"], #MainMenu, footer {visibility: hidden;}

  [data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p,
  [data-testid="stMarkdownContainer"] blockquote, [data-testid="stMarkdownContainer"] blockquote p,
  [data-testid="stFileUploaderDropzoneInstructions"] span,
  [data-testid="stFileUploaderDropzoneInstructions"] small {color: inherit !important; opacity: 1 !important;}

  :focus-visible {outline: 3px solid #1a73e8 !important; outline-offset: 2px;}

  /* The three views stay in reach while the page scrolls (ADR 0007). Kept to one slim
     row, right of the button that opens the sidebar. */
  /* Streamlit's header lies over the top of the page. It is made see-through and lets
     taps pass, except on its own buttons, so the bar under it can be seen and used. */
  [data-testid="stHeader"] {background: transparent !important;}
  [data-testid="stHeader"], [data-testid="stHeader"] * {pointer-events: none !important;}
  [data-testid="stHeader"] button, [data-testid="stHeader"] button * {pointer-events: auto !important;}
  .st-key-topnav {position: fixed; top: 0; left: 0; right: 0; z-index: 999980; padding: 0.3rem 1rem 0.2rem 3.75rem;
    /* Streamlit sets no colour variable, only `color-scheme` on the app. `Canvas` and
       `light-dark()` both follow it, so the bar is dark in a dark theme. The two
       colours are Streamlit's own default page backgrounds. */
    background: Canvas; background: light-dark(#ffffff, #0e1117);
    border-bottom: 1px solid rgba(128, 128, 128, 0.35);}
  /* The options sit at the right: on a wide screen the open sidebar lies over the
     left of the bar, and on a phone the left is where the sidebar button is. */
  .st-key-topnav {display: flex; flex-direction: row; justify-content: flex-end;}
  .st-key-topnav > * {width: auto !important; flex: 0 0 auto;}
  .st-key-topnav [role="radiogroup"] {flex-wrap: nowrap; gap: 0.5rem;}
  /* A control that takes keyboard focus is never left hidden under the bar (WCAG 2.4.11). */
  [data-testid="stMain"], [data-testid="stAppScrollToBottomContainer"] {scroll-padding-top: 5rem;}
  .st-key-backtotop a {display: inline-block; min-height: 44px; padding: 0.6rem 0;}
  .sgrag-copy {display: flex; align-items: center; gap: 0.75rem; flex-wrap: wrap;}
  .sgrag-copy-button[disabled] {opacity: 0.45; cursor: not-allowed;}
  .sgrag-copy-button {min-height: 44px; padding: 0.4rem 0.9rem; border-radius: 0.5rem; cursor: pointer; font: inherit;
    color: inherit; background: transparent; border: 1px solid rgba(128, 128, 128, 0.6);}

  @media (max-width: 640px) {
    [data-testid="stMainBlockContainer"] {padding: 3.75rem 1rem 6rem 1rem;}
    [data-testid="stMainBlockContainer"] h1 {font-size: 1.85rem; line-height: 1.2; padding-top: 0.5rem;}
    [data-testid="stMainBlockContainer"] h2 {font-size: 1.35rem; line-height: 1.3;}
    [data-testid="stMainBlockContainer"] h3 {font-size: 1.15rem; line-height: 1.3;}
  }
  @media (pointer: coarse) {
    [data-testid="stRadio"] [role="radiogroup"] label, [data-testid="stCheckbox"] label {
      min-height: 44px; display: flex; align-items: center; padding-right: 0.75rem;}
    [data-testid="stButton"] button, [data-testid="stDownloadButton"] button,
    [data-testid="stExpandSidebarButton"], [data-testid="stSidebarCollapseButton"] button {min-height: 44px; min-width: 44px;}
  }
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

VIEW_ASK, VIEW_LIBRARY, VIEW_ARTICLE = "Ask questions", "Thesis library", "Write an article"

ARTICLE_EXPLAINER = (
    "Drafts an article for general readers from the active thesis. Every claim carries a note back "
    "to a printed page. **It drafts; you check every note and decide.** Nothing is published or "
    "sent anywhere."
)
# Short names for the navigation bar, which stays in view on a narrow screen.
VIEW_LABELS = {VIEW_ASK: "Ask", VIEW_LIBRARY: "Library", VIEW_ARTICLE: "Write"}
OWN_TOPIC = "My own topic"
I_WRITE, GENERATE = "I write it", "Generate as labelled commentary"
NOT_JUDGED = "not judged"


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


COPY_SCRIPT = """
<div class="sgrag-copy">
  <button type="button" id="copy-__ID__" class="sgrag-copy-button" __DISABLED__>__LABEL__</button>
  <span id="copy-status-__ID__" class="sgrag-copy-status" role="status" aria-live="polite"></span>
</div>
<script>
(() => {
  const text = __TEXT__;
  const rich = __HTML__;
  const button = document.getElementById("copy-__ID__");
  const status = document.getElementById("copy-status-__ID__");
  const label = button.textContent;
  button.addEventListener("click", async () => {
    let copied = false;
    try {
      if (navigator.clipboard && window.isSecureContext) {
        if (rich && window.ClipboardItem) {
          await navigator.clipboard.write([new ClipboardItem({
            "text/html": new Blob([rich], {type: "text/html"}), "text/plain": new Blob([text], {type: "text/plain"})})]);
        } else { await navigator.clipboard.writeText(text); }
        copied = true;
      }
    } catch (error) {}
    if (!copied) {
      // The page is served over plain http, where browsers withhold the clipboard API.
      // Formatted text is copied by selecting it as rendered; plain text from a text box.
      const holder = document.createElement(rich ? "div" : "textarea");
      if (rich) { holder.innerHTML = rich; holder.setAttribute("contenteditable", "true"); }
      else { holder.value = text; holder.setAttribute("readonly", ""); }
      holder.style.position = "fixed"; holder.style.left = "-9999px"; holder.style.opacity = "0";
      document.body.appendChild(holder);
      if (rich) {
        const range = document.createRange(); range.selectNodeContents(holder);
        const selection = window.getSelection(); selection.removeAllRanges(); selection.addRange(range);
      } else { holder.select(); }
      try { copied = document.execCommand("copy"); } catch (error) {}
      if (rich) { window.getSelection().removeAllRanges(); }
      holder.remove();
    }
    button.textContent = copied ? "Copied" : label;
    status.textContent = copied ? "Copied to the clipboard." : "Could not copy. Select the text and copy it by hand.";
    setTimeout(() => { button.textContent = label; status.textContent = ""; }, 4000);
  });
})();
</script>
"""


def copy_text(outcome: ask.QueryOutcome) -> str:
    """What a copied answer carries: the question, the answer, its limits and its
    sources, so it cannot arrive somewhere without its citations. Notes and pages
    come from the same functions the page uses (`ask.substitute_markers`,
    `ask.footnote`): nothing here resolves a page. Retrieval diagnostics are for
    evaluators and are left out."""
    result, items = outcome.result, outcome.items
    order = ask.assign_order(result, items)
    lines = [outcome.question, ""]
    if result["evidence_sufficiency"] == "insufficient" or result.get("answer") is None:
        lines.append(REFUSAL_HEADING)
    else:
        lines.append(ask.substitute_markers(result["answer"], order))
    if result.get("limitations"):
        lines += ["", "Limits of this answer:"] + [f"- {ask.substitute_markers(line, order)}" for line in result["limitations"]]
    if result.get("unsupported_by_evidence"):
        lines += ["", "Not covered by the collection:"] + [f"- {line}" for line in result["unsupported_by_evidence"]]
    if result.get("ai_interpretation"):
        lines += ["", "AI interpretation (the assistant's own inference, not the author's stated position):"]
        lines += [f"- {ask.substitute_markers(line, order)}" for line in result["ai_interpretation"]]
    if order:
        lines += ["", "Sources:"]
        for handle, n in sorted(order.items(), key=lambda pair: pair[1]):
            lines.append(ask.footnote(n, next(item for item in items if item.handle == handle)))
    if not outcome.grounded:
        lines += ["", UNGROUNDED_NOTICE]
    return "\n".join(lines)


def copy_button(text: str, label: str, key: str, rich: str | None = None, disabled: bool = False) -> None:
    """One tap copies `text`. The label changes to "Copied" and the result is
    announced to a screen reader (WCAG 4.1.3). It falls back to the older copy
    command, because the app is served over plain http, where the clipboard API
    is not available. With `rich`, formatted HTML is copied, so that an editor
    keeps headings and lists on paste, with `text` as the plain form."""
    identity = re.sub(r"[^a-zA-Z0-9]", "-", key)

    def literal(value: str | None) -> str:
        return "null" if value is None else json.dumps(value, ensure_ascii=False).replace("</", "<\\/")

    st.html(
        COPY_SCRIPT.replace("__ID__", identity).replace("__LABEL__", html.escape(label))
        .replace("__DISABLED__", "disabled" if disabled else "")
        .replace("__TEXT__", literal(text)).replace("__HTML__", literal(rich)),
        unsafe_allow_javascript=True,
    )


def copy_block(outcome: ask.QueryOutcome, key: str) -> None:
    copy_button(copy_text(outcome), "Copy the answer", key=f"answer-{key}")


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
    """The thesis picker, at the top of the page: the built-in thesis first, then
    approved uploads."""
    documents = [default_document(settings)] + upload.ready_documents()
    by_id = {d.document_id: d for d in documents}
    if st.session_state.get("active_document") not in by_id:
        st.session_state.active_document = documents[0].document_id
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
    cost_estimate.clear()
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


KIND_LABELS = {"thesis": "A thesis", "article": "A journal article or book chapter"}


def render_identity_form(record: dict) -> None:
    proposal = record.get("identity_proposal") or {}
    confirmed = record["identity"]

    def start(name: str) -> str:
        return confirmed.get(name) or (proposal.get(name) or {}).get("value", "")

    is_article = record.get("kind") == "article"
    st.markdown("**Who wrote this, and when?** Nothing is cited until you confirm these.")
    for name in ("title", "author", "year") + (("doi",) if is_article else ()):
        source = (proposal.get(name) or {}).get("source", "")
        value = (proposal.get(name) or {}).get("value", "")
        label = "DOI" if name == "doi" else name.capitalize()
        st.caption(f"{label} — proposed from {source}." if value else f"{label} — {source}.")
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
        published = {}
        if is_article:
            st.caption("Where it was published. These go into the source line as you type them; nothing is "
                       "looked up. Leave empty what you do not know.")
            published = {
                "container": st.text_input("Journal, or the book the chapter is in", value=start("container"),
                                           key=f"container-{key}"),
                "volume_issue": st.text_input("Volume and issue, as printed (for example 12(3))",
                                              value=start("volume_issue"), key=f"volume-{key}"),
                "pages": st.text_input("Its page range (for example 45–67)", value=start("pages"), key=f"pages-{key}"),
                "doi": st.text_input("DOI", value=start("doi"), key=f"doi-{key}"),
            }
        if st.form_submit_button("Confirm identity"):
            if attempt(upload.confirm_identity, key, author=author, year=year, title=title,
                       short_title=short_title, **published):
                st.session_state.library_message = ("success", "Identity confirmed.")
            refresh()
    if confirmed["confirmed"]:
        st.success(f"Confirmed: {upload._provisional_document(record, None).reference()}", icon="✅")


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


@st.cache_data(show_spinner="Counting what would be sent for embedding…")
def cost_estimate(document_id: str, audited_hash: str | None) -> dict:
    """The estimate re-reads the whole PDF, so it is worked out once per audited
    extraction and not on every redraw. It is for display only: `upload.build_index`
    re-derives and re-checks the passages itself before anything is sent."""
    return upload.estimate_cost(document_id)


def render_record(record: dict) -> None:
    key, state = record["document_id"], record["state"]
    name = record["identity"]["title"] or record["source_filename"]
    with st.container(border=True):
        st.markdown(f"## {name}")
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
                estimate = cost_estimate(key, record.get("audited_corpus_sha256"))
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
        "Upload a thesis or an article as a PDF. The system measures its layout, extracts it, and checks "
        "the extraction against the PDF. **You read the report and decide.** Nothing is sent for "
        "embedding, and nothing is spent, until you approve."
    )
    st.caption(
        "Theses, journal articles and book chapters with a text layer, in one or two columns. Not "
        "scans. Uploads stay on this machine and are never committed or shared."
    )

    message = st.session_state.pop("library_message", None)
    if message:
        (st.error if message[0] == "error" else st.success)(message[1])

    kind = st.radio(
        "What is this document?", list(KIND_LABELS), key="upload_kind", horizontal=True, format_func=KIND_LABELS.get,
        help="A thesis prints a title page and chapters. An article is a journal article or a book "
             "chapter: its first page gives the title and authors, and it ends in a reference list.",
    )
    uploaded = st.file_uploader("PDF", type=["pdf"], key="thesis_upload")
    if uploaded is not None and st.button("Add to the library", type="primary"):
        with st.spinner("Storing, measuring and auditing…"):
            try:
                record = upload.receive(uploaded.getvalue(), uploaded.name, kind)
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
# Write an article (PLAN_V6) — a shell over the `article` package
# ---------------------------------------------------------------------------


@st.cache_resource(show_spinner="Reading what the sources offer…")
def load_workspace(document_id: str, others: tuple[str, ...] = ()) -> pipeline.Workspace:
    """The active document's filtered sources, with any further sources of the article."""
    return pipeline.open_workspace(upload.find_document(document_id),
                                   others=[upload.find_document(other) for other in others])


def workspace_key(workspace: pipeline.Workspace) -> str:
    """What a draft on the screen belongs to: its sources, in order."""
    return "|".join(document.document_id for document in workspace.documents)


def further_sources(document: Document) -> list[Document]:
    """Every other document that is ready to be drafted from."""
    available = [default_document(settings)] + upload.ready_documents()
    return [other for other in available if other.document_id != document.document_id]


def parse_outline(text: str) -> list[tuple[str, str]]:
    """One section per line: `Heading | the question the section must answer`."""
    outline = []
    for line in text.splitlines():
        if line.strip():
            heading, _, brief = line.partition("|")
            outline.append((heading.strip(), brief.strip()))
    return outline


def outline_from(topic: article_topics.Topic, kind: str = article_topics.SUMMARY) -> str:
    """An outline to edit, from the chapter's own section titles. No model is involved."""
    return "\n".join(f"{heading} | {brief}"
                     for heading, brief in article_topics.outline(topic, kind, pipeline.MIN_SECTIONS))


def persist(workspace: pipeline.Workspace, draft: pipeline.Draft) -> None:
    pipeline.save(workspace, draft, reference_text=st.session_state.get("article_reference", ""))


def plan_draft(title: str, outline: list[tuple[str, str]], topic: str | None, frame: dict,
               section_sources: list[list[str] | None] | None = None) -> pipeline.Draft:
    """The plan only: no model is called here."""
    origin = {I_WRITE: pipeline.RESEARCHER, GENERATE: pipeline.GENERATED}
    return pipeline.new_draft(
        title, outline, topic=topic, commentary=frame["commentary"], editorial=frame["editorial"],
        voice_exemplar=st.session_state.get("article_reference", "") if frame.get("voice_example") else "",
        exploration=frame.get("exploration"), section_sources=section_sources,
        introduction=origin[frame["introduction"]], introduction_text=frame["introduction_text"],
        transitions=origin[frame["transitions"]],
        transitions_text=[line.strip() for line in frame["transitions_text"].splitlines() if line.strip()],
        conclusion=origin[frame["conclusion"]], conclusion_text=frame["conclusion_text"],
    )


def carry_out(workspace: pipeline.Workspace, draft: pipeline.Draft) -> None:
    """Run what the plan still needs. The record is saved after every step, so a
    restart loses at most the step in flight; the draft can then be resumed."""
    pipeline.run(workspace, draft, reference_text=st.session_state.get("article_reference", ""))


ARTICLE_STEPS = ("Outline", "Frame and options", "Draft", "Review", "Finish")
STEP_OUTLINE, STEP_FRAME, STEP_DRAFT, STEP_REVIEW, STEP_FINISH = range(5)
PLAN_DEFAULTS = {
    "topic": OWN_TOPIC, "title": "", "outline": "",
    "introduction": I_WRITE, "introduction_text": "", "transitions": I_WRITE, "transitions_text": "",
    "conclusion": I_WRITE, "conclusion_text": "", "commentary": False, "editorial": False, "voice_example": False,
    # An exploration's record with the researcher's approval of its proposal (ADR 0014), or None.
    "exploration": None,
    # brief -> the document ids a section is narrowed to, of an article with several sources.
    "section_sources": {},
}


def article_plan() -> dict:
    return st.session_state.setdefault("article_plan", copy.deepcopy(PLAN_DEFAULTS))


def remembered(name: str, widget, *args, **kwargs):
    """Draw a plan widget and keep its value in the plan.

    Streamlit forgets a widget's value when the widget is not drawn. The plan is
    spread over several steps, so each value is kept in `article_plan` and put
    back when its step is shown again: nothing typed is lost by going Back.
    """
    plan, key = article_plan(), f"article_{name}"
    if key not in st.session_state:
        st.session_state[key] = plan[name]
    plan[name] = widget(*args, key=key, **kwargs)
    return plan[name]


def go_to_step(step: int) -> None:
    st.session_state.article_step = step
    st.rerun()


def step_header(step: int) -> None:
    """Where the researcher is, in words: no step is shown by colour or symbol alone."""
    st.caption(f"Step {step + 1} of {len(ARTICLE_STEPS)}")
    st.subheader(ARTICLE_STEPS[step], divider="grey")
    st.caption(" · ".join(
        f"{name} (done)" if index < step else f"**{name} (now)**" if index == step else name
        for index, name in enumerate(ARTICLE_STEPS)
    ))


def planned(plan: dict) -> tuple[list[tuple[str, str]], dict]:
    outline = parse_outline(plan["outline"])
    return outline, {
        "sections": len(outline),
        "editorial": len(outline) if plan["editorial"] else 0,
        "frame": 0,                                     # the frame is yours, or a suggestion asked for later
    }


def render_saved_articles(workspace: pipeline.Workspace, document: Document) -> None:
    saved = pipeline.saved_articles(document_id=document.document_id)
    if not saved:
        return
    with st.expander(f"Saved articles ({len(saved)})"):
        by_id = {row["article_id"]: row for row in saved}
        chosen = st.selectbox(
            "Saved article", list(by_id), key="article_saved",
            format_func=lambda i: f"{by_id[i]['title']} — " + (
                f"unfinished, {by_id[i]['model_calls_remaining']} model call(s) left"
                if by_id[i]["status"] == pipeline.DRAFTING
                else f"{by_id[i]['status']}, {by_id[i]['support']['notes']} notes"),
        )
        if st.button("Open this article"):
            try:
                # An article is reopened against the sources it was drafted from.
                ids = by_id[chosen]["document_ids"]
                opened = load_workspace(ids[0], tuple(ids[1:]))
                st.session_state.article_draft = pipeline.load(by_id[chosen]["folder"], opened)
                st.session_state.article_source_ids = list(ids[1:])
                st.session_state.pop("article_sources", None)
                st.session_state.article_draft_document = workspace_key(opened)
                go_to_step(STEP_REVIEW)
            except (pipeline.ArticleError, upload.UploadRefused, article_sources.NoFootnoteMap) as exc:
                st.error(str(exc))


def passage_label(workspace: pipeline.Workspace, chunk: dict) -> str:
    """A passage by where it is: page, section, and its source when there are several."""
    where = chunk.get("section") or chunk.get("chapter") or "no section title"
    source = workspace.document_of(chunk["chunk_id"])
    return f"{ask.page_phrase(chunk)} — " + (f"{source.author} ({source.year}), " if workspace.several else "") + where


def render_proposal(workspace: pipeline.Workspace, record: dict) -> None:
    """The agent's proposal, for the researcher to edit and approve. Nothing is drafted here."""
    proposal = record["proposal"]
    with st.expander("What the agent did — every step, with the pages each search returned"):
        st.code(article_trace.format_trace(article_trace.exploration_rows(workspace, record)), language="text")
    if proposal is None:
        st.warning(f"The exploration ended without a proposal: {record['stop']}"
                   + (f" ({record['stop_detail']})" if record.get("stop_detail") else "")
                   + ". Nothing was sent again. You can explore once more, or write the outline yourself.")
        return
    stamp = record["started"]
    st.markdown(f"**Proposed theme.** {proposal['theme']}")
    st.caption("A proposal, not a finding. Edit a heading or a question, untick what you do not want, read the "
               "passages, then use it. Each section you keep will be drafted only from the passages left ticked.")
    kept = []
    for index, section in enumerate(proposal["sections"]):
        st.markdown(f"**Section {index + 1}**")
        keep = st.checkbox("Keep this section", value=True, key=f"proposal_{stamp}_keep_{index}")
        heading = st.text_input("Heading", section["heading"], key=f"proposal_{stamp}_heading_{index}")
        question = st.text_input("The question it must answer", section["question"], key=f"proposal_{stamp}_question_{index}")
        passages = []
        for chunk_id in section["passages"]:
            chunk = workspace.by_id.get(chunk_id)
            if chunk is None:
                continue
            label = passage_label(workspace, chunk)
            if st.checkbox(f"Use the passage at {label}", value=True, key=f"proposal_{stamp}_{index}_{chunk_id}"):
                passages.append(chunk_id)
            with st.expander(f"Read the passage at {label}"):
                st.write(chunk["text"])
        # More passages for this question, from the coverage map: yours to add or leave.
        more = st.session_state.setdefault("proposal_more", {}).get((stamp, index), [])
        if st.button("Find more passages for this question (one embedding call, no model)",
                     key=f"proposal_{stamp}_more_{index}"):
            found = pipeline.coverage(workspace, question)
            more = [p["chunk_id"] for source in found["sources"] for p in source["passages"]]
            st.session_state.proposal_more[(stamp, index)] = more
        for chunk_id in more:
            if chunk_id in section["passages"]:
                continue
            chunk = workspace.by_id[chunk_id]
            label = passage_label(workspace, chunk)
            if st.checkbox(f"Add the passage at {label}", value=False, key=f"proposal_{stamp}_{index}_add_{chunk_id}"):
                passages.append(chunk_id)
            with st.expander(f"Read the passage at {label}"):
                st.write(chunk["text"])
        if keep:
            kept.append({"heading": heading.replace("|", "/"), "question": question, "passages": passages})
    if proposal["gaps"]:
        st.markdown("**Gaps the agent reported** (what it looked for and did not find)\n"
                    + "\n".join(f"- {gap}" for gap in proposal["gaps"]))
    if st.button("Use this proposal as my outline", type="primary"):
        try:
            approved = pipeline.approve(workspace, record, kept)
        except pipeline.ArticleError as exc:
            st.error(str(exc))
            return
        plan = article_plan()
        plan["exploration"] = approved
        plan["outline"] = st.session_state.article_outline = "\n".join(
            f"{section['heading']} | {section['question']}" for section in approved["approval"]["sections"])
        st.session_state.pop("article_exploration", None)     # approved: the proposal is now the outline below
        st.rerun()


def render_explore(workspace: pipeline.Workspace, document: Document) -> None:
    """The exploring agent (ADR 0014): it searches and proposes; the researcher decides."""
    if not st.checkbox("Let an agent explore the source and propose an outline (optional)", key="article_explore_open"):
        return
    st.caption(
        "You give a topic. The model searches this source, choosing each search itself, and ends with a "
        "proposal: a theme, an outline and the passages for each section. It writes no part of the article. "
        "The same topic can give a different proposal another time; every step is recorded."
    )
    topic = st.text_input("Topic to explore (yours to write)", key="article_explore_topic")
    budget = explorer.estimate(workspace)
    cost = ("No price is configured, so no cost is shown." if budget["cost_ceiling_usd"] is None
            else f"Cost, at most: ${budget['cost_ceiling_usd']:.2f}.")
    st.markdown(
        f"**The most this exploration can use**\n"
        f"- Model calls: {budget['model_calls_at_most']}\n"
        f"- Searches: {budget['searches_at_most']} (one embedding call each)\n"
        f"- Tokens: {budget['input_tokens_ceiling']:,} in, {budget['output_tokens_ceiling']:,} out\n"
        f"- {cost}\n\n"
        "This is a ceiling, not a forecast: a real exploration uses a fraction of it, and it is stopped "
        "if it reaches the ceiling."
    )
    accepted = st.checkbox("I accept this ceiling", key="article_explore_accept")
    if st.button("Explore", disabled=not (accepted and topic.strip())):
        with st.spinner("Exploring… every step is recorded."):
            run = explorer.explore(workspace, topic)
            explorer.save(run)
        st.session_state.article_exploration = {"document_id": workspace_key(workspace), "record": run.as_record()}
        st.rerun()
    held = st.session_state.get("article_exploration")
    if held and held["document_id"] == workspace_key(workspace):
        render_proposal(workspace, held["record"])


def render_step_outline(workspace: pipeline.Workspace, document: Document) -> None:
    render_saved_articles(workspace, document)
    step_header(STEP_OUTLINE)
    plan, listed = article_plan(), workspace.topics()
    st.caption("What the thesis covers, from the chapters and sections it prints. No model is involved.")
    labels = [f"{t.chapter} — {article_topics.count(t.passages)}, {t.pages}" + ("  (thin)" if t.passages < 3 else "")
              for t in listed]
    if plan["topic"] not in labels:
        plan["topic"] = OWN_TOPIC
    choice = remembered("topic", st.selectbox, "Topic", [OWN_TOPIC] + labels)
    topic = listed[labels.index(choice)] if choice != OWN_TOPIC else None
    if topic is not None:
        st.caption("Sections: " + "; ".join(f"{s.title} ({s.passages})" for s in topic.sections))
        kind = st.selectbox(
            "What each section should do", article_topics.OUTLINE_KINDS, key="article_outline_kind",
            help="“What it says” asks for a summary of each section. The others ask for a step in an "
                 "argument: a definition, how something works, a comparison, what follows, what is left open. "
                 "The questions are built from the thesis's own section titles, with no model. Edit them freely.",
        )
        if st.button("Fill the outline from this chapter's sections"):
            plan["outline"] = st.session_state.article_outline = outline_from(topic, kind)
            st.rerun()
    render_explore(workspace, document)
    remembered("title", st.text_input, "Title (yours to write)")
    if plan.get("exploration"):
        st.caption("This outline came from a proposal you approved. A line you leave as it is will be drafted "
                   "from the passages you approved for it; a line you rewrite is drafted by retrieval, as usual.")
    remembered(
        "outline", st.text_area,
        f"Outline — {pipeline.MIN_SECTIONS} to {pipeline.MAX_SECTIONS} sections, one per line: "
        "Heading | the question the section must answer", height=160,
    )
    if st.button("Next: frame and options", type="primary"):
        try:
            pipeline.check_outline(plan["title"], parse_outline(plan["outline"]))
        except pipeline.ArticleError as exc:
            st.error(str(exc))
            return
        go_to_step(STEP_FRAME)


def render_step_frame() -> None:
    if st.button("Back to the outline"):
        go_to_step(STEP_OUTLINE)
    step_header(STEP_FRAME)
    st.caption(
        "The introduction, transitions and conclusion are not on a page of the thesis, so none can be "
        "cited. Write them here if you have them. A box left empty leaves that part out. After drafting "
        "you can ask for a suggested introduction and conclusion, written from the article's own text, "
        "and edit it before it is used."
    )
    for part, hint in (("introduction", ""), ("transitions", " — one per line, in order"), ("conclusion", "")):
        remembered(f"{part}_text", st.text_area, f"Your {part}{hint} (optional)", height=90)
    remembered(
        "commentary", st.checkbox, "Include the model's own commentary (one paragraph per section at most)",
        help="Commentary is the model's inference, not the author's position. It is marked as such, "
             "and each paragraph needs your own verdict before the article can leave draft.",
    )
    remembered(
        "editorial", st.checkbox, "Editorial pass: rewrite each section for flow (one more model call per section)",
        help="The rewrite is kept only if it carries the same notes in each paragraph and adds no name, "
             "number or term. Otherwise the original stands and the reason is shown.",
    )
    with st.expander("Your own writing, for comparison (optional)"):
        reference = st.file_uploader("A piece of your published writing (text or Markdown)", type=["txt", "md"],
                                     key="article_reference_file")
        if reference is not None:
            st.session_state.article_reference = reference.getvalue().decode("utf-8", errors="replace")
        remembered(
            "voice_example", st.checkbox,
            "Show its opening to the editorial pass as an example of how I write",
            help="About 300 words of it are sent to the model with each section, for its voice only: the "
                 "length of your sentences and how you join them. A rewrite still may add no name, number "
                 "or term the section did not have. It needs the editorial pass switched on.",
        )
    if st.button("Next: check the plan", type="primary"):
        go_to_step(STEP_DRAFT)


def render_step_draft(workspace: pipeline.Workspace, document: Document) -> None:
    if st.button("Back to frame and options"):
        go_to_step(STEP_FRAME)
    step_header(STEP_DRAFT)
    plan = article_plan()
    outline, calls = planned(plan)
    st.markdown(f"**{plan['title'] or '(no title yet)'}**")
    approved = {(s["heading"], s["question"]): len(s["passages"])
                for s in (plan.get("exploration") or {}).get("approval", {}).get("sections", [])}
    st.markdown("\n".join(
        f"{n}. **{heading}** — {brief}" + (
            f" *(from {approved[(heading, brief)]} passage(s) you approved)*" if (heading, brief) in approved
            else " *(passages retrieved for this question)*" if approved else "")
        for n, (heading, brief) in enumerate(outline, start=1)))
    st.markdown("\n".join(
        f"- {part.capitalize()}: " + ("yours" if plan[f"{part}_text"].strip() else "left out for now")
        for part in ("introduction", "transitions", "conclusion")
    ))
    voiced = plan["editorial"] and plan["voice_example"] and st.session_state.get("article_reference")
    st.markdown(f"- Commentary: {'on' if plan['commentary'] else 'off'}\n"
                f"- Editorial pass: {'on' if plan['editorial'] else 'off'}"
                + (", with your own writing as its example of voice" if voiced else ""))
    st.caption(
        f"Drafting makes {calls['sections']} model call(s) for the sections and up to "
        f"{calls['editorial']} for the editorial pass. Nothing is "
        "retried. Each finished step is saved, so an interrupted draft can be resumed."
    )
    narrowed: list[list[str] | None] = [None] * len(outline)
    if workspace.several:
        ids = [d.document_id for d in workspace.documents]
        names = {d.document_id: f"{d.author} ({d.year})" for d in workspace.documents}
        kept = plan.setdefault("section_sources", {})
        st.markdown("**Which sources each section searches.** All of them, unless you narrow it.")
        for n, (heading, brief) in enumerate(outline):
            if (heading, brief) in approved:
                continue                                  # drafted from approved passages; nothing is searched
            mine = st.multiselect(f"Sources for “{heading}”", ids, default=[i for i in kept.get(brief, ids) if i in ids],
                                  format_func=names.get, key=f"section_sources_{n}")
            kept[brief] = mine
            narrowed[n] = mine if mine and len(mine) < len(ids) else None
    label = ("Coverage map: what each source holds for each section (no model call)" if workspace.several
             else "Preview what each section would draw on (no model call)")
    if st.button(label):
        with st.spinner("Finding the passages each question would draw on…"):
            st.session_state.article_preview = (
                pipeline.format_coverage([pipeline.coverage(workspace, brief, narrowed[n])
                                          for n, (_, brief) in enumerate(outline)])
                if workspace.several else
                pipeline.format_preview([pipeline.preview(workspace, brief) for _, brief in outline]))
    if st.session_state.get("article_preview"):
        st.code(st.session_state.article_preview, language="text")
        st.caption(
            "One embedding call per section, nothing generated. A low score is a reason to look at the "
            "question again; it is a diagnostic, not a measure of confidence."
        )
    if st.button("Draft the article", type="primary"):
        st.session_state.pop("article_preview", None)
        topic = None if plan["topic"] == OWN_TOPIC else plan["topic"].split(" — ")[0]
        try:
            draft = plan_draft(plan["title"], outline, topic, plan, narrowed)
        except pipeline.ArticleError as exc:
            st.error(str(exc))
            return
        persist(workspace, draft)           # the plan is on disk before the first call
        st.session_state.article_draft = draft
        st.session_state.article_draft_document = workspace_key(workspace)
        st.session_state.pop("article_item", None)
        with st.spinner("Drafting from the thesis… each finished step is saved."):
            carry_out(workspace, draft)
        go_to_step(STEP_REVIEW)


def render_section_choices(workspace: pipeline.Workspace, draft: pipeline.Draft) -> None:
    """What was left out is said in the open. The choices that are rarely changed are
    folded away, so the first note to judge is not pushed down the page."""
    changed = False
    reasons = [assemble.block_reason(section.outcome, section.error) for section in draft.sections]
    for index, (section, reason) in enumerate(zip(draft.sections, reasons)):
        if reason == assemble.INSUFFICIENT:
            st.warning(f"**{section.heading}** was not written: {reason}.")
            say = st.checkbox("Say so in the article, under this heading", value=section.state_gap,
                              key=f"article_gap_{index}")
            changed |= say != section.state_gap
            section.state_gap = say
        elif reason is not None:
            st.error(f"**{section.heading}** is blocked and left out: {reason}")
    drafted = [(index, section) for index, (section, reason) in enumerate(zip(draft.sections, reasons)) if reason is None]
    has_commentary = any(s.outcome and s.outcome.result.get("ai_interpretation") for s in draft.sections)
    if drafted:
        kept = sum(section.kept for _, section in drafted)
        with st.expander(f"Sections and commentary — {kept} of {len(drafted)} drafted sections kept"):
            for index, section in drafted:
                keep = st.checkbox(f"Keep section: {section.heading}", value=section.kept, key=f"article_keep_{index}")
                changed |= keep != section.kept
                section.kept = keep
            if has_commentary:
                show = st.checkbox("Show the model's commentary in the article", value=draft.commentary,
                                   key="article_commentary_shown")
                changed |= show != draft.commentary
                draft.commentary = show
    if changed:
        st.session_state.pop("article_item", None)      # the list of things to judge has changed
        persist(workspace, draft)
        st.rerun()


def review_items(article: assemble.Article) -> list[tuple[str, dict]]:
    """Everything that needs the researcher's verdict, in reading order: the notes,
    then each commentary paragraph that is printed."""
    return [("held", held) for held in article.held_back] + [("pair", pair) for pair in article.pairs] + [
        ("commentary", entry) for entry in article.commentary if entry["printed"]]


def is_judged(draft: pipeline.Draft, kind: str, item: dict) -> bool:
    if kind == "held":
        return False                                    # it leaves the list once deleted or kept
    if kind == "pair":
        return pipeline.pair_verdict(draft, item) is not None
    return bool(draft.commentary_verdicts.get(item["section"], {}).get("verdict"))


def render_pair(workspace: pipeline.Workspace, draft: pipeline.Draft, pair: dict,
                article: assemble.Article | None = None):
    """One sentence and one note it carries, beside the sentences of the cited passage
    that share most of its words. The matching only chooses what to show: the verdict
    is the researcher's, on reading."""
    chunk = workspace.by_id[pair["chunk_id"]]
    recorded = pipeline.pair_verdict(draft, pair) or {}
    source = workspace.document_of(pair["chunk_id"])
    st.markdown(f"**Sentence with note [{pair['n']}]**, in “{pair['heading']}” — "
                + (f"{source.author} ({source.year}), " if workspace.several else "") + ask.page_phrase(chunk))
    left, right = st.columns(2)
    with left:
        st.caption("The article says" + (" (edited by you)" if pair["edited"] else ""))
        st.markdown(f"> {pair['sentence']}")
    with right:
        matches = article_sentences.best_matches(pair["raw"], chunk["text"])
        st.caption("Closest sentences in the passage it cites, shared words in bold"
                   + (" (footnote text removed)" if pair["chunk_id"] in workspace.removed else ""))
        if not matches:
            st.warning("No sentence of the cited passage shares a word of substance with this one. Read the whole passage.")
        for match in matches:
            st.markdown(f"- {article_sentences.highlight(match.text, match.shared)}")
    for flag in pipeline.pair_flags(workspace, pair, article):
        st.warning(f"Check the attribution: {flag}.")
    with st.expander("The whole passage"):
        # Reflowed: the index keeps the PDF's line breaks, which read as ragged short lines.
        st.text(" ".join(chunk["text"].split()))
    if recorded.get("carried_over"):
        st.caption("Carried over: this verdict was given to the whole note, before sentences were judged one by one.")
    options = [NOT_JUDGED, *assemble.VERDICTS]
    key = pipeline.pair_key(pair).replace("|", "_")
    verdict = st.radio("Does the passage support this sentence?", options, horizontal=True,
                       index=options.index(recorded.get("verdict", NOT_JUDGED)), key=f"article_verdict_{key}")
    reason = st.text_input("Reason (optional)", value=recorded.get("reason", ""), key=f"article_reason_{key}")
    if recorded.get("verdict") == "does not":
        st.warning("Judged “does not”. The article stays a draft until this sentence is edited or deleted.")
    if recorded.get("verdict"):
        # Offered only once the researcher has judged: it is compared with a verdict, it never makes one.
        opinion = pipeline.opinion_on(draft, pair)
        if opinion is None:
            if st.button("Ask the model for a second opinion (one model call)", key=f"article_opinion_{key}"):
                with st.spinner("Asking whether the passage supports the sentence…"):
                    pipeline.second_opinion(workspace, draft, pair)
                persist(workspace, draft)
                st.rerun()
        elif opinion["opinion"] is None:
            st.caption("A second opinion was asked for and could not be given: "
                       + "; ".join(opinion["not_offered_because"]) + ".")
        else:
            st.info(f"**The model's reading, not a verdict: {opinion['opinion']}.** {opinion['reason']}")
            if opinion["opinion"] != recorded["verdict"]:
                st.warning(
                    f"It differs from your verdict ({recorded['verdict']}). Read the passage again. "
                    "Your verdict stands until you change it."
                )
    with st.expander("Edit or delete this sentence", expanded=recorded.get("verdict") == "does not"):
        st.caption(
            "Keep each marker such as [E1] exactly as it is: it ties the sentence to its passage. "
            "An edited sentence needs a fresh verdict."
        )
        wording = st.text_area("The sentence", value=pair["raw"], key=f"article_edit_{key}", height=110)
        save_edit, delete = st.columns(2)
        with save_edit:
            if st.button("Save my edit", key=f"article_save_edit_{key}", use_container_width=True):
                try:
                    pipeline.edit_sentence(draft, pair["sid"], wording)
                    persist(workspace, draft)
                    st.rerun()
                except pipeline.ArticleError as exc:
                    st.error(str(exc))
        with delete:
            if st.button("Delete this sentence", key=f"article_delete_{key}", use_container_width=True):
                pipeline.delete_sentence(draft, pair["sid"])
                persist(workspace, draft)
                st.rerun()

    def save() -> None:
        changed = (verdict, reason.strip()) != (recorded.get("verdict"), recorded.get("reason", ""))
        if verdict != NOT_JUDGED and (changed or recorded.get("carried_over")):
            pipeline.set_pair_verdict(draft, pair, verdict, reason)
    return save


def render_held_back(workspace: pipeline.Workspace, draft: pipeline.Draft, held: dict):
    """A sentence of section prose with no note. It is not printed until the researcher
    decides: nothing here may pass as sourced that is not."""
    st.markdown(f"**A sentence with no note**, in “{held['heading']}”")
    st.markdown(f"> {held['text']}")
    st.warning(
        "This sentence cites no passage, so it is not printed. Delete it, or keep it as your own "
        "words: it is then printed without a note and recorded as yours, not as the thesis's."
    )
    keep, drop = st.columns(2)
    with keep:
        if st.button("Keep it as my own words", key=f"article_keep_own_{held['sid']}", use_container_width=True):
            pipeline.keep_as_own_words(draft, held["sid"])
            persist(workspace, draft)
            st.rerun()
    with drop:
        if st.button("Delete this sentence", key=f"article_delete_{held['sid']}", use_container_width=True):
            pipeline.delete_sentence(draft, held["sid"])
            persist(workspace, draft)
            st.rerun()
    return lambda: None


def render_commentary(draft: pipeline.Draft, entry: dict):
    st.markdown(f"**Commentary in “{entry['heading']}”**")
    st.caption(
        "Commentary is the model's own reading. Nothing checks it but you, so it is never accepted on "
        "its own. Rejected commentary leaves the article and stays in the record."
    )
    st.markdown(f"> {entry['text']}")
    for flag in entry["flags"]:
        st.warning(f"Check who acts: this {flag}.")
    options = [NOT_JUDGED, *pipeline.COMMENTARY_VERDICTS]
    recorded = draft.commentary_verdicts.get(entry["section"], {}).get("verdict", NOT_JUDGED)
    verdict = st.radio("Keep this commentary?", options, horizontal=True, index=options.index(recorded),
                       key=f"article_commentary_verdict_{entry['section']}")

    def save() -> None:
        if verdict != NOT_JUDGED and verdict != recorded:
            pipeline.set_commentary_verdict(draft, entry["section"], verdict)
    return save


def render_review(workspace: pipeline.Workspace, draft: pipeline.Draft, article: assemble.Article) -> None:
    """One note on the screen at a time, with its sentence and the passage it cites."""
    items = review_items(article)
    if not items:
        st.info("This article has no notes to check.")
        return
    judged = sum(is_judged(draft, kind, item) for kind, item in items)
    if "article_item" not in st.session_state:        # open on the first one still to judge
        st.session_state.article_item = next(
            (i for i, (kind, item) in enumerate(items) if not is_judged(draft, kind, item)), 0)
    index = st.session_state.article_item = min(st.session_state.article_item, len(items) - 1)
    kind, item = items[index]
    st.caption(
        "The checks so far show that each note points at a real passage. Only reading shows whether "
        "the passage supports the sentence. Each sentence is judged with each note it carries; the "
        "article stays a draft until every one is judged."
    )
    st.markdown(f"**{index + 1} of {len(items)}** · judged so far: {judged} of {len(items)}")
    with st.container(border=True):
        save = (render_held_back(workspace, draft, item) if kind == "held"
                else render_pair(workspace, draft, item, article) if kind == "pair"
                else render_commentary(draft, item))
    back, forward = st.columns(2)
    with back:
        if st.button("Previous", disabled=index == 0, use_container_width=True):
            st.session_state.article_item = index - 1
            st.rerun()
    with forward:
        last = index == len(items) - 1
        if st.button("Save my verdict" if last else "Save and next", type="primary", use_container_width=True):
            save()
            persist(workspace, draft)
            if not last:
                st.session_state.article_item = index + 1
            st.rerun()


def render_terms(draft: pipeline.Draft, article: assemble.Article) -> None:
    """Terms the article uses in more than one section, with each sentence that uses
    them, section by section. A term can be faithful to its passage each time and
    still name two different things; only reading the uses together shows it."""
    shared = article_terms.shared_terms(article.pairs, article.own_words)
    if not shared:
        return
    with st.expander(f"Terms used in more than one section ({len(shared)})"):
        st.caption(
            "Check that each term means the same thing wherever it is used. The thesis itself may use "
            "one term in two senses on different pages; each sentence can then match its passage and "
            "the article still contradict itself. Nothing here is checked for you."
        )
        for term in shared:
            st.markdown(f"**{term.term}** — in {term.sections} sections")
            for section in sorted(term.uses):
                for use in term.uses[section]:
                    st.markdown(f"- *{draft.sections[section].heading}*: {use['sentence']}")


def render_resume(workspace: pipeline.Workspace, draft: pipeline.Draft) -> None:
    left = pipeline.planned_calls(draft)
    st.warning(
        f"This article was not finished: {left['model_calls']} model call(s) remain. What was drafted is "
        "saved. Resuming sends only what is missing; finished sections are not sent or charged again."
    )
    if st.button("Resume drafting", type="primary"):
        with st.spinner("Drafting what is missing… each finished step is saved."):
            carry_out(workspace, draft)
        st.rerun()
    with st.container(border=True):
        st.markdown(re.sub(r"^(#{1,2}) ", r"##\1 ", pipeline.render(workspace, draft).markdown, flags=re.MULTILINE))


def start_another() -> None:
    if st.button("Start another article"):
        for key in ("article_draft", "article_item", "article_plan", "article_exploration", "article_explore_open",
                    "proposal_more"):
            st.session_state.pop(key, None)
        for name in PLAN_DEFAULTS:
            st.session_state.pop(f"article_{name}", None)
        go_to_step(STEP_OUTLINE)


def render_step_review(workspace: pipeline.Workspace, draft: pipeline.Draft) -> None:
    start_another()
    step_header(STEP_REVIEW)
    if not draft.complete:
        render_resume(workspace, draft)
        return
    render_section_choices(workspace, draft)
    article = pipeline.render(workspace, draft)
    for item in article.blocked:
        if not item["what"].startswith("section:"):
            st.error(f"The generated {item['what']} is blocked and left out: {item['reason']}")
    for item in article.unnoted:
        st.warning(
            f"The generated {item['what']} has {item['sentences']} sentence(s) with no note. "
            "Check that they add no fact of their own."
        )
    render_review(workspace, draft, article)
    render_terms(draft, article)
    if st.button("Next: the finished article"):
        go_to_step(STEP_FINISH)


def render_frame_part(workspace: pipeline.Workspace, draft: pipeline.Draft, kind: str) -> None:
    """The introduction or the conclusion: the researcher's to write, with a suggestion
    on request. A suggestion is drawn from the article's own text and is only a text to
    edit: nothing is printed until the researcher says "use this"."""
    current = getattr(draft, kind)
    latest = (draft.frame_suggestions.get(kind) or [None])[-1]
    key = f"article_frame_{kind}"
    if f"{key}_incoming" in st.session_state:               # a new suggestion, put in before the box is drawn
        st.session_state[key] = st.session_state.pop(f"{key}_incoming")
    elif key not in st.session_state:
        st.session_state[key] = current.text if current is not None and current.origin != pipeline.GENERATED else ""
    st.markdown(f"**{kind.capitalize()}**")
    if latest and latest["rejected_because"]:
        st.warning("The suggestion asked for was not offered: " + "; ".join(latest["rejected_because"]) + ".")
    text = st.text_area(f"The {kind} (yours to write or edit)", key=key, height=150)
    ask_for, use = st.columns(2)
    with ask_for:
        article_word = "an introduction" if kind == "introduction" else "a conclusion"
        if st.button(f"Suggest {article_word} (one model call)", key=f"{key}_suggest", use_container_width=True):
            with st.spinner("Asking for a suggestion from the article's own text…"):
                suggestion = pipeline.suggest_frame(workspace, draft, kind)
            if not suggestion["rejected_because"]:
                st.session_state[f"{key}_incoming"] = suggestion["text"]
            persist(workspace, draft)
            st.rerun()
    with use:
        if st.button(f"Use this {kind}", key=f"{key}_use", type="primary", use_container_width=True):
            pipeline.set_frame(draft, kind, text)
            persist(workspace, draft)
            st.rerun()
    if current is not None and current.origin != pipeline.GENERATED:
        st.caption(f"In the article now, recorded as: {current.origin}.")
    elif current is not None:
        st.caption("In the article now as labelled commentary, from an earlier version. Using a text here replaces it.")


def render_step_finish(workspace: pipeline.Workspace, draft: pipeline.Draft) -> None:
    if st.button("Back to the review"):
        go_to_step(STEP_REVIEW)
    step_header(STEP_FINISH)
    article = pipeline.render(workspace, draft)
    state = pipeline.status(draft, article)
    counts = assemble.support_rate(pipeline.pairs_record(draft, article))

    if state == pipeline.REVIEWED:
        st.success("Reviewed: every note has your verdict.")
    else:
        st.info("Draft: not every note has been judged, a note judged “does not” is still in the article, "
                "or a commentary paragraph is waiting for your verdict.")
    st.markdown(
        f"**Sentences to judge:** {counts['pairs']} — supports {counts['supports']}, partly {counts['partly']}, "
        f"does not {counts['does not']}, not judged {counts['not judged']}"
    )
    with st.expander("Introduction and conclusion", expanded=draft.introduction is None and draft.conclusion is None):
        st.caption(
            "Neither is on a page of the thesis, so neither carries a note. Write them, or ask for a "
            "suggestion drawn only from the sections above, and edit it. What you use is printed as "
            "the article's own text and recorded as yours or as suggested by the model and accepted by you."
        )
        render_frame_part(workspace, draft, "introduction")
        render_frame_part(workspace, draft, "conclusion")
        article = pipeline.render(workspace, draft)

    # What leaves the app is what the record shows as reviewed (ADR 0008): the export is
    # locked until then, and the working draft on disk keeps its DRAFT line.
    blockers = pipeline.export_blockers(draft, article)
    exported = None if blockers else pipeline.export(workspace, draft)
    if blockers:
        st.warning("**Export is locked** until: " + "; ".join(blockers) + ".")
    else:
        st.caption(
            "The export opens with the AI disclosure and names the source, drops the draft line, and "
            "lists compact sources. It is exactly the article as you reviewed it."
        )
    copy_button(exported["markdown"] if exported else "", "Copy for Medium", key="medium",
                rich=exported["html"] if exported else None, disabled=bool(blockers))
    st.download_button("Download Markdown", exported["markdown"] if exported else "", file_name="article.md",
                       mime="text/markdown", disabled=bool(blockers))
    st.caption(f"Saved in `output/articles/{draft.article_id}/` with its record.")
    with st.container(border=True):
        # Shown two heading levels down so the page keeps one title and an unbroken
        # outline for a screen reader. The saved file is not changed.
        st.markdown(re.sub(r"^(#{1,2}) ", r"##\1 ", article.markdown, flags=re.MULTILINE))

    if article.limits_held_back:
        st.caption(
            f"{article.limits_held_back} limitation line(s) from the model are kept in the record only. The "
            f"article prints at most one per section, under “{assemble.NOT_COVERED_HEADING}”."
        )
    dashes = pipeline.em_dashes(draft)
    if dashes:
        st.caption(
            "Em dashes in print (your target is none): "
            + "; ".join(f"“{heading}” has {count}" for heading, count in dashes.items())
            + ". They are left as the model wrote them: replacing one changes how the sentence reads, so that is yours to do."
        )
    edited = [s for s in draft.sections if s.editorial]
    if edited:
        with st.expander(f"Editorial pass — {sum(1 for s in edited if s.editorial['accepted'])} of {len(edited)} rewrites kept"):
            for section in edited:
                outcome = section.editorial
                if outcome["accepted"]:
                    st.markdown(f"**{section.heading}** — rewrite kept.")
                else:
                    st.markdown(f"**{section.heading}** — rewrite rejected; the original stands.")
                    for reason in outcome["rejected_because"]:
                        st.warning(reason)
                if outcome["voice_after"]:
                    st.code(voice.format_comparison({"before": outcome["voice_before"], "after": outcome["voice_after"]}))
    with st.expander("Trace — every step this article has been through"):
        st.caption(
            "What went into each step, what came back, and why anything was blocked, rejected or held "
            "back. Passages are shown by page and score, and a score is a diagnostic, not a confidence. "
            "The same steps are drawn in `docs/workflows.md`."
        )
        st.code(article_trace.format_trace(article_trace.trace(workspace, draft)), language="text")
    with st.expander("Voice — plain counts beside your own writing"):
        columns = pipeline.voice_columns(article, st.session_state.get("article_reference", ""))
        st.code(voice.format_comparison(columns))
        st.caption("Surface counts only. There is no score: whether it is close enough is your call.")


def render_article(document: Document) -> None:
    st.title(VIEW_ARTICLE)
    st.header(document.short_title, divider="grey")
    # The article's further sources (PLAN_V7 §7). Kept apart from the widget that shows
    # them, because that widget is only drawn on the first step.
    available = {other.document_id: other for other in further_sources(document)}
    chosen = [i for i in st.session_state.get("article_source_ids", []) if i in available]
    try:
        workspace = load_workspace(document.document_id, tuple(chosen))
    except (article_sources.NoFootnoteMap, pipeline.ArticleError, upload.UploadRefused) as exc:
        st.error(str(exc))
        if chosen:
            st.session_state.article_source_ids = []        # fall back to the active document alone
            st.session_state.pop("article_sources", None)
            if st.button("Continue with this document alone"):
                st.rerun()
        return
    except BaseException as exc:  # SystemExit (no index / model mismatch) included
        st.error("The thesis could not be loaded, so no article can be drafted yet.")
        with st.expander(DIAGNOSTICS_LABEL):
            st.code(f"{type(exc).__name__}: {exc}")
        return

    # A draft belongs to the thesis it was drafted from. If another thesis is now
    # active it leaves the screen; it is still saved, under "Saved articles".
    if st.session_state.get("article_draft_document") != workspace_key(workspace):
        st.session_state.pop("article_draft", None)
    draft = st.session_state.get("article_draft")
    step = st.session_state.get("article_step", STEP_OUTLINE)
    # The steps before a draft plan it; the steps after it review it.
    step = max(step, STEP_REVIEW) if draft is not None else min(step, STEP_DRAFT)
    st.session_state.article_step = step

    if step == STEP_OUTLINE:
        st.markdown(ARTICLE_EXPLAINER)
        with st.expander("What an article may draw on"):
            st.caption(
                "Footnotes and the reference list usually give other writers' words, so they are never "
                "drafted from. This is a check on the shape of each page, not a proof."
            )
            for member in workspace.members:
                if workspace.several:
                    st.markdown(f"**{member.document.reference()}**")
                st.code("\n".join(member.sources.report.lines()))
        if available:
            if "article_sources" not in st.session_state:
                st.session_state.article_sources = chosen
            picked = st.multiselect(
                "Further sources for this article (optional)", list(available), key="article_sources",
                format_func=lambda i: available[i].short_title,
                help="Every source you add is searched for each section, with a few passages at most from "
                     "any one of them. Each sentence of the draft names the source it reports, and each "
                     "note says which source it is from.",
            )
            if picked != chosen:
                st.session_state.article_source_ids = picked
                st.session_state.pop("article_exploration", None)      # a proposal belongs to the sources it searched
                article_plan()["exploration"] = None
                st.rerun()
        render_step_outline(workspace, document)
    elif step == STEP_FRAME:
        render_step_frame()
    elif step == STEP_DRAFT:
        render_step_draft(workspace, document)
    elif step == STEP_REVIEW:
        render_step_review(workspace, draft)
    else:
        render_step_finish(workspace, draft)


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------


def render_chat(document: Document) -> None:
    vectors, chunks, manifest = collection_or_stop(document)

    st.title(PAGE_TITLE)
    st.header(
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
    st.markdown(PAGE_STYLE, unsafe_allow_html=True)

    # A button elsewhere asked to open a thesis: apply it before the widgets
    # that own these keys are drawn.
    if "pending_document" in st.session_state:
        st.session_state.active_document = st.session_state.pop("pending_document")
    if "pending_view" in st.session_state:
        st.session_state.view = st.session_state.pop("pending_view")

    # The view and the thesis are chosen at the top of the page, not in the sidebar.
    # On a phone the sidebar opens as a panel over the page and stays open after a
    # choice, so a control underneath it (such as "I accept this cost") could not
    # be tapped. The sidebar now holds only the question history.
    st.html('<div id="page-top"></div>')
    with st.container(key="topnav"):
        view = st.radio("View", [VIEW_ASK, VIEW_LIBRARY, VIEW_ARTICLE], key="view", horizontal=True,
                        format_func=VIEW_LABELS.get, label_visibility="collapsed")
    document = choose_document()

    if view == VIEW_LIBRARY:
        render_library()
    elif view == VIEW_ARTICLE:
        render_article(document)
    else:
        render_chat(document)
    with st.container(key="backtotop"):
        st.markdown("[Back to top](#page-top)")


main()
