# ADR 0007 — Navigation that stays in reach, an article written in steps, and a copy button that copies

Date: 15 November 2026. Status: proposed (awaiting the researcher's approval).

## What the researcher reported

After ADR 0004 the app was still not easy to use: the Copy control did not copy, switching view
meant scrolling to the top of the page, and "Write an article" did not feel like help.

## What was found

| Complaint | Cause, as tested in a browser |
|---|---|
| Copy does not copy | The control opened a box of text. The small copy icon inside it relies on the browser's clipboard API, which browsers provide only on HTTPS or localhost. The app is served at plain `http://` on a private address. On a plain-http page `window.isSecureContext` was false and `navigator.clipboard` was absent. |
| Scrolling to the top to switch view | The view picker sat at the top of the page and scrolled away. A drafted article with its notes is many screens long on a phone. |
| The article page is heavy | Topic, title, outline, three frame choices, options and an upload were on one page; after drafting, the article, voice counts and every note were stacked on one page again. |

## What the guidance says

Opened and read, through a tool that summarises pages, so wording may differ slightly.

| Source | Point |
|---|---|
| Apple, Human Interface Guidelines, tab bars | "Make sure the tab bar is visible when people navigate to different sections of your app." |
| Google, Android layout and navigation patterns | "The navigation bar can hold three to five navigation destinations." |
| Nielsen Norman Group, sticky headers | A pinned header raises discoverability but "inherently take[s] up space on the screen", more so on a phone. |
| GOV.UK Design System, question pages; complete multiple tasks | One question per page; a Back link; "make it clear to users which tasks they've completed". |
| Nielsen Norman Group, wizards | Buttons for next and previous steps, steps labelled descriptively, and "allow users to exit the wizard midway and save state". |
| MDN, `Clipboard.writeText` and Secure Contexts | "Writing to the clipboard can only be done in a secure context"; secure means HTTPS or a loopback address. |
| UK Ministry of Justice design system, copy button (experimental) | The label changes to "Copied" for four seconds and a polite live region announces it. |
| WCAG 2.2 | 2.4.11 Focus Not Obscured (a pinned bar must not hide the focused control), 3.2.3 Consistent Navigation, 4.1.3 Status Messages, 2.5.8 Target Size. |
| Nielsen Norman Group, mobile accordions; back to top | Accordions shorten long mobile pages; a Back to Top control suits pages longer than four screens. |

## Decisions

1. **A Copy button that copies.** One tap; the label changes to "Copied" and a `role="status"`
   region announces it. It tries the clipboard API and falls back to the older copy command, which
   works on plain http: tested by pasting the text back. A copied answer carries the question, the
   answer, its limits and its sources, built from `ask.substitute_markers` and `ask.footnote`; the
   retrieval diagnostics are left out. The finished article has the same button.
2. **The three views in one slim bar pinned to the top.** Short names (Ask, Library, Write) keep it
   to one row. Its options sit at the right, clear of the sidebar button on a phone and of the open
   sidebar on a laptop. Its background follows the theme. `scroll-padding-top` keeps a focused
   control from hiding under it.
3. **"Write an article" in five steps**, one on screen at a time: Outline, Frame and options,
   Draft, Review, Finish. A line says which step this is and which are done, in words. Back keeps
   what was typed. The Draft step shows the plan and the calls it will make before anything is sent.
4. **Review one note at a time**, with its sentence and passage, Previous and Save-and-next, and a
   count of how many are judged. A verdict is saved as it is given. Review opens on the first note
   still to judge. Commentary paragraphs follow the notes in the same sequence. Moving on without
   choosing records nothing.
5. **Less on each page.** Section choices are folded away unless something was blocked; voice
   counts, the source filter and the reference upload are collapsed. A "Back to top" link ends
   each page.

## Considered and not done

- **HTTPS on the Pi.** It would make the standard clipboard API work, and is good practice. It is
  new infrastructure (a certificate for a private address), and the fallback makes it unnecessary
  for copying. Left for the researcher to decide.
- **A floating Back-to-top button**, as Nielsen Norman Group describes. Tried: on a phone it lay
  over the text and the question box. It is a plain link at the end of the page.
- **The thesis picker in the pinned bar.** It made the bar two rows on a phone. It stays at the top
  of the page.
- **A bottom navigation bar.** The question box already occupies the bottom of the Ask view.

## Limits

- The copy fallback uses `document.execCommand("copy")`, which browsers mark as deprecated. It
  works today in Chromium; it was not tested in Safari or Firefox. If it is ever removed, the
  button will say it could not copy.
- Checked in Chromium at laptop, phone and dark-phone sizes with axe-core, and by walking the whole
  flow with a scripted model. Not checked: a real phone, Safari, a screen reader, 200% zoom.
- The pinned bar makes Streamlit's header see-through and lets taps pass through it, by CSS. A
  Streamlit upgrade may rename what that CSS targets; the tests hold the rules in place, not their
  effect in a browser.
- `light-dark()` needs a browser from 2024 or later; older ones fall back to the system `Canvas`
  colour.
