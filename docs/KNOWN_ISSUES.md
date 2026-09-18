# Known Issues

Issues found during the Sept 2026 UI overhaul that were deliberately **not**
fixed in the batch that found them. Each entry says why, so a later batch can
pick it up without re-investigating from scratch.

---

## KI-1 — Cases keeps the last status filter after navigating to plain `#/cases`

| | |
|---|---|
| **Found** | Merge A verification (Cases + Official Search Engine), Sept 2026 |
| **Severity** | Low — cosmetic / UX. No data is affected; the filter dropdown shows the filter that is actually applied. |
| **Pre-existing** | Yes, by code inspection: the lines responsible (below) are untouched by Merge A. Not a merge regression. (Not separately re-run on the pre-merge build.) |
| **Suggested batch** | Post-overhaul UI polish |

**Reproduction**

1. Open Cases already filtered — e.g. click the Dashboard's **Active Cases** card, which goes to `#/cases/active`.
2. Navigate to plain `#/cases` (e.g. sidebar **Cases**).
3. The **Status** dropdown still reads *Active* and closed cases stay hidden. A full browser reload clears it.

**Suspected cause.** `js/pages/cases.js` keeps `filters` as module-level
state. `render()` *sets* `filters.status = "active"` when the incoming route
segment is `active`, but nothing ever *resets* it when the segment is absent,
so the value outlives the navigation that set it. The likely fix is to derive
`filters.status` from the route on every render (reset to `""` when there is
no filter segment) rather than only assigning it in the one case.

**Why deferred.** Out of scope for Merge A, which was restricted to the page
merge itself; flagged there and deferred by review decision.

---

## KI-2 — Arrow-key tab switching on the Cases page: occasional dropped keypress in automated testing

| | |
|---|---|
| **Found** | Merge A verification, Sept 2026 |
| **Severity** | None observed for real users — see conclusion. Logged for traceability. |
| **Status** | Not reproducible as an application defect. |

**What happened.** During automated browser testing (Claude-in-Chrome), 3 of
10 scripted "reload → focus a tab → press an arrow key" trials ended with the
tab selection unchanged.

**Investigation.**
- In every trial where a capture-phase `keydown` logger confirmed the key had
  actually reached the page (4 of 4, including at 0.3s after reload — the
  timing that failed earlier), the tab switched correctly.
- The 3 failed trials were exactly the ones with no delivery confirmation.
- There is no code path that can drop the key: the hub (`js/hub.js`, which
  `js/pages/cases-hub.js` is built on) creates the tab buttons and attaches
  their `keydown` listener in the same
  synchronous block, so a tab can never be focusable before its listener
  exists.

**Conclusion.** A key-delivery artifact of the automation tool, not the
application. Re-test manually with a real keyboard if it is ever reported by
a user.

**Related fix made while investigating (KI-2).** Arrow keys were computed relative
to the *selected* tab; WAI-ARIA defines them relative to the *focused* tab.
The two only differ when focus is placed on an unselected (`tabindex=-1`)
tab programmatically, so no keyboard user could hit it, but the handler now
follows the focused tab.

---

## KI-3 — Every full shell render requests `/api/notifications` twice for the bell badge — **RESOLVED**

> **Resolved** in commit `fix(notif): dedupe notification count fetch on page
> load`: `refreshNotifBadge()` now has one call site, at the top of
> `handleRoute()` (before its early returns, so the access-denied path still
> updates the badge). Kept here for the record.

| | |
|---|---|
| **Found** | Merge B verification (Notifications hub), Sept 2026 |
| **Severity** | Low — one redundant read request per page load / language switch. No functional effect. |
| **Pre-existing** | Yes — both calls predate the overhaul. Not a merge regression. |
| **Suggested batch** | Post-overhaul UI polish |

**Observation.** Loading any page in a fresh tab records the badge request
twice before the page's own data requests (on the Notifications page, three
`/api/notifications` requests in total: two for the badge, one for the list).

**Cause.** `js/app.js::renderShell()` calls `refreshNotifBadge()` and then
calls `handleRoute()`, which calls `refreshNotifBadge()` again. Ordinary
navigation (which goes through `handleRoute()` alone) makes one request, as
intended.

**Likely fix.** Drop the call in `renderShell()`; the `handleRoute()` it
always ends with already covers it.

---

## KI-4 — Focus rings below WCAG 1.4.11 contrast on six components — **RESOLVED**

> **Resolved** in commit `fix(a11y): consistent high-contrast focus ring across
> all interactive elements`: all six rules below now use the outline from the
> "Fix" paragraph; `rgba(28, 74, 130, 0.25)` no longer appears in
> `css/styles.css`. Kept here for the record.

| | |
|---|---|
| **Found** | Item 4 audit (button sizing), Sept 2026 |
| **Severity** | Medium for accessibility — keyboard users can lose track of focus. No functional effect. |
| **Pre-existing** | `.btn` and `.doc-case-toggle` predate the overhaul; `.qcp-chip`, `.qcp-tile`, `.astream-row`, `.watched-rail-item` were added in sub-phases 3.2/3.4 copying that same pattern. |
| **Suggested batch** | Post-overhaul UI polish (deferred: that item's instruction was "no extra CSS polish") |

**Issue.** These `:focus-visible` rules draw
`box-shadow: 0 0 0 3px rgba(28, 74, 130, 0.25)`. Blended onto a white
surface that ring is roughly 1.5:1 against its surroundings — WCAG 1.4.11
asks 3:1 for a focus indicator.

| Line (css/styles.css, at time of logging) | Selector |
|---|---|
| ~739 | `.btn:focus-visible` (every button in the app) |
| ~1236 | `.qcp-chip:focus-visible` |
| ~1287 | `.qcp-tile:focus-visible` |
| ~1519 | `.astream-row.astream-clickable:focus-visible` |
| ~1653 | `.watched-rail-item:focus-visible` |
| ~2389 | `.doc-case-toggle:focus-visible` |

**Fix, already proven here.** `.hub-tab` and `.qa-action-btn` were moved to
`outline: 2px solid var(--color-primary-light); outline-offset: 2px;`
(~8:1 on the page background) during Merge A and Item 4. Apply the same to
the six rules above; grep for `rgba(28, 74, 130, 0.25)`.

---

## KI-5 — Arabic notifications contain English task titles

| | |
|---|---|
| **Found** | Final live verification (Arabic sweep of Notifications), Sept 2026 |
| **Severity** | Low — cosmetic i18n inconsistency; the content is still understandable. |
| **Pre-existing** | Yes — the text comes from stored data, not from anything the overhaul changed. |
| **Suggested batch** | i18n polish batch (post-overhaul) |

**Observation.** In Arabic, notifications about status-update requests read
e.g. `فات موعد المهمة: Status update requested for case 1123/2024 — …`: the
surrounding sentence is translated, the task title inside it is not.

**Cause.** Task titles are stored in the database as free text at creation
time, and the notification templates embed them verbatim. The English text
seen here specifically is the server's default note:
`backend/app/routers/search.py` (request-status-update endpoint) stores
`f"Status update requested for case {case_label}"` in `CaseReminder.note`
whenever the requester leaves the message blank, regardless of language.
A title the user typed is legitimately in whatever language they typed it.

**Suggested fix.** Store a language-agnostic key (plus the case label) for
system-generated titles and render it per language at display time, or keep
per-language title fields on reminders. Leave user-typed titles as typed.

**Why deferred.** Out of scope for the UI overhaul; logged by review decision.

---

## KI-6 — One-off: two narrow-width renders came up in Arabic under an English setting

| | |
|---|---|
| **Found** | Layout-restructure verification (Gate 1), Sept 2026 |
| **Severity** | None observed for real users — logged for traceability, by review decision. |
| **Status** | Not reproducible. |

**What happened.** The first 375px and 768px renders of the Dashboard came
up in Arabic although English was the saved language. Three repeat runs
were all English.

**Context.** Those renders used the fixed-width embedded-frame technique
(a same-origin `<iframe>` of the app at a set width), because the browser
tool's `resize_window` does not change the viewport. The live tab itself
never showed it, and no later verification (Merge A, Merge B, Items 1–9,
final sweep, Admin and Client) reproduced it.

**If it recurs.** Check what the language preference read at the moment the
frame's app booted; investigate then, per the review decision not to chase
an unreproducible artifact.

---

# Post-Overhaul Follow-Up

Verification and documentation gaps left open when the overhaul was accepted
(see `docs/FINAL_ACCEPTANCE_REPORT.md` §5 and §7). These are not known
defects. They are checks that were not run and a doc that was not updated,
and they are out of scope for the accepting session by review decision
(2026-09-19).

## FO-1 — 2560px and 4K viewport verification

| | |
|---|---|
| **Gap** | The overhauled pages were verified up to 1366px, with button-label checks up to 1920px. Nothing was rendered at 2560px or 4K. |
| **Why untested** | No 4K hardware; the browser tool's `resize_window` never changes the viewport, so widths were simulated with a fixed-width embedded frame. |
| **Risk** | Low but unverified: wide screens rely on `--content-max-lg` widening the existing layout, not on a layout (topology) change. |
| **To close** | Render Dashboard, Cases (both tabs), Notifications (both tabs) and Document Center at 2560×1440 and 3840×2160, EN and AR. Check content width, no stretched rows, no overflow. |

## FO-2 — Lawyer, Consultant and Delegate role verification

| | |
|---|---|
| **Gap** | Only Admin and Client were verified live. |
| **Risk** | Low: the merged hubs gate their sections with `visibleSections()`, which works the same for every role, and Admin (sees both tabs) and Client (sees one, no tab bar) cover both outcomes. These three roles were still not checked visually. |
| **To close** | Log in as each role; confirm the sidebar, which hub tabs show, the Dashboard quick actions, and that no request is refused with 403 in the network log. EN and AR. |

## FO-3 — Update `docs/REVERT_UI_OVERHAUL.md`

| | |
|---|---|
| **Gap** | The runbook was last updated with the Merge B commit (`a2b49f7`). It covers both hubs and the shared `js/hub.js`, including the order to revert them in. It predates everything after that: responsive buttons, clamp fonts, Items 1–9, X1/X2, Decisions A/B, and Tier 2. |
| **Risk** | Someone reverting today would have no guidance for those later commits. Most are small single-purpose commits that `git revert` cleanly on their own. The exception is Decision A (`7563f78`): it changes the backend, so reverting it needs a worker restart (app-pool recycle), and its tests revert with it. |
| **To close** | Add the post-Merge-B commits to the runbook's per-task table with their revert notes and ordering. |
