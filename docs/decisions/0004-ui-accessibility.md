# ADR 0004 — What the phone and laptop audit found, and what was changed

Date: 15 November 2026. Status: proposed (awaiting the researcher's approval).

## How it was audited

The real `app.py` was run with a scripted model and an offline embedding stand-in, and opened in
Chromium at three profiles: a laptop (1366×768), a phone (Pixel 7, 412 px wide, touch) and the same
phone in a dark theme. All views were walked: Ask questions, Thesis library, Write an article
(setup and a drafted article). Each was checked with axe-core 4.10 against WCAG 2.0/2.1/2.2 A and AA
and its best-practice rules, plus a measurement of control sizes and sideways overflow, and read
from screenshots.

This is an emulation. It was not run on the researcher's own phone or laptop, with a screen reader,
or on Safari.

## Findings and what was done

| # | Finding | Where | Done |
|---|---|---|---|
| 1 | **The sidebar could not be opened on a phone.** It starts closed below about 768 px, and the button that opens it sits in Streamlit's toolbar, which the page hid entirely to remove the Deploy button. Views and theses could not be changed. | every view, phone | Only the Deploy button and the main menu are hidden now. |
| 2 | Captions and quoted sentences were drawn at 3.68:1, below the 4.5:1 minimum. Captions here carry rules, not decoration. | every view | They take the theme's own text colour. No fixed colour is set, so dark themes hold too. |
| 3 | Heading levels skipped from 1 to 3; the article preview added a second level-1 heading. | every view | Title is level 1, the thesis line level 2, steps level 3. The preview is shown two levels down; the saved file is unchanged. |
| 4 | The cited passage sat in a fixed-height scrolling box that a keyboard could not scroll. | note review | The passage is shown whole. |
| 5 | Passages kept the PDF's line breaks and read as ragged short lines. | note review | Reflowed for display only. |
| 6 | Radio buttons and checkboxes were 22 px tall. | touch screens | 44 px on touch screens. |
| 7 | About a third of the first phone screen was empty above the title, and the title wrapped to three lines. | phone | Less top padding and smaller headings below 640 px. |
| 8 | "1 passages". | topic list | "1 passage". |
| 9 | No visible keyboard focus on some controls. | every view | A focus outline. |

No view scrolled sideways at either size, before or after.

## Left as found, because it is Streamlit's own markup

- The sidebar element carries `aria-expanded`, which its role does not allow (axe: critical).
- The button that opens the sidebar has an empty `aria-label`; a screen reader hears its icon name.
- The file uploader's drop zone has a presentation role and a label (axe: minor).
- Page content is not wrapped in landmark regions (axe: moderate).

These need a change in Streamlit or a move off it. Neither is proposed here (hard rule 10).

## Not covered

A screen reader pass, Safari and iOS, zoom to 200 %, and the app under a slow connection.
