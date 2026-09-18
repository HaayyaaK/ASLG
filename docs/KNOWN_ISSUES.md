# Known Issues

Issues found during the Sept 2026 UI overhaul that were deliberately **not**
fixed in the batch that found them. Each entry says why, so a later batch can
pick it up without re-investigating from scratch.

---

## KI-1 — My Cases keeps the last status filter after navigating to plain `#/cases`

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
- There is no code path that can drop the key: `js/pages/cases-hub.js`
  creates the tab buttons and attaches their `keydown` listener in the same
  synchronous block, so a tab can never be focusable before its listener
  exists.

**Conclusion.** A key-delivery artifact of the automation tool, not the
application. Re-test manually with a real keyboard if it is ever reported by
a user.

**Related fix made while investigating.** Arrow keys were computed relative
to the *selected* tab; WAI-ARIA defines them relative to the *focused* tab.
The two only differ when focus is placed on an unselected (`tabindex=-1`)
tab programmatically, so no keyboard user could hit it, but the handler now
follows the focused tab.
