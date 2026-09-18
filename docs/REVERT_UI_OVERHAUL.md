# Revert Runbook — Full CSS & Dashboard Overhaul

**Status: DRAFT ONLY.** Written during Phase 1 (proposal) of the UI overhaul,
before any implementation. Not committed to git until a plan is applied — see
the git status note at the end of this file. If Phase 2 changes the file
layout described in "Applies to" below, update this runbook to match before
relying on it; a stale runbook is worse than none.

**No database changes are part of this overhaul.** Every task (nav merges,
dashboard redesign, CSS tokens, stat-grid resize, qa-panel redesign, Useful
Kuwait Websites relocation) is front-end only — HTML template strings inside
`.js` page modules, plus `css/styles.css`. The one candidate for backend code
(a `GET /api/dashboard/recent-activity` endpoint, proposed only in Plan B's
"Latest Updates" widget) is a new read-only query against existing tables —
**no migration, no schema change, nothing to roll back at the database
layer** even if that option is chosen. This section exists for completeness,
per the task brief's explicit request, not because a real risk was found.

---

## 1. General revert strategy: `git revert`, not `git reset`

Every task below lands as its own commit (see the Phase 2 sub-phase plan).
Reverting means `git revert <sha>` for the specific commit(s) being undone —
**not** `git reset --hard` to an earlier point, which would also discard any
unrelated work made after this overhaul started. `git revert` is safe to run
even after the branch has been pushed and even if later commits touch
adjacent (but not overlapping) parts of the same files, which `git reset`
is not.

If a later commit *did* touch the same lines a revert needs (e.g. a hotfix to
`dashboard.js` landed after the overhaul), `git revert` will stop with a
conflict instead of silently discarding the hotfix — resolve it by hand,
keeping the hotfix and undoing only the overhaul's part.

No step in this runbook requires `--force` or `--force-with-lease`.

## 2. Per-task revert

| Task | Files touched | Revert action | Notes |
|---|---|---|---|
| 6 — CSS tokens & breakpoints | `css/styles.css` (global) | `git revert` the token-pass commit | Highest blast radius: touches shared rules every page depends on. See §3 for the staged rollback if a full revert is too broad. |
| 4 — stat-grid resize | `css/styles.css` (`.stat-card`, `.stat-grid`, its `@media` blocks) | `git revert` the stat-grid commit | Isolated to ~40 lines; low interaction with other tasks once Task 6's tokens exist. |
| 5 — qa-panel redesign | `css/styles.css` (`.qa-*`), `js/pages/dashboard.js` (`renderQuickActions`, `quickActionsSkeleton`) | `git revert` the qa-panel commit | Self-contained block; reverting restores the chip+pill version that predates this overhaul, not the pre-chip version from before the *previous* batch. |
| 3 — Useful Kuwait Websites → Dashboard | new `js/kuwait-websites.js`, `js/pages/dashboard.js`, `js/pages/search.js`, `css/styles.css` (`.ul-*`), `GUIDELINES.md`, `description.md` | `git revert` the relocation commit | Reverting restores the panel to `search.js` intact — the data module split means no content is retyped by the revert, only re-wired. |
| 7 — Dashboard upgrade | `js/pages/dashboard.js` (rewritten), new `js/action-feed.js`, `js/command-palette.js`, `js/recently-viewed.js`, `css/styles.css` (`.dash-*`, `.astream-*`, `.myweek-*`, `.trend-*`, `.watched-rail-*`, `.rv-rail-*`, `.cmdk-*`, `.qa-actions-*`), `js/i18n.js`, `GUIDELINES.md`, `description.md`, plus `js/pages/cases.js` (+2 lines: import + one call wiring Recently-Viewed's single write point in `openCaseDetail`) and `backend/app/schemas.py` + `routers/cases.py` + `routers/search.py` (added `created_at` to the existing `CaseOut` response shape, for the Filing Trend sparkline) | `git revert` the dashboard-upgrade commit(s) | No new endpoint was needed after all — an existing column (`Case.created_at`) was surfaced through the existing `GET /api/cases` response instead, so there is nothing to unwind at the database layer and no separate route to remove. Reverting `js/pages/cases.js`'s 2-line addition alongside the rest restores it exactly; nothing else in that file changed. |
| 1 — Cases + Search merge | `js/app.js` (`ROUTES`), `js/pages/cases.js`, `js/pages/search.js` (deleted or emptied), `js/i18n.js`, `GUIDELINES.md`, `description.md` | `git revert` the merge commit | See §4 — this is the one revert with a genuine two-way choice to make. |
| 2 — Notifications + Reminders merge | `js/app.js` (`ROUTES`), `js/pages/notifications.js`, `js/pages/reminders.js` (deleted or emptied), `js/i18n.js` | `git revert` the merge commit | Same shape as Task 1; see §4. |

## 3. Reverting Task 6 (tokens) without reverting everything built on it

Tasks 4, 5, 3, and 7 all *consume* the tokens Task 6 introduces. If a visual
regression traces back to Task 6 specifically, reverting it outright would
break every later task's CSS (undefined custom properties fall back to
`unset`, not to the old hardcoded value). Two safe paths, in order of
preference:

1. **Fix forward.** A token *value* is wrong far more often than the *token
   system* being wrong — change the value in `:root`, not the architecture.
   This never requires a revert.
2. **Revert Task 6 last, in isolation, after re-adding the specific hardcoded
   values Tasks 4/5/3/7 need.** Since every later task is a separate commit,
   `git revert` the Task 6 commit, then patch the (small number of) rules
   that now reference a removed token back to a literal value — a five-
   minute fix, not a cascading one, *because* each task stayed in its own
   commit.

This is the concrete reason the sub-phase order matters (§6.5) and why each
task is one commit, not a squashed batch.

## 4. Reverting a nav merge (Tasks 1 & 2): two sub-choices

"Restore the split pages" has two different endings depending on how much
was deleted, and the choice should be made *at merge time*, not left to be
guessed at revert time:

- **If `search.js` / `reminders.js` were kept as files** (their `render`
  logic moved into `cases.js`/`notifications.js`, but the old files still
  exist, e.g. re-exporting a sub-render function) — reverting `js/app.js`'s
  `ROUTES` array plus the merge commit restores the split instantly, no
  content loss.
- **If `search.js` / `reminders.js` were deleted outright** — `git revert`
  restores the deleted file's content from git history automatically (this
  is what `revert` does with a deletion), so the outcome is identical; the
  only difference is that the *live* filesystem has one fewer file to look
  at between "merge" and "revert."

**Recommendation for Phase 2:** delete the standalone files. `git revert`
handles file resurrection correctly either way, and keeping a half-used file
around as a re-export shim is exactly the kind of orphaned reference the
brief's TASK 1/2 discovery step was told to watch for.

### Restoring the 2-tab nav structure specifically
`js/app.js`'s `ROUTES` array (`js/app.js:18-36`) is the single source for the
sidebar, bottom-nav, and "more" sheet. Reverting the merge commit reverts
this array to its 9-entry form automatically — there is no separate nav
markup anywhere else to hand-restore.

## 5. Restoring the Useful Kuwait Websites panel to Search specifically

Independent of whether Task 1 (merge) was also applied: reverting Task 3's
commit moves `KUWAIT_WEBSITES` and its render function back into
`js/pages/search.js` and removes the Dashboard's copy, restoring the
`usefulWebsitesPanel()` call at the bottom of `search.js`'s `render()`
exactly where it is today (`js/pages/search.js:59`). No data is lost — the
array of 4 sites is version-controlled, not user-editable state.

## 6. Does any step need an app-pool recycle or a deploy cycle?

**No, for every task in this overhaul.** All of it is static `.js`/`.css`
under IIS's `no-store` cache policy — the fix from the prior batch. A revert
lands the moment `git revert` completes; the next page load (client-side
`no-store`, confirmed in the prior batch's verification) serves the reverted
file with no server restart. This differs from the earlier automated-number
work, which needed a database migration and therefore a coordinated cutover
— that precedent does **not** apply here, which is exactly why the brief's
constraint ("No DB migration unless absolutely required") holds throughout.

The one exception: if Plan B's optional `/api/dashboard/recent-activity`
endpoint is built, its revert removes Python code under `backend/app/`,
which **does** need the FastAPI process to pick up the change — i.e. the
same `httpPlatformHandler` restart-on-file-change behavior every other
backend change in this repo already goes through. Not a special step; the
same one every backend commit in this project already requires.

## 7. What this runbook does not cover

Documentation-only edits (`GUIDELINES.md`, `description.md`) are reverted by
the same `git revert` as their accompanying code commit — they carry no
separate risk and are not called out per-task above beyond the table in §2.

---

*This file is currently untracked in git (drafted per the Phase 1 brief,
"not committed until we apply a plan"). Once a plan is approved and Phase 2
begins, it will be committed alongside the first implementation commit so
the two ship together — a revert runbook that lands after the thing it
describes is not a revert runbook.*
