# ASLG — Hybrid Legal Web Portal

**A plain-language guide to what this system does, who can do what, and how to test it yourself.**

This document is written for everyone — whether you've never opened a terminal before, or you're a developer who wants a fast orientation. No prior knowledge of the codebase is assumed.

> **Looking for the end-user manual?** See **[`GUIDELINES.md`](GUIDELINES.md)** — a page-by-page guide written for staff who just want to use the portal, organised in the same order as the application's own navigation. This document is the technical/operational companion to it; where the two overlap they are kept consistent, and `GUIDELINES.md` is the one to hand to non-technical users.

---

## Table of Contents

**Understanding the product**
1. [System Overview — What Is This?](#1-system-overview--what-is-this)
2. [Who's Who — Roles & What They Can Do](#2-whos-who--roles--what-they-can-do)
3. [Core Features — How Everything Works](#3-core-features--how-everything-works)
4. [Step-by-Step Testing Guide](#4-step-by-step-testing-guide)
5. [Quick-Reference: Default Test Accounts](#5-quick-reference-default-test-accounts)
6. [Where Things Live (for developers)](#6-where-things-live-for-developers)

**Running & operating it**
7. [Architecture & Requirements](#7-architecture--requirements)
8. [Local Development Setup](#8-local-development-setup)
9. [Configuration Reference (.env)](#9-configuration-reference-env)
10. [Database](#10-database)
11. [Authentication & Login Credential Management](#11-authentication--login-credential-management)
12. [Production Deployment (IIS)](#12-production-deployment-iis)
13. [IIS Configuration Reference](#13-iis-configuration-reference)
14. [Verification Checklist](#14-verification-checklist)
15. [Troubleshooting](#15-troubleshooting)
16. [Rollback](#16-rollback)
17. [Security Notes](#17-security-notes)
18. [Responsive & UI Architecture](#18-responsive--ui-architecture)
19. [Maintenance](#19-maintenance)

---

## 1. System Overview — What Is This?

ASLG is an internal web portal for a law firm. Think of it as the firm's digital office: it keeps track of every case, every court hearing, every document, and every client — and it gives each person in the firm exactly the amount of access they should have, no more and no less.

It does two things at once:

1. **Manages the firm's own work** — cases, documents, internal notes, reminders, and client records, stored in the firm's own private database.
2. **Mirrors the official Kuwait Ministry of Justice (MOJ) e-Services search experience** — a search screen shaped exactly like the real government portal (same tabs: case number, sessions, experts, execution), so lawyers who are used to the official site feel instantly at home. In this build, that search runs against the firm's own case records; a future step would be pointing the same screen at the real MOJ system.

Everything runs on three pieces:

| Piece | What it is | Where it lives |
|---|---|---|
| **Frontend** (what you see) | Plain HTML/CSS/JavaScript pages — no heavy frameworks | `index.html`, `css/`, `js/` |
| **Backend** (the brain) | A Python program (FastAPI) that checks permissions and talks to the database | `backend/` |
| **Database** (the memory) | MySQL — stores every user, case, document record, and reminder | Runs as a Windows service; the actual file structure is in `db/schema.sql` |

The site speaks **Arabic by default**, laid out right-to-left like a real Arabic document, and can be switched to English (left-to-right) with one click — everything on screen mirrors itself automatically, down to the icons and sidebar position.

**On a phone**, the sidebar disappears entirely and is replaced by a bottom tab bar — the same style used by most mobile apps you already know. The four most relevant sections for your role sit along the bottom, and a **"More"** tab opens a slide-up sheet with everything else (remaining sections, the language switch, and Logout). This flips correctly in Arabic too — the tab bar and sheet mirror right-to-left, exactly like the rest of the app.

---

## 2. Who's Who — Roles & What They Can Do

The system recognizes **five roles**. Every one of the 9 real staff/client accounts in the system belongs to exactly one role:

| Person | Role |
|---|---|
| Tamer Salem | **Admin** (IT Administrator) |
| Hassan Falah, Jaber Barrak | **Lawyer** — and marked as **Owners** of the firm (see below) |
| Mohammad Ahmad, Mohammad Mahmoud | **Consultant** |
| Ahmad Sayed, Ahmad Saber | **Delegate** |
| Jarrah Saad, Fahad Fazzaa | **Client** |

**Owners.** Hassan Falah and Jaber Barrak carry an extra flag — "Owner" — on top of their Lawyer role. It's a small badge visible next to their name in Users & Permissions. Any admin can grant this same flag to another Lawyer later by ticking "Firm owner" when creating or editing their account. It only changes one thing: who they're allowed to hand a task to (see [3.4](#34-reminders--status-update-requests-and-owner-task-assignment)).

### What each role can actually see and do

Think of the table below as a light switch for each part of the app — each cell tells you how "on" that switch is for that role.

| Area of the App | Admin | Lawyer | Consultant | Delegate | Client |
|---|:---:|:---:|:---:|:---:|:---:|
| Dashboard (stats, hearing countdowns) | Full + task stats | Full + task stats | Full + task stats | Full + task stats | Limited (own cases only) |
| Official Search Engine | Full | Full | Can search & import | Can search & import | Hidden |
| Cases (view, notes, change stage) | Full control | Full control | Can view & add notes/change stage | View only | Their own case(s) only, read-only |
| Document Center (upload/preview/delete) | Full control | Full control | Can upload & delete | Can upload & delete | Can view/download own documents; can **upload only** during a temporary window a staff member opens for them |
| Reminders & Follow-ups | Full control, can assign to **anyone** | Full control, can assign to **anyone** (Owners) | Can create, only assignable to the case's own lawyer | Can view & resolve tasks *assigned to them*, cannot create new ones | Hidden |
| Notifications | Full | Full | Full | Full | Full (their own alerts) |
| Users & Permissions (admin panel, incl. System Maintenance) | Full control | Hidden | Hidden | Hidden | Hidden |
| Activity Log (audit trail) | Full control | Hidden | Hidden | Hidden | Hidden |

**In plain words:**
- **Admin** is the IT manager — the only one who can create/edit/delete staff accounts and reset passwords. They also have full access to everything else.
- **Lawyer** owns the casework — full control over their cases, documents, search, and reminders, but cannot manage other people's user accounts.
- **Consultant** helps run cases day-to-day — can add case notes, move a case to its next stage, upload documents, and search — but doesn't have full administrative control over a case (for example, can't do everything a Lawyer can).
- **Delegate** is a support/legwork role — can look everything up (cases, search, documents) but can't change a case's status. They also can't *create* reminders — but if a Lawyer or Admin hands them a task directly, they'll see it under "Reminders & Follow-ups" and can mark it done or dismiss it.
- **Client** is the firm's customer — logs in and sees **only their own case(s)** and **only their own documents**. They cannot search the official database, manage reminders, or see other clients' information. Everything they see is read-only — including document uploads, which are blocked unless a staff member has just opened a temporary window for them (see [3.3](#33-document-locker--secure-preview)).

Every one of these rules is enforced twice: once in what buttons/pages you see (so it's not confusing), and again inside the server itself — so even if someone tried to bypass the screen and call the system directly, the server independently checks "is this person actually allowed to do this?" and refuses if not. A Client, for example, physically cannot retrieve another person's case data no matter how they ask.

---

## 3. Core Features — How Everything Works

### 3.1 The Official Search Engine (5 tabs)

Found under **"Cases"** in the sidebar, as that page's second tab (see 3.2 below — the two used to be separate sidebar entries). It's built to feel just like the Kuwait MOJ e-Services search page, with five tabs of its own across the top:

| Tab | What you search by | What you get back |
|---|---|---|
| **بحث برقم القضية / Case Number Search** | Court level, case number, year, or a name/civil ID | Matching case(s), with status and assigned lawyer |
| **الدوائر والجلسات / Sessions & Circuits** | Circuit name/number, a date, or case number | Upcoming/past court hearings |
| **الخبراء / Experts** | Expert file number, expert's name, or case number | Court-appointed experts and their assignment status |
| **التنفيذ / Execution** | Execution file number, case number, or status | Judgment-enforcement files and amounts owed |
| **البحث الداخلي / Internal Firm Search** | Any free-text keyword | Searches the firm's own cases *and* document filenames at once |

**How to use it:** type your search terms into the boxes, hit **Search**, and a results table appears below.

**Result quality.** Case Number Search orders **exact matches first**, so searching `1123` puts case 1123 above any partial match. Every result on the Sessions & Circuits, Experts, and Execution tabs carries its **case context** — case number/year, current stage badge, parties, court, and a "Closed" badge where applicable. That context is resolved server-side through the record's own `case_id` foreign key on every request (`search.py::_case_ctx`), never by text matching, so a result can never contradict the case page. All search endpoints apply the same permission scoping as the rest of the app — a Client sees only their own cases and documents.

**Actions on every result row:**

| Action | Who sees it | What it does |
|---|---|---|
| **Open Case** | Everyone | Opens the case detail modal for the case behind that result |
| **Track / Tracked** | Everyone | Adds/removes the case from the user's tracked list. The button *shows* its state (outline "Track" vs. filled "Tracked") and persists across sessions. Tracking makes the user a **watcher**, which is what puts them on the pre-hearing notification list. Same relationship as the **Watching** toggle inside the case modal. The older label **"Import to Tracking List"** refers to this same action. |
| **Request Update** | Admin, Lawyer | Opens a dialog (choose a colleague, a reply-by date, an optional message) that creates a **real reminder** assigned to that person and notifies them. It never changes the case stage. Backed by `POST /api/search/request-update`. |

### 3.2 Case Management (filterable list + detailed view)

**One sidebar entry, two tabs (Merge A, Sept 2026 overhaul).** "Cases" is a single `ROUTES` entry rendered by `js/pages/cases-hub.js`, which mounts two existing page modules unchanged into contained tabs: **My Cases** (`js/pages/cases.js`) and **Official Search Engine** (`js/pages/search.js`, section 3.1 above). The hub is its own module because `search.js` already imports `openCaseDetail` from `cases.js`; `cases.js` importing `search.js` back would be circular. All the hub *behavior* below lives in the shared `js/hub.js::createHub`, which the Notifications hub (section 3.4) is built on too; `cases-hub.js` itself is only configuration.

- **Permission gate.** `visibleSections()` keeps only the tabs whose permission key (`cases`, `search`) is not `none`. A Client's `search` is `none`, so a Client gets My Cases alone and **no tab bar is rendered at all**; the server independently refuses every `/api/search/*` call for that role regardless.
- **URL.** `#/cases` is My Cases, `#/cases/search` the search tab. Any other second segment (`#/cases/active`, `#/cases/today-hearings`) is a My Cases filter read by `cases.js` itself, and is remembered so leaving the search tab and coming back restores the filtered list. Tab switches update the URL with `history.replaceState` (no history entry, no re-render). The old `#/search` route is rewritten to `#/cases/search` by `ROUTE_ALIASES` in `js/app.js`, so bookmarks keep working; a Client following such a link lands on My Cases with the segment dropped.
- **No re-render, no re-fetch — unless you click.** Each tab is mounted on first activation and then kept, so switching tabs by keyboard, route alias or initial load repeats no request and keeps search results and filters. The case list both tabs need (the table; the Official Sync case picker) comes from `api.js::listCasesCached`: one shared in-flight promise, reused for 60 seconds, dropped on failure, and invalidated automatically by every call that changes the list (`createCase`, `updateCaseStage`, `watchCase`/`unwatchCase`, `importRecord`/`untrackCase`) — so the cache can hide at most a minute of *other* users' changes, never the current user's own. This also fixed a pre-existing waste: the search tab re-requested the whole case list on every one of its five sub-tab clicks.
- **Clicking a tab is the refresh control** (there is no separate Refresh button). A click — on another tab or the one already selected — invalidates that tab's cached lists (`lists` in its section config) and reloads it, with a spinner in place of the tab's icon until the reload settles. My Cases re-renders (its filters are module state, so they survive). Official Search Engine calls `search.js::refresh()` instead, which re-reads tracked state and re-runs the current sub-tab's last search with the same inputs, so a refresh never wipes what the user typed.
- **Keyboard.** WAI-ARIA tabs pattern — arrow keys move between tabs (reading-direction aware, so ArrowLeft is "next" under RTL), Home/End jump; only the selected tab is in the Tab order.

**The My Cases tab** (page heading *Cases & Case Statements*). The case list is a **table** with two dropdown filters above it — **Status** (All/Active/Closed) and **Assigned Lawyer**. Arriving from a Dashboard stat card pre-applies the matching filter and shows a dismissible filter chip. There is no Kanban/board view.

Clicking any case opens its **detail view**, which shows:
- The case number, court, and assigned lawyer as badges
- A plain-language summary of what the case is about
- The **Case Timeline** (see the note below)
- **Notes** — a running log of internal commentary that staff can add to
- A **status dropdown** to move the case to its next stage (Lawyers, Consultants, and Admins only)
- A **"Watch Case" / "Watching"** toggle — the same relationship as **Track** in the search engine
- A **reminder-scheduling form** (see below)

> **Case Timeline — actual behaviour.** The timeline is a **read-only historical record**. Exactly one step is written by the application: `Case Filed` / `تسجيل الدعوى`, inserted automatically when a case is created (`routers/cases.py`, `CaseTimeline(...)`). Any further steps in an existing case came from seeded/imported data. **Changing the case stage does not add a timeline step** — `PUT /api/cases/{id}/stage` updates `cases.stage` and writes an audit entry, nothing else — and **there is no UI anywhere for adding a timeline step by hand.** A case showing only `Case Filed` is correct, not a bug. Admins and Lawyers get a **Request Update** button on the *last* timeline step; it creates a task for a person and does **not** advance the timeline or the case. This is documented the same way in `GUIDELINES.md` so users don't assume the timeline auto-advances.

#### User ↔ Case Linking (`user_case_links`)

Additive to the pre-existing Civil ID match (`cases.civil_id == users.civil_id`, which keeps working unchanged): an explicit link row lets a **System Admin** (any case) or the case's own **assigned Lawyer** (their case only) attach a **Client**-role user to a case regardless of `civil_id` — needed when a client has no Civil ID on file, or when a case's `civil_id` column is recording the *opposing* party's ID rather than the firm's own client's. Many-to-many: one client can be linked to several cases, one case can carry several linked clients (co-clients, power of attorney).

Managed from **Case Details → Linked Clients** (`js/pages/cases.js::wireLinkedClients`), backed by `GET/POST /api/cases/{id}/links` and `DELETE /api/cases/{id}/links/{link_id}` (`backend/app/routers/cases.py`). Unlinking **revokes** the row (`status: 'active' -> 'revoked'`, with `revoked_by`/`revoked_at` stamped) rather than deleting it, preserving who-linked/unlinked-whom-when. A MySQL 8.0.13+ **functional unique index** (`uq_ucl_active_pair`, on `(user_id, case_id, (CASE WHEN status='active' THEN 1 ELSE NULL END))`) guarantees at most one `active` row per pair at the database level — re-linking the same pair supersedes the old row, and this holds even under a race between two admins linking the same pair at once.

Both `cases.py::_scope_query`, `documents.py::_scope_query`, and `dashboard.py::_my_case_ids` now resolve a Client's visible cases as the **union** of civil_id-matched ids and actively-linked case ids, computed as a plain Python `set()` and filtered once via `Case.id.in_(...)`/`Document.case_id.in_(...)` against the base table, deliberately never via a JOIN against `user_case_links`, so a case connected two ways is still returned exactly once.

**Upload access — two independent, coexisting mechanisms.** The per-link `can_upload` flag (default off) grants a **standing** permission — no consumption on use, and no expiry unless a `can_upload_until` timestamp is set (column exists, reserved for a future expiring-standing-access UI; nothing writes it today). This sits alongside, not in place of, the older one-time `document_upload_grants` window described below — a client can hold both at once, on the same or different cases; `GET /api/documents/my-upload-access` now returns entries from both tables tagged with a `source: "grant"|"link"` field, and the Document Center renders one upload box per active source (`js/pages/documents.js::renderClientAccessBanner`, now a loop rather than "first grant only"), each labeled honestly ("Standing upload access" vs. "Expires at ...").

**Notifications.** `escalation.py::notify_case_stage_changed` and `notify_case_note_added` fire on `PUT /api/cases/{id}/stage` and `POST /api/cases/{id}/notes` respectively, targeting `case_client_recipient_ids()` — the same civil_id union active-link set, so a client connected both ways still gets exactly one notification per event, never two. The stage-change message carries the case number and the old-to-new stage; the note-added message never carries the note's own text, only that one was added — notes may hold internal-only commentary not meant for a client.

**Migration.** `user_case_links` is not created by the running application — its DB account (`aslg_app`) has no CREATE/ALTER/DROP privilege by design, the same constraint noted under Notifications later in this document. It was applied once by hand from `db/migration_user_case_links.sql` against a privileged account; rollback is a plain `DROP TABLE user_case_links;`, safe only once the corresponding application code is also reverted.

### 3.3 Document Locker & Secure Preview

Found under **"Document Center."** This is the case's file cabinet.

- **Uploading (staff)**: the page is an **accordion grouped by case** — there is no page-level dropzone for staff. Expand a case and press its **+** button (*"Add a document to this case"*) or **Add New Document**; a modal opens with a dropzone that also accepts click-to-browse, and a real progress bar per file. Because upload always starts from a case row, the case association is implicit and cannot be mis-selected. Accepted file types: PDF, DOCX, JPG, PNG — up to 25 MB each. Arriving via the Dashboard's **Pending Documents** card filters the accordion to pending documents.
- **Every document is stored for real** on the server's disk, linked to a specific case, and tagged with who uploaded it and when.
- **Preview**: clicking "Preview" securely fetches the file (you must be logged in — the link isn't public) and shows it right inside a popup window, with a download button.
- **Approval workflow**: every upload is stored with `status = "pending"` and is reviewed via **`PUT /api/documents/{id}/status`** (`{status: "approved"|"rejected", reason?: str}`).
  - **Authorization** is `require_module("documents", "full")` — deliberately narrower than the `"full"|"edit"` used for upload/delete, so only **Admin and Lawyer** may review; Consultant and Delegate (`edit`) and Client (`own`) get 403. The frontend gates the buttons on the same `perm === "full"`, but the server check is independent and authoritative.
  - **Idempotent by state**: re-applying the status a document already holds returns 200 with the unchanged row and writes **no** audit entry and **no** notification, so two reviewers clicking Approve on the same row produce one decision. The UI reinforces this by rendering only the button that would change something.
  - **Notification**: the uploader is notified privately (`notifications.user_id`, `type="document"`), with the rejection reason inlined. Reviewing your own upload notifies nobody. This deliberately bypasses `_notify_once` — see the docstring on `escalation.notify_document_reviewed` for why deduping on `message_en` would be wrong here.
  - **Audit**: `document_approve` / `document_reject`, with `meta` carrying `file_name`, `case`, `from`, `to`, and `reason`.
  - **`reason` is not persisted on the row.** The app DB account has no DDL privilege so no column can be added; the reason lives in the audit `meta` (retrievable, exportable) and in the uploader's notification.
  - **No path back to `pending`.** The endpoint accepts only `approved`/`rejected` — 400 otherwise. Re-opening a review means uploading a fresh copy. If "send back for review" is ever wanted it needs a deliberate product decision, not a quiet third enum value.
  - The Dashboard's **Pending Documents** card (`count(Document.status == "pending")`, scoped by the caller's document permission) is therefore a real work queue that drains as documents are reviewed.

> **Why this was built rather than documented away.** The UI already rendered a status badge on every document row — the Arabic literally read *بانتظار المراجعة* ("awaiting review") — the seed data ships a *"Document pending review"* notification, the column already had `approved`/`rejected` values, and a Dashboard card counted the queue. The workflow was presented to users as real and was simply missing its verb. Note the badge renderer was also a two-branch if/else that displayed **any** non-pending status as "Approved", so a rejected document would have shown as approved; it is now a three-state map.

**Clients can't upload by default.** A client only ever sees documents attached to their own case, and normally that page is read-only for them — no upload box at all. To let a client submit a document, an Admin, Lawyer, or Consultant clicks **"Grant Temporary Upload Access"** on the Document Center page, picks the client's case and a time window (15 minutes up to 24 hours), and confirms. For that window only, the client's Document Center shows a green banner — *"You have upload access — [case number], Expires at [time]"* — along with a normal upload box. The moment they successfully upload one file, the window closes itself automatically and the page reverts to blocked, even if time was left on the clock. If they never upload anything, it simply expires on its own. This means a client can never leave a standing ability to upload files sitting open — every single upload has to be freshly invited by staff.

### 3.4 Reminders & Status-Update Requests (and Owner task assignment)

Found under **"Reminders & Follow-ups."** This is how staff nudge each other about a case without a side conversation getting lost.

There are two kinds of reminders:
1. **Follow-up** — a simple "check on this by this date" note.
2. **Status Update Request** — a specific ask: "please move this case to [new stage] by this date."

**How it works:** From inside any case's detail view, an Admin, Lawyer, or Consultant can schedule a reminder — pick the type, a due date, and write a note.

- If you're a **Consultant**, it's automatically assigned to that case's own lawyer — you can't redirect it elsewhere.
- If you're an **Admin or an Owner-lawyer** (Hassan Falah / Jaber Barrak), the "Assign To" field becomes a full dropdown of every staff member in the firm — Lawyers, Consultants, and Delegates alike. This is the "direct task assignment" ability: an owner can hand a task straight to a Delegate or Consultant without routing it through the case's lawyer first.

The **Reminders & Follow-ups** page lists every reminder you created *or* were assigned. The person it's assigned to can mark it **Done** (which, for a status-update request, automatically applies the requested stage change to the case) or **Dismiss** it.

**Automatic pre-deadline alerts (3 layers).** Nobody has to manually chase a deadline. The engine (`backend/app/escalation.py`) runs every time reminders, notifications, or the dashboard are loaded.

> **This replaced an earlier overdue-based design.** The old engine fired at due+0, due+1 day, and due+3 days — i.e. *every* layer landed after the deadline had already passed. The governing business rule is now: **no overdue case notification is acceptable.** All three layers fire *before* the date.

| Layer | Hearing wording | Task wording |
|---|---|---|
| 1 of 3 | *Upcoming hearing — early notice* | *Task due soon — early notice* |
| 2 of 3 | *Hearing approaching — action required* | *Task due — action required* |
| 3 of 3 | *Hearing tomorrow — final alert* | *Task due tomorrow — final alert* |

- **Timing.** With comfortable notice (`COMFORTABLE_NOTICE_DAYS = 10`), the layers land at `STANDARD_OFFSETS_DAYS = (7, 3, 1)` days before the event. With short notice, the three layers are **compressed proportionally into the time available** rather than skipped — all three still fire, all still before the date.
- **The firm's business week.** Defined once, in `kuwait_time.py`, as `WEEKEND_WEEKDAYS = frozenset({4})` — **Friday only** (Python numbers Mon=0 … Sun=6). Sunday is the first business day; Monday–Thursday are working days; **Saturday is a working day**. `BUSINESS_WEEK_ORDER = (6, 0, 1, 2, 3, 5)` expresses the same week Sunday-first for anything that needs to present it in the firm's own order. `escalation.py` no longer holds its own copy of the rule; it calls `is_kuwait_weekend()`.

  > **Corrected this round.** The set was previously `{4, 5}` (Fri **and** Sat), which is the Gulf weekend as it was before Kuwait's private sector moved, but is not this firm's week. Every alert that landed on a Saturday was being pulled a day earlier for no reason. Only Friday is now avoided, and the shift is still always **earlier** (never later, which could cross the event date).
- **Ordering is guaranteed.** `_layer_moments()` enforces two invariants in priority order: (1) every moment is strictly before the event, and (2) the moments are strictly increasing. A backward clamp with `MIN_LAYER_GAP = 1 hour` pulls any layer that a weekend shift pushed past a later layer back in front of it. Because the clamp only ever moves a moment *earlier*, invariant (1) is preserved by construction. Verified by an exhaustive sweep: **20,146 scenarios, 0 ordering violations, 0 after-the-date violations.**
- **No duplicates.** `_notify_once()` dedupes on `(user_id, message_en)`, and every message is a pure function of `(event, layer)` — never of "now" — so repeated runs are idempotent. Verified live: repeated engine runs produced zero new rows and zero duplicate messages.
- **Recipients.** Hearing layers go to the case's **assigned lawyer plus every watcher/tracker**. Task layers go to the **assignee**. Hearings that are cancelled/completed/postponed, already in the past, or on a **closed case** are skipped entirely.
- **Overdue is reported, not escalated.** If a task deadline genuinely passes, a single, distinctly worded *"Task deadline passed"* message is sent. It is a report, not one of the three warnings.

**Smart Follow-up (automatic nudges).** If an assigned task sits untouched, the system chases it: first nudge after `NUDGE_FIRST_AFTER_DAYS = 2`, repeating every `NUDGE_REPEAT_EVERY_DAYS = 2`, capped at `NUDGE_MAX_COUNT = 3`, and stopping immediately when the assignee marks the task Done or Dismissed. The **assignee** gets the nudge; the **person who assigned it** gets a separate FYI copy. Nobody else is involved. Both are tagged **Smart Follow-up** in the UI (`isSmartNudge()` in `js/ui.js` matches on the message prefix, not merely `type === "system"`, so seeded system messages are not mislabelled).

**Notification privacy.** `notifications.user_id` targets one person; `notifications.target_role_id` targets a whole role. The scope query is `user_id == me OR target_role_id == my_role`, enforced server-side on every request. An Admin cannot browse another user's notifications. Verified live across all 9 accounts after the ordering fix: only intended recipients saw their notifications — zero leakage.

> `Notification.type` is a fixed MySQL ENUM (`hearing, status, document, system, reminder`) and the application DB account has no DDL privileges, so no new notification type can be added — new categories must reuse an existing enum value.

### 3.5 IT Admin — User & Credential Management

Found under **"Users & Permissions"** — visible only to the Admin role. This is the staff directory and its control panel.

- **Create a new user**: click "New User," fill in their name (in both Arabic and English), username, role, and a starting password.
- **Edit a user**: change their name, email, role, or active/inactive status at any time.
- **Reset a single password**: one click, type the new password, done.
- **Bulk actions**: tick the checkboxes next to several users at once, and a toolbar appears letting you **activate**, **deactivate**, or **reset the password for all of them together** — handy for onboarding/offboarding several people at once.
- **Delete a user**: removes their account entirely (you can't delete your own account, as a safety guard).
- The bottom of the page shows the full **permissions matrix** (the same table as Section 2) so an admin can see the rules at a glance.
- Any Lawyer can be flagged as a firm **Owner** here too — tick "Firm owner" in their edit form to give them the direct task-assignment ability described in [3.4](#34-reminders--status-update-requests-and-owner-task-assignment).

**System Maintenance panel** (bottom of the same page, Admin only). Four tools, two safe and two destructive:

| Tool | Risk | Endpoint | Behaviour |
|---|---|---|---|
| **Reset Client / Clear Local App Data** | Safe | — (client-side) | Clears this browser's `localStorage` and reloads. Server data untouched. |
| **Full Backup** | Safe | `GET /api/admin/backup` | Streams a ZIP containing a `mysqldump` of the database plus every uploaded document file. Read-only. |
| **Import / Restore Backup** | ⚠ Destructive | `POST /api/admin/restore-database` | Replaces the database and document store from a Full Backup ZIP. Takes an **automatic safety backup first**, validates the SQL dump, guards against zip-slip path traversal, requires the confirmation phrase `RESTORE DATABASE`, then signs everyone out. |
| **Factory Reset / Reset Database to Seed Data** | ⚠⚠ Destructive, irreversible | `POST /api/admin/reset-database` | Deletes every case, document, user, reminder, and the activity log, then re-seeds. Requires the confirmation phrase `RESET DATABASE`, then signs everyone out. |

Both destructive operations are serialised behind `_maintenance_lock`. Backup/restore shell out to `mysqldump`/`mysql` using `--defaults-extra-file` (never `-p<password>` on the command line) with `stdin=subprocess.DEVNULL` — without the latter, `mysqldump` fails under IIS with `OSError: [WinError 6] The handle is invalid`.

> **Restore is implemented and deployed but has not been executed end-to-end against production.** The app DB account holds only `SELECT, INSERT, UPDATE, DELETE ON aslg_legal.*` plus `USAGE ON *.*` — no `CREATE`/`DROP` — so no disposable test database could be provisioned, and running a real restore against `aslg_legal` would have destroyed live data. This limitation is stated in `GUIDELINES.md` too rather than glossed over.

### 3.5a Activity Log (audit trail)

Found under **"Activity Log"** — Admin only, and independently enforced server-side on every `/api/activity-log/*` route (the nav entry reuses the `users` permission key purely to decide whether to render). Columns: Time, User, Action, Type, Reference, IP Address. Recorded actions include successful and **failed** logins, logout, user create/update/delete, password reset, the three bulk user actions, document upload/**approve**/**reject**/delete/download-or-preview, temporary upload-access grants, case stage updates, and case note additions. **Export CSV** downloads the log. The log is append-only from within the application and never stores a password.

### 3.6 Dashboard Task Stats

Every role whose `reminders` permission is not `none` — Admin, Lawyer, Consultant, **and Delegate** — sees a **second row** of stat cards on the Dashboard, labeled "Tasks & Assignments," just below the usual four. Only the **Client** role, whose `reminders` permission is `none`, does not see it.

**Every stat card on both rows is interactive.** Each is a `role="button"`, keyboard-focusable (`tabindex="0"`, Enter/Space), shows its own action label, and navigates to the matching page with the filter already applied via a hash route (`#/<route>/<filter>`). The destination page renders a dismissible filter chip so the user can clear it.

| Card | What it counts | Navigates to |
|---|---|---|
| Unread Notifications | Notifications you haven't opened | `#/notifications` |
| Pending Documents | Documents awaiting review | `#/documents/pending` |
| Today's Hearings | Hearings scheduled today | `#/cases/today-hearings` |
| Active Cases | Cases not closed | `#/cases/active` |
| My Open Tasks | Reminders assigned to you, unresolved | `#/reminders/mine-open` |
| Overdue Tasks | Of those, how many are past due | `#/reminders/overdue` |
| Pending Status Requests | Status-update requests still waiting on you | `#/reminders/status-requests` |
| Tasks I Assigned | Reminders you created that are still open | `#/reminders/assigned-by-me` |

**Critical Upcoming Hearings** sits below the cards: hearings in date order with a live countdown in **days / hours / minutes** (turning red inside the last 24h, replaced by a "Completed" badge once it has passed). The seconds unit was removed — on a court date weeks away it was noise, and it forced a full row redraw every second for no information gain. The arithmetic is unchanged and the tick stays at 1s, so the minutes value is never stale. Each row carries an **Open Case** button, and — for Admin and Lawyer — a **Request Update** button using the same shared dialog as the search results and the case timeline (`js/request-update.js`).

**Useful Kuwait Websites.** Moved here from the Official Search Engine page in the Sept 2026 UI overhaul (`js/kuwait-websites.js`, imported by `dashboard.js`). Sits directly above Critical Upcoming Hearings: `.qa-action-btn` buttons (the Quick Actions row's own style) linking to the official Kuwaiti authorities (Ministry of Justice, E-Services of MOJ, PACI, Civil Service Commission), each button's `title` tooltip saying what the site offers. Links open in a new tab. Note: `tawtheeq.moj.gov.kw` does not resolve (DNS NXDOMAIN), so this entry is linked through the verified `https://eservices.moj.gov.kw` portal instead.

### 3.6a' Dashboard upgrade — priority-first panel rows (Sub-phase 3.4, Sept 2026 overhaul)

The Quick Actions row, the Quick Case Access panel and the stat grids keep their full-width position at the top of the page. Below them, `.dash-rows` stacks the remaining panels as full-width rows in this order: **My Week + Watched Cases** side by side (`.dash-row-split`, 50/50, collapsing to one column at ≤768px; a Client, who has no My Week, gets Watched Cases at full width instead), then **Useful Kuwait Websites**, then **Critical Upcoming Hearings**, then **Action Stream**. This replaced an earlier 2fr/1fr two-column grid on review. The widgets, all in `js/pages/dashboard.js` unless noted:

- **Quick Actions row** (`.qa-actions-row`) — up to six one-click shortcuts, each shown only if the signed-in role could actually use it: **New Case** and **Assign a Task** (navigate to Cases / Reminders & Follow-ups), **Mark All Notifications Read** and **Sync Deadlines Now** (real in-place actions — no navigation, the page's own stat cards refresh after), **Request Case Update** (opens a case picker, then the existing shared Request Update dialog), and **Check Official Portal** (navigates to `#/cases/search`, the Cases page's Official Search Engine tab). Distinct from the pre-existing "Quick Case Access" browse panel directly above it, despite the similar name. The Dashboard's **Useful Kuwait Websites** panel reuses this same `.qa-action-btn` style for its four links (icon + label; the per-site description moved to the button's `title` tooltip) rather than a parallel style, so the two rows can't visually drift apart.
- **Action Stream** (`.astream-*`) — a merged, reverse-chronological feed of the signed-in user's notifications and open tasks, built by `js/action-feed.js::mergeActionFeed()`. Rows sort overdue tasks first, then tasks due within 3 days, then everything else newest-first. Clicking a task row (only rows with a case behind them are clickable) opens that case. This merge function is written to be reused as-is for Sub-phase 3.6's Notifications + Reminders unification, not thrown away afterward.
- **My Week** — for any role with reminders access: tasks due in the next 7 days, tasks resolved (`CaseReminder.resolved_at`) in the past 7 days, and a small completion-rate bar.
- **Watched Cases rail** — every case the signed-in user is currently watching (`is_watching`, the same flag the case-detail "Watch Case" toggle already returns), with its next hearing time if one is scheduled.
- **Command Palette** (`js/command-palette.js`, Ctrl+K, or the "Quick search" button beside the header) — a searchable list combining page navigation, the six Quick Actions, and every case the user can see. Scope note: it is wired from the Dashboard page only in this sub-phase (the approved file list for 3.4 does not include `js/app.js`), so the shortcut currently opens the palette only while the Dashboard is the active page; making it a global shortcut is a one-line addition to `app.js`'s `boot()` in a later sub-phase.

**Removed after initial delivery.** Two widgets originally shipped in this sub-phase were removed from the Dashboard on review: the **Case Filing Trend** sparkline and the **Recently-Viewed Cases** rail. Their mount code, CSS (`.trend-*`, `.rv-rail-*`), and i18n keys were deleted outright, not left dead. Two pieces of supporting infrastructure were deliberately kept, at the user's direction, as harmless and possibly useful later:
- `Case.created_at` is still exposed on `CaseOut` (`backend/app/schemas.py`, `routers/cases.py::_to_out`, `routers/search.py::_case_to_out`) — no migration, no new endpoint, just an existing column surfaced through the existing response shape. It currently has no frontend consumer.
- `js/recently-viewed.js` and its single write point in `js/pages/cases.js::openCaseDetail` (the one function every "open a case" action in the app already funnels through) are still active — every case a user opens is still recorded to `localStorage`, namespaced per user id, even though nothing currently reads it back. Removing the write point was explicitly out of scope for this cleanup.

### 3.6a Forms, dates, and language

- **Mandatory field indicators.** Every required field across every form in the app carries a red `*` on its label (`label.required`) plus `aria-required="true"`, and every form shows the "\* Required field" note (`requiredNote()` in `js/ui.js`). Optional fields carry no star.
- **Kuwait business calendar (`backend/app/kuwait_time.py`).** Storage stays naive UTC — that convention is unchanged — but every *calendar* question is now asked in Kuwait terms, via one shared helper module rather than ad-hoc arithmetic at each call site:

  | Helper | Used by | Replaces |
  |---|---|---|
  | `kuwait_today_utc_range()` | `dashboard.py` — "Today's Hearings" | *replaced:* `datetime.combine(utcnow().date(), time.min/max)`, i.e. the **UTC** day |
  | `kuwait_day_utc_range(date)` + `parse_kuwait_date()` | `search.py` — Sessions & Circuits `session_date` filter | *replaced:* `session_at LIKE 'YYYY-MM-DD%'`, a **UTC**-day prefix match |
  | `kuwait_weekday(dt)` / `is_kuwait_weekend(dt)` | `escalation.py::_shift_off_weekend` | *replaced:* `moment.weekday()` on the raw UTC value, tested against a locally-declared weekend set |

  The three disagreed with the displayed time for the first three hours of every Kuwait day (00:00–02:59 Kuwait is the *previous* UTC date), so a 1:00 AM hearing was counted, searched, and weekend-tested against the wrong day. The window is **half-open** (`>= start`, `< end`) rather than `BETWEEN … time.max`, which silently excluded the final microsecond of each day. `parse_kuwait_date` returns `None` on junk so a malformed query string drops the filter instead of raising.

  Verified: all 365 day-windows are exactly 24h with no gap or overlap at the seams; 00:00/00:01/01:30/02:59 Kuwait all classify correctly (and all four were missed by the old logic); 22:00 UTC Thursday correctly reads as Friday in Kuwait. Re-running the notification sweep after the weekday change: **72,369 scenarios / 217,107 layer moments, 0 ordering violations, 0 after-the-date violations, 0 comfortable-notice layers on a Kuwait weekend.** Re-run again after the business-week correction (Friday-only weekend): **32,850 scenarios / 98,550 layer moments, 0 ordering violations, 0 after-the-date violations, 0 comfortable-notice layers on a Friday**, plus a day-by-day assertion of the whole week (Sun–Thu and Sat working, Fri not), the Thu-23:59/Fri-00:00/Fri-23:59/Sat-00:00 Kuwait boundaries, and 400 consecutive days confirming `_shift_off_weekend` always lands on a working day, never moves a moment later, and never moves it more than one day. Instant-vs-instant comparisons (`session_at >= utcnow()`, `due_at < now`) are timezone-independent and were correctly left alone.
- **Kuwait time everywhere.** The API returns naive-UTC ISO timestamps and MySQL sessions are pinned to `+00:00`. The frontend parses them with `parseServerDate()` (which appends `Z` so they are never read as browser-local) and formats with `timeZone: "Asia/Kuwait"` and `hour12: true`, uppercasing the meridiem — e.g. `09 Sep 2026, 09:30 AM`. Kuwait has had no DST since 1990, so the offset is a constant UTC+3. Seed data stores Kuwait-local intent converted to UTC (`seed.py::days_from_now`, `KUWAIT_UTC_OFFSET_HOURS = 3`).
- **Arabic/English parity.** Both dictionaries in `js/i18n.js` are kept at key parity; `t()` falls back to Arabic if an English key is ever missing. The language toggle also flips `dir` between `rtl` and `ltr` and persists the choice per device.

### 3.6b Printing (`js/print.js`)

Printing never prints the live page. A raw `window.print()` on this application would put the sidebar, the bottom navigation, every Approve/Reject/Delete button and whatever modal happens to be open onto the paper — and would **silently clip content**, because a browser paints only the visible slice of an `overflow` box and this UI puts wide tables inside `.table-wrap` (`overflow-x: auto`) and documents inside collapsible accordion bodies.

Instead each Print action hands `printRecord(spec)` a *description of the record* — title, identifying fields, and one or more sections of the data the page has already loaded — and the module composes a self-contained sheet into a `#print-root` element, prints it, and removes it again on `afterprint`.

- **`#print-root` is `display: none` on screen** and, inside `@media print`, is the only visible thing on the page: the print block sets `#app-root, .toast-container, .modal-overlay { display: none !important }` and `#print-root { display: block }`. Nothing interactive is composed into the sheet in the first place, so there are no controls to hide after the fact — verified live: **0 `button`/`input`/`select`/`a`/`nav` elements** in every generated sheet.
- **Same data as the screen.** The spec is built from the objects the page already rendered from, not from a second round of API calls that could return different values a moment later. Pages therefore keep the currently-displayed rows (`visibleDocs`, `visibleReminders`, `visibleNotifs`, `auditRows`, `filtered()`) for the button to close over.
- **Dates.** Every timestamp goes through `formatDate(..., { time: true })`, so paper gets the same Kuwait (UTC+3) 12-hour AM/PM rendering as the screen, and each sheet carries a footer saying so.
- **Language and direction** are read from the live document, so an Arabic session prints a right-to-left Arabic sheet (verified: `dir="rtl" lang="ar"`, Arabic ص/م meridiem) and an English session an LTR one.
- **Header block** on every sheet: firm name, **when** it was printed (Kuwait time) and **who** printed it.
- **Empty state.** A page with nothing to print raises a toast (`print_nothing_to_print`) instead of producing a blank sheet.
- **Pagination.** `thead { display: table-header-group }` repeats column headers on every page; `break-inside: avoid` keeps rows, list items and sections from splitting.

| Location | Button id | What it prints |
|---|---|---|
| Dashboard | `#dash-print` | The 8 stat figures, then Critical Upcoming Hearings |
| Cases → Official Search Engine tab (all 5 search tabs) | `#<tab>-print-slot-btn` | The criteria used + the result rows; **rendered only once a search returns rows** |
| Cases | `#cases-print` | The case list as filtered, naming the active filters |
| Case details modal | `#case-print` | Full case record: identity, court, lawyer, stage, status, parties, summary, timeline, every note |
| Document Center | `#docs-print` | The document *register* (case, name, size, review status, upload date) — not file contents |
| Reminders & Follow-ups | `#reminders-print` | The task list as filtered |
| Notifications | `#notif-print` | The signed-in user's own notification history |
| Activity Log | `#al-print` | The audit trail (Admin only); Export CSV remains the machine-readable route |

**Deliberately not added:** Users & Permissions. It holds staff account details and there is no routine need for a printed roster; adding a button there would be clutter with a privacy cost.

**Verification.** Every button was exercised against the live IIS application in both languages with `window.print` stubbed (the real dialog is modal and would freeze an automated browser session). Each produced a correctly composed `#print-root` with the right title, header, columns and row counts, and zero interactive elements. The `@media print` rules were read back out of the live stylesheet to confirm what they hide and show. **The operating system's own print-preview window was not opened during automated testing** — that is a one-keystroke manual check (`Ctrl+P` after pressing a Print button).

### 3.6c SPA render lifecycle — one container per navigation

Every page module is an `async render(container)`: it writes its markup, awaits its data, then goes back to `container.querySelector(...)` to wire buttons and fill panels. When the user navigated again while a request was in flight, the outgoing render resumed **after** the incoming page had taken over, and — because both renders shared the single persistent `#page-content` element — every lookup the outgoing render made returned `null`. That surfaced as a stream of uncaught `TypeError: Cannot read properties of null` in the console.

`app.js::handleRoute()` now **replaces the container element on each navigation** (same id, same class, new node). The outgoing render keeps a reference to the previous element, which is detached but still fully populated: its remaining lookups all resolve, its writes land harmlessly off-screen, and it finishes quietly. The incoming render gets a clean element of its own. No page module needs to know about this, and pages added later inherit the fix for free.

Individual `?.` guards were also added at the few post-`await` lookups that lacked them, as defence in depth, and every Print button is wired **before** its page's first `await` so it is live as soon as it is visible.

**Verified live:** before the fix, a 47-navigation sweep produced roughly ten uncaught exceptions per run across `cases.js`, `documents.js`, `reminders.js`, `notifications.js`, `users.js`, `activity-log.js` and `dashboard.js`. After it, **101 navigations at mixed cadence (60 ms and 320 ms) produced 0 uncaught exceptions**, and all eight pages still render their content.

### 3.6d The `reportAllChanges` / `startTime` console error

A recurring browser-console error was reported:

```
Uncaught TypeError: Cannot read properties of undefined (reading 'startTime')
    at et.reportAllChanges (<anonymous>:2:19429)
    ... at requestIdleCallback
```

**It is not application code.** Evidence, in order of strength:

1. `reportAllChanges` appears **zero times** in the entire source tree (`js/`, `backend/`, `css/`).
2. `index.html` on disk contains **exactly one** `<script>` tag: `js/app.js`. Requesting the origin directly (bypassing Cloudflare, with a `Host:` header against `127.0.0.1`) returns that same single script tag.
3. **Cloudflare's edge injects a second script** into the HTML — but only on real browser navigations, which is why a plain `curl` misses it. With `Accept: text/html` and `Sec-Fetch-Dest: document` the response gains a `<script type="module" src="https://static.cloudflareinsights.com/beacon.min.js/...">` carrying `data-cf-beacon='{"version":"2024.11.0","token":"...","r":1,"spa":2}'`. Confirmed present in the live DOM, and `window.__cfBeacon` is set at runtime.
4. That beacon is a bundle of **Google's `web-vitals`** library: `reportAllChanges` occurs in it 16 times, it wraps its reporters in `requestIdleCallback`, and it initialises `onLCP(N,{reportAllChanges:true, reportSoftNavs:true})`, `onINP(N,{reportSoftNavs:true})` and `onCLS(N,{reportAllChanges:true, reportSoftNavs:true})`. The injected `"spa":2` maps to its `SpaMonitoringType.SoftNavigationHeuristics` — the experimental soft-navigation path, which this hash-routed SPA exercises constantly.
5. Every precondition of that path holds in the reporting browser (Edge/Chromium 152): `PerformanceObserver.supportedEntryTypes` includes `soft-navigation`, and `PerformanceSoftNavigation.prototype.getLargestInteractionContentfulPaint` is a function. The library dereferences `metric.entries[0].startTime` when building attribution; on a soft-navigation reset the metric can be reported with an empty `entries` array — which is exactly `undefined.startTime`.

**Status: no longer reproducing.** The error only ever appeared in stress runs in which **the application itself was also throwing** the render-lifecycle exceptions described in [3.6c](#36c-spa-render-lifecycle--one-container-per-navigation) — renders that aborted mid-flight, leaving route transitions with no painted content for the metric to attribute. Since that fix it has not recurred in **around 210 SPA navigations**, 110 of them with the Cloudflare beacon active and unblocked.

**The limits of that conclusion, stated plainly.** The throwing frames are `<anonymous>` — a script with no URL — so the exact injected instance could not be pinned by URL the way this application's own modules can be. That contrast is itself part of the proof: our modules' errors carry `https://app.alsaiflegalgroup.com/js/pages/*.js` in their stacks, and this one carries nothing. The code is third-party and outside this application's control, so it cannot be *guaranteed* never to fire again.

**If it ever returns, there are two real fixes — neither of them a workaround:**

| Option | How | Trade-off |
|---|---|---|
| **Turn the beacon off at Cloudflare** *(recommended)* | Cloudflare dashboard, the zone for `app.alsaiflegalgroup.com`, **Analytics & Logs -> Web Analytics**, remove or disable automatic setup | Removes the buggy script entirely. Cloudflare Web Analytics stops collecting. Only the account owner can do this. |
| **Confine script execution to this origin** | Add `<meta http-equiv="Content-Security-Policy" content="script-src 'self' 'unsafe-inline'" />` to `index.html` | Blocks the injected beacon from executing — **tested against the live site: the app loaded and behaved normally and `window.__cfBeacon` was never set**. Also a genuine hardening for a legal-records portal. Same analytics trade-off. `'unsafe-inline'` is needed by the one inline `onerror` logo fallback in `ui.js::brandMark`. |

Neither was applied, because the error stopped once the application's own exceptions were fixed, and disabling the firm's analytics is a business decision rather than a developer's. Both were tested and are one line away.

**What was explicitly *not* done:** the error was never suppressed, filtered out of DevTools, wrapped in a blanket `try/catch`, or otherwise hidden.

### 3.6e Client IP resolution in the Activity Log (`backend/app/client_ip.py`)

**What was wrong.** The Activity Log's IP Address column stored
`request.client.host`, which behind this deployment is always the loopback
address of the hop in front of the application. Worse, uvicorn's
`--proxy-headers` (on by default, and trusted because our peer *is* 127.0.0.1)
rewrote `request.client` from the `X-Forwarded-For` header IIS sets — and IIS
writes that header in a non-standard `address:port` form describing its **own**
peer. The result: every login was recorded as `[::1]:<ephemeral port>`, which
looked like seventeen different addresses in the audit trail when it was one
machine talking to itself. **No real client address was ever captured.**

**The actual request path**, established by inspecting the running host:

| Hop | What it is | What it contributes |
|---|---|---|
| Browser / device | The user | — |
| Cloudflare edge | TLS terminates here | Adds `CF-Connecting-IP` — the only party that sees the real visitor |
| `cloudflared` | A **Cloudflare Tunnel**, running as the `Cloudflared` Windows service on this host, outbound-only | Connects to IIS over **loopback**, so IIS sees the client as `::1` |
| IIS `:80` | `*:80:app.alsaiflegalgroup.com` | Sets `X-Forwarded-For` to its own peer, as `[::1]:51203` |
| `httpPlatformHandler` → uvicorn `127.0.0.1` | The application | Peer is always loopback |

**The trust boundary.** `CF-Connecting-IP` is an ordinary request header and
anything able to reach IIS directly can set it to any value. This host is *not*
provably unreachable except through the tunnel — Windows Firewall carries an
inbound allow rule for TCP/80 (`World Wide Web Services (HTTP Traffic-In)`) and
the machine holds a globally-routable IPv6 address. So the header is never
trusted on its own. Instead the resolver uses the one thing an outside caller
cannot forge — **IIS's own view of who connected to it**:

| IIS's peer (the **right-most** `X-Forwarded-For` entry) | Conclusion | Recorded |
|---|---|---|
| Loopback (`::1` / `127.0.0.1`) | Came through `cloudflared` on this host | `CF-Connecting-IP` |
| Anything else | Someone reached IIS directly; any CF header is forged | The address IIS actually saw |
| Header absent | No reverse proxy in front (local run) | Our own TCP peer |

> **Right-most, not left-most — and this was a real bug, not a stylistic
> choice.** `X-Forwarded-For` is *appended* to by each hop, so it reads
> oldest-first: `<whatever the caller sent>, <hop>, <hop>`. The left-most entry
> is conventionally "the original client", but only when every hop is trusted.
> Here the caller can simply send an `X-Forwarded-For` of their own and our
> infrastructure appends *after* it rather than replacing it.
>
> The first implementation read the left-most entry. Sending
> `X-Forwarded-For: 1.2.3.4` through the live site made the Activity Log record
> `1.2.3.4` — a working audit-log spoof, found by testing rather than by
> reasoning, and now fixed. The right-most entry is the one our own front-most
> hop appended, after any caller-supplied text and with nothing downstream able
> to add to it; it is the only entry in the header a caller cannot influence.
>
> Two rows written during that test (`__xff_probe`, `__xff_chain_probe`) carry
> the spoofed `1.2.3.4`. They are left in place: audit records are not deleted
> to tidy away a finding.

**Cloudflare rejects a client-supplied `CF-Connecting-IP` outright** — such a
request is answered `403` at the edge and never reaches the origin, verified
live. That is a useful extra layer but it is not what the application relies
on: the origin is reachable without Cloudflare (see the firewall note above),
so the trust rule has to hold on its own, and it is the unit suite rather than
the live test that exercises that path.

The failure mode is deliberately the safe one: when in doubt the log records the
address it can see rather than the one it was told about, so it can under-report
but can never be made to name an innocent third party. Values are parsed with
`ipaddress`, so a junk or hostile header is dropped rather than stored, and the
stored value never carries a port.

**`web.config` change.** uvicorn is now started with `--no-proxy-headers`, so
`request.client` is the genuine TCP peer and every forwarded-header decision is
made in one reviewed place instead of being pre-empted by uvicorn's own
middleware. The flag is load-bearing and commented as such in `web.config`.

**Verified end to end on the live site.** A login through
`https://app.alsaiflegalgroup.com/` recorded
`2a00:1851:801d:af45:…`, byte-identical to the address
`https://www.cloudflare.com/cdn-cgi/trace` reports for the same connection —
where the immediately preceding rows still read `[::1]:59500`. Seventeen
trust-boundary unit tests cover the hostile cases (forged `CF-Connecting-IP`
from a direct LAN hit, a direct public-IPv6 hit, a direct hit on uvicorn,
caller-prefixed `X-Forwarded-For` chains of several entries, junk and
injection-shaped header values) and all pass, alongside 14 context-propagation
tests covering both the `async def` and threadpool paths.

Live spoofing was re-tested against the deployed fix with the exact requests
that had succeeded before it: `X-Forwarded-For: 1.2.3.4`, a three-entry forged
chain, and a forged loopback value all recorded the real client address.
`X-Real-IP` and `True-Client-IP` are not read at all and were confirmed to have
no effect.

**Coverage: every audited action.** The address is resolved once per request
and published on a `ContextVar` by `ClientIPMiddleware`; `audit.log_activity()`
reads it by default. All 21 `log_activity()` call sites across the 7 routers
therefore record it without any of them asking, and a router added later
inherits the behaviour for free. Threading a `Request` object through seven
routers was rejected as the alternative: it would have meant 21 chances to get
it wrong, or to quietly reintroduce `request.client.host`.

Mechanics worth knowing:

- The middleware is a **plain ASGI callable, not a `BaseHTTPMiddleware`**, and
  is registered *first* in `main.py` so Starlette places it innermost. Both
  details matter: `BaseHTTPMiddleware` runs the downstream app in a separate
  anyio task, which makes `ContextVar` propagation subtle. Being a bare ASGI
  middleware closest to the router means the value is set in the same task the
  endpoint runs in.
- Only two endpoints in the app are `async def` (`upload_document`,
  `restore_database`); every other route is `def` and runs in Starlette's
  threadpool, which receives a *copy* of the context. **Both paths are
  covered by tests**, because they propagate differently.
- `log_activity()` distinguishes "caller said nothing" from "caller said there
  is no IP" with a sentinel default, so an explicit `ip_address=None` still
  means NULL.
- The `ContextVar` is reset in a `finally`, so a pooled worker can never leak
  one request's address into the next — verified.

**System / background actions stay NULL.** Anything running outside a request —
a management script, a future scheduled job — reads the `ContextVar` default of
`None` and stores NULL. That is the honest answer: there was no client. **The
server's own address is never substituted for a missing client address**, since
that would be indistinguishable from a real visitor and worse than a blank.
There are no non-request audit writers in the codebase today; the property is
structural rather than something each caller has to remember.

**One limitation, stated plainly: deployment dependency.** The resolution is
correct *for this topology*. If the site is ever published without the
Cloudflare tunnel — a direct public binding, a different reverse proxy, IIS ARR
— the loopback test stops identifying "arrived via Cloudflare" and the column
falls back to whatever the new front-most hop exposes. It will not start
recording wrong addresses, but the trust rule in `client_ip.py` must be re-read
against the new chain.

**The audited actions** (21 `log_activity()` call sites, 23 distinct action
names, all inside HTTP handlers and therefore all client-initiated):

| Router | Actions |
|---|---|
| `auth.py` | `login_success`, `login_failed`, `logout` |
| `cases.py` | `case_create`, `case_note_add`, `case_stage_update` |
| `documents.py` | `document_upload`, `document_download`, `document_approve`, `document_reject`, `document_delete`, `document_grant_access` |
| `search.py` | `status_update_requested`, `case_track`, `case_untrack` |
| `users.py` | `user_create`, `user_update`, `user_delete`, `password_reset`, `user_bulk_activate`, `user_bulk_deactivate`, `user_bulk_reset_password` |
| `admin.py` | `database_backup_download`, `database_reset`, `database_restore` |
| `reminders.py` | `reminder_create`, `reminder_resolve` |
| `cases.py` (watch) | `case_watch`, `case_unwatch` |

**Still not audited, by design:** `PUT /api/notifications/{id}/read` and
`PUT /api/notifications/read-all`. Those are a person reading their own inbox
rather than acting on a business record, and auditing them would add a row per
glance without answering a question anyone asks of this log. Left deliberately,
not overlooked — and neither document claims otherwise. Implementing them is a
product decision, not a gap to be quietly closed.

#### The six actions added in this round

| Action | Endpoint | `entity_type` / `entity_id` | Meta |
|---|---|---|---|
| `reminder_create` | `POST /api/reminders` | `reminder` / new id | case label + id, type, requested_stage, assigned_to, due_at |
| `reminder_resolve` | `PUT /api/reminders/{id}/resolve` | `reminder` / id | case label + id, type, `from`/`to` status, `case_stage_advanced_to` |
| `case_track` | `POST /api/search/import` | `case` / case id | case label, source_type, source_ref_id, `already_tracked` |
| `case_untrack` | `DELETE /api/search/track/{case_id}` | `case` / case id | case label, `was_added_by` |
| `case_watch` | `POST /api/cases/{id}/watch` | `case` / case id | case label, `source` |
| `case_unwatch` | `DELETE /api/cases/{id}/watch` | `case` / case id | case label, `was_added_by` |

`case_track`/`case_untrack` and `case_watch`/`case_unwatch` both manage
`case_watchers` rows; they are separate actions because they are separate
controls (the Official Search Engine's **Track** button vs. **Watch Case** in
the case-detail modal), and knowing which one a person used is exactly the kind
of thing an audit log exists to answer.

**How they render.** Each has an `al_action_<name>` label in both dictionaries
and a colour in `ACTION_BADGE` (`js/pages/activity-log.js`); the `reminder`
entity type has a label in `ENTITY_LABEL`. Without a label the Activity Log
falls back to the raw action name, which is what five older actions were doing
until this round — `case_create`, `status_update_requested`,
`database_backup_download`, `database_restore` and `database_reset` were
emitted by routers but never translated, and were given labels and colours here
so the documentation above is true of every row.

| Action | English label | Arabic label | Badge |
|---|---|---|---|
| `reminder_create` | Reminder created | إنشاء تذكير | `badge-info` |
| `reminder_resolve` | Reminder resolved | إغلاق تذكير | `badge-success` |
| `case_track` | Case tracked | تتبّع قضية | `badge-info` |
| `case_untrack` | Case untracked | إيقاف تتبّع قضية | `badge-muted` |
| `case_watch` | Case watch added | متابعة قضية | `badge-info` |
| `case_unwatch` | Case watch removed | إلغاء متابعة قضية | `badge-muted` |

**Placement rules followed at every new call site:**

- **Logged after the commit, never before.** Every validation and authorization
  failure in these handlers raises before anything is written, so a rejected
  request cannot leave a record claiming the action succeeded. Verified live:
  four `403`s and one `401` produced zero audit rows.
- **Only real state changes are logged.** `case_watch`, `case_unwatch` and
  `case_untrack` log *inside* the endpoints' existing idempotency guards;
  `reminder_resolve` compares the previous status and stays silent if nothing
  changed. Repeating any of them writes nothing — the endpoints' behaviour is
  unchanged, only the log stops implying work that did not happen.
- **`case_track` is the deliberate exception.** Every successful call really
  does write an `imported_records` row, so every call is logged; the
  `already_tracked` flag in the meta makes a repeat press self-evident rather
  than hiding it.
- **No router asks for the IP.** All six inherit it from the request context
  (§3.6e). No `Request` parameter, no `request.client.host`, no second
  resolution path — `grep` confirms `request.client` appears nowhere outside
  `client_ip.py`.

**Historical rows are left untouched.** Pre-fix sign-ins keep their
`[::1]:<port>` value and pre-fix non-login actions keep their `NULL`; audit
records are never rewritten to make old data look better than it was.

### 3.6f The notification bell is a single action

The bell in the title bar used to toggle a `.notif-dropdown` preview panel
listing the latest eight notifications. That gave the application two places to
read the same list, and the smaller one was strictly worse: it truncated at
eight rows, had no "Mark all as read", no Smart Follow-up filtering, no print,
and no presence at all in the mobile layout.

The bell now sets `location.hash = "#/notifications"` and nothing else. The
dropdown's markup, its click and outside-click handlers, the
`renderNotifDropdown()` function and the `.notif-dropdown` / `.notif-item` CSS
were all removed; `js/app.js` no longer imports `markNotificationRead`,
`formatDate`, `escapeHtml` or `isSmartNudge`, which existed only for it. The
unread badge (`#notif-badge`, and `#bn-notif-badge` when Notifications is a
primary mobile tab) is unchanged.

`.notif-smart` and `.smart-tag` are **not** part of the dropdown and were kept —
the Notifications page uses them for the Smart Follow-up tag.

### 3.7 Mobile Experience

Open the portal on a phone (or narrow a desktop browser window below about 768px) and the layout changes to feel like a native app:

- The sidebar disappears completely.
- A **bottom tab bar** appears instead, showing the four sections most relevant to your role.
- A fifth tab, **"More,"** opens a sheet that slides up from the bottom with everything else — any remaining sections, the language switch, and Logout.
- Everything still mirrors correctly in Arabic — the tab bar and sheet flip right-to-left along with the rest of the app.

---

### 3.8 Procedural Intelligence

**Status: implemented in code, not yet applied to the production database.** Everything below describes what the code does; `db/migration_procedural_intelligence.sql` and `db/seed_procedure_rules.sql` must be applied by a privileged database account before any of it is live (see [§10](#10-database)). Until then the running app behaves exactly as before — every change in this feature is additive, and no existing table, column, or `stage` value is touched.

**What it answers, for any case:** Current Status → Latest Event → Required Next Procedure → Responsible User → Deadline → Reminder/Notification → Completion. The Cases module already tracked a coarse `stage`; this feature adds a real append-only event log (`case_procedures`), a rule-driven deadline engine (`procedures.py`), and a catalogue of the rules themselves (`procedure_rules`) — so the app can say not just "this case is at judgment" but "the last thing that happened was the judgment, issued on this date, and the appeal window closes on this date, because of this statute."

**The one rule that governs everything else: never present a guess as fact.**
- Every legal rule (`procedure_rules`) ships **disabled**, carrying its legal citation and a `source_tier` (`official_verified` / `official_inferred` / `firm_entered` / `ai_suggested` / `unverified`). A rule computes nothing until a named lawyer explicitly enables it — a deliberate, audit-logged, two-gate action (Admin, or an owner-Lawyer; see `backend/app/routers/rules.py`).
- Research done for this feature (Sept 2026) found the Cassation appeal deadline cited as **both 30 and 60 days** by two different professional guides. Rather than picking one, both candidate rules are seeded, both disabled, both flagged as conflicting — a lawyer must check the primary statute text before either is ever used.
- A deadline computed from a rule that isn't `official_verified` + lawyer-verified is `confidence = 'provisional'`: visibly badged "Suggested — needs lawyer confirmation" everywhere it appears, excluded from hard escalation, and cannot close a procedural step on its own.
- If no enabled rule matches a case's latest event, the UI says so plainly and offers manual entry — it never invents a date.

**No automated government sync exists, on purpose.** Every official Kuwait channel checked (MOJ e-Services, Sahel, Sahel Business, the MOJ site) is either login+CAPTCHA gated or requires the caller's own personal sign-in, and none publish an API. This app never stores a government credential and never solves a CAPTCHA. Instead, **Assisted Manual Sync** (the "Check official portal" panel on the Official Search Engine page): the app shows the exact lookup details and a deep link to the real portal; a human opens it, signs in as themselves, looks, and comes back to record what they saw (`POST /api/official-sync/case/{id}/check`). That observation can optionally become a real, `official_verified` procedural event in one step.

**Where it shows up:**
- **Case Details modal → "Procedural Intelligence"** section: the latest recorded event, any next-action candidates (with their due date, confidence badge, and legal citation), a "Record Procedure" button, and the full event history.
- **Official Search Engine** tab (on the Cases page): a disclaimer that the five search tabs show the firm's own records, not live government data (unchanged behaviour — just now stated explicitly), plus the "Check official portal" panel described above.
- **Deadlines** (new sidebar entry): a firm-wide, permission-scoped list of every deadline, filterable by status, with Confirm/Waive actions.
- **Dashboard**, third stats row: deadlines due this week, overdue deadlines, deadlines awaiting a lawyer's confirmation, and cases not checked against an official source recently.
- **Procedure Rules** (new sidebar entry, Admin/Lawyer only): the rule catalogue itself, where a rule is enabled or disabled.

**Permissions** (four new modules, same `none/view/own/limited/edit/full` matrix every other module uses):

| Module | Admin | Lawyer | consultant | delegate | User (Client) |
|---|---|---|---|---|---|
| `procedures` | full | full | edit | view | own (read-only) |
| `deadlines` | full | full | edit | view | own (read-only) |
| `official_sync` | full | full | edit | edit | none |
| `rules_admin` | full | view | none | none | none |

A Client (`own`) only ever sees `confidence = 'confirmed'` deadlines and events on their own cases — never a provisional/suggested item, and never the rule catalogue or sync internals. Enabling a rule additionally requires the caller to be Admin, or a Lawyer who is a firm owner (`is_owner`), on top of holding `rules_admin: full` — a non-owner Lawyer is refused even if granted `full`.

**Scheduling.** This feature adds `POST /api/internal/run-escalations`, protected by a shared-secret header (`ASLG_INTERNAL_TASK_TOKEN`, see [§9](#9-configuration-reference-env)) rather than a login, since nothing calls it from a browser session. It runs the existing notification engine plus the deadline sync/staleness sweep, firm-wide. Everything it does is idempotent, so it is safe to call on a schedule — see [§12](#12-production-deployment-iis) for wiring it to a Windows Scheduled Task, which finally gives this app a real periodic tick (previously every proactive check only ran opportunistically, when someone happened to load a page).

**Files, for developers:** `backend/app/procedures.py` (the engine), `backend/app/routers/{procedures,deadlines,official_sync,rules,internal}.py`, `backend/backfill_procedures.py` (one-time projection of existing `case_timeline`/`court_sessions`/`experts`/`execution_files` rows into the new event log — dry-run by default, `--apply` to write, generates **no** deadlines retroactively), `db/migration_procedural_intelligence.sql` + `db/rollback_procedural_intelligence.sql`, `db/seed_procedure_rules.sql`, `backend/tests/` (the project's first test suite — `pytest`, run from `backend/` with `backend/requirements-dev.txt` installed).

---

## 4. Step-by-Step Testing Guide

This section is a hands-on checklist. Follow it top to bottom and you'll have exercised every major feature.

> ⚠ **This section describes a local development copy, not the running system.**
> The authoritative deployment is **https://app.alsaiflegalgroup.com/**, hosted by **Windows IIS** via `httpPlatformHandler` (see [§12](#12-production-deployment-iis)). The `uvicorn` command in Step 1 is a developer convenience for a separate local checkout — it is **not** the production runtime, and starting it is never a substitute for, or a way to "restart", the live site. To restart the live site, recycle the IIS application pool ([§12.8](#128-restart--recycle)).

### Step 0 — What you need before starting

- The MySQL service must be running (it's installed as a Windows service named `MySQL` — check with `services.msc` if unsure, or ask whoever set it up).
- Python 3.11+ with the packages listed in `backend/requirements.txt` installed machine-wide, one time only: `python -m pip install --no-user -r backend/requirements.txt` (the `--no-user` matters — see [§12.3](#123-install-dependencies)). No virtual environment, no activation step.

### Step 1 — Start the backend server

Open a terminal, go into the `backend` folder, and run:

```
cd backend
python -m uvicorn app.main:app --reload
```

Leave this window open — it's now serving both the API *and* the website itself. You should see a line saying it's running on `http://127.0.0.1:8000`.

> If this is a brand-new database with no data yet, run `python seed.py` once first (still inside the `backend` folder) — it fills the database with the starting set of users, cases, and sample documents.

### Step 2 — Open the app

In a web browser, go to:

```
http://127.0.0.1:8000/index.html
```

You should land on the **login page** — Arabic, right-to-left, with an animated background, a username field, and a password field.

### Step 3 — Log in and explore as different roles

Every account uses the same starting password, which is defined in `backend/seed.py` and deliberately not reproduced in this document (see [§5](#5-quick-reference-default-test-accounts) for the full list of usernames). Type a username and that password into the login form to try each role:

| Log in as | You become | Try this |
|---|---|---|
| `tamer.salem` | Admin | Go to "Users & Permissions" — you should see all 9 accounts and full admin tools |
| `hassan.falah` | Lawyer | Notice "Users & Permissions" is now gone from the sidebar |
| `mohammad.ahmad` | Consultant | Open a case — you can add a note and change its stage |
| `ahmad.sayed` | Delegate | Open a case — notice there's *no* stage dropdown or note box (view-only). "Reminders & Follow-ups" is visible, but only shows tasks assigned to them — there's no way to create a new one |
| `jarrah.saad` | Client | Notice "Reminders" is completely gone, and "Cases" has no tab bar (no Official Search Engine tab) and shows only *one* case — theirs |

To log out of one role and try another, click **"Logout"** at the bottom of the sidebar, then log in again with a different account.

### Step 4 — Test the Search Engine

1. Log in as **Tamer Salem** (Admin) or **Hassan Falah** (Lawyer).
2. Click **"Cases"**, then the **"Official Search Engine"** tab.
3. On the first search tab, type `1123` into the Case Number box and click **Search** — you should see one matching case.
4. Click **"Import to Tracking List"** on that result — a green success message should pop up.
5. Click through the other four tabs (Sessions, Experts, Execution, Internal) and try a search on each — every tab should return real results from the database, not placeholders.

### Step 5 — Test Case Management

1. Still logged in as a Lawyer or Admin, click **"Cases."**
2. You'll see the case **table** with **Status** and **Assigned Lawyer** filter dropdowns above it (there is no Kanban/board view). Click any row to open its details.
3. Try the **"Watch Case"** toggle — it should switch to a highlighted "Watching" state. This is the same relationship as **Track** in the search engine, and it is what puts you on the pre-hearing alert list for that case.
4. Type something into the note box and click **Add Note** — it should appear immediately above, with your name and today's date.
5. Change the **status dropdown** to a different stage — a success toast should appear, the badge in the table should update, and an entry should appear in the **Activity Log**. Note that the **Case Timeline does not gain a step** from this: see [3.2](#32-case-management-filterable-list--detailed-view).
6. Set the **Status** filter to *Closed*, then clear it — the table should filter and restore. Then open the Dashboard and click the **Active Cases** card: it should land back here with the filter already applied and a dismissible filter chip shown.

### Step 6 — Test Document Upload & Preview

1. From the case detail view (or the "Document Center" page), pick a case from the dropdown.
2. Drag any PDF, DOCX, JPG, or PNG file onto the upload box (or click it to choose a file).
3. Watch the progress bar fill up — when it finishes, a "File uploaded successfully" message appears and the file shows up in the table below, tagged "Pending."
4. Click **"Preview"** next to it — the file should open in a popup, with a working **Download** button.
5. Click **"Delete"** to remove it, and confirm it disappears from the list.

### Step 7 — Test the Client Upload-Access Grant

This proves a client genuinely cannot upload anything until staff opens the door for them, and that the door shuts itself afterward.

1. Log in as **Jarrah Saad** (Client) and open **"Document Center."** You should see a gray, dashed banner saying you can't upload right now — and no upload box at all.
2. Log out, log back in as **Tamer Salem** (Admin) or **Hassan Falah** (Lawyer), and open Document Center.
3. Click **"Grant Temporary Upload Access,"** pick case **1123/2024** (Jarrah Saad's case) and a short duration like 15 minutes, then confirm.
4. Log out and back in as **Jarrah Saad** again. The banner should now be green — *"You have upload access — 1123/2024"* — with a working upload box beneath it.
5. Upload any file. As soon as it finishes, refresh the page (or just look again) — the banner should have flipped straight back to blocked, even though the 15 minutes hadn't run out. That one upload used up the access.

### Step 8 — Test Reminders & Owner Task Assignment

1. Log in as **Mohammad Ahmad** (Consultant) and open any case that has an assigned lawyer.
2. Scroll to **"Schedule Reminder"** inside the case detail view. Notice the "Assign To" field is a plain, disabled box already filled in with the case's own lawyer — a Consultant can't change it.
3. Pick "Status Update Request," choose a due date and a new requested stage, write a short note, and click **Create**.
4. Go to **"Reminders & Follow-ups"** in the sidebar — your new reminder should be listed as "Open."
5. Log out and log back in as the lawyer it was assigned to, go to Reminders, and click **"Mark Done"** — the case's stage should update automatically to match what you requested.
6. Now test the Owner ability: log in as **Hassan Falah** or **Jaber Barrak** (both are Owners) and open a case's **"Schedule Reminder"** form. This time "Assign To" is a full dropdown — pick **Ahmad Sayed** (a Delegate) instead of the case's own lawyer, and click **Create**.
7. Log in as **Ahmad Sayed** and check **"Reminders & Follow-ups"** — the task should be sitting there waiting for them, with **Mark Done** / **Dismiss** buttons, proving a task can reach a Delegate directly without ever passing through the case's lawyer.

### Step 9 — Test User Management (Admin only)

1. Log in as **Tamer Salem**.
2. Go to **"Users & Permissions"** and click **"New User."** Fill in a name, username, role, and password, then **Save** — the new person should appear in the list immediately.
3. Tick the checkbox next to two or three users — a blue toolbar should appear at the top with **Activate / Deactivate / Reset Password** buttons. Try "Deactivate selected" — their status badges should turn gray.
4. Reactivate them the same way (select + "Activate selected"), or open one user's **Edit** form and tick "Account active" directly.
5. Open **Mohammad Ahmad**'s (a Consultant) edit form and tick **"Firm owner."** Save, then log in as Mohammad Ahmad and open a case's reminder form — the "Assign To" field should now be a full staff dropdown, just like it is for Hassan Falah and Jaber Barrak. Untick it afterward to put things back.
6. Delete the test user you created in step 2, to keep the account list clean.

### Step 10 — Test Role Restrictions Are *Really* Enforced

This step proves the security isn't just "hiding buttons" — the server itself refuses unauthorized requests.

1. Log in as **Jarrah Saad** (Client).
2. Notice the Cases page has no "Official Search Engine" tab — try typing `#/cases/search` (or the old `#/search`) directly at the end of the page's address bar and pressing Enter anyway.
3. You land on the plain case list with no search tab, and the address drops back to `#/cases` — not the search screen. The restriction is also enforced by the server: every `/api/search/*` request from a Client account is refused, so even a hand-made request gets nothing.

### Step 11 — Test the Language Toggle

1. On any page, click the small globe icon in the top-right corner.
2. The entire interface should flip: Arabic → English text, right-to-left → left-to-right layout, sidebar moves from right to left, everything mirrors correctly (dates, numbers, icons).
3. Click it again to switch back to Arabic.

### Step 12 — Test the Dashboard Task Stats Row

1. Log in as **Tamer Salem**, **Hassan Falah**, or **Mohammad Ahmad** (Admin, Lawyer, or Consultant) and open the **Dashboard**.
2. Below the usual four stat cards, you should see a second row labeled **"Tasks & Assignments"** with four more cards: My Open Tasks, Overdue Tasks, Pending Status Requests, Tasks I Assigned.
3. Log in as **Ahmad Sayed** (Delegate) or **Jarrah Saad** (Client) and open the Dashboard again — that second row should be completely absent for both.

### Step 13 — Test the Mobile Bottom Navigation

1. Make your browser window narrow — under about 768px wide. (On a desktop browser, you can usually do this with the responsive/device-toolbar view in your browser's developer tools, typically opened with F12 then a phone-icon button, or just shrink the window if your OS allows it.)
2. The sidebar should vanish, replaced by a row of icons fixed to the bottom of the screen.
3. Tap **"More"** — a panel should slide up from the bottom listing whatever didn't fit in the bottom row, plus the language switch and Logout.
4. Tap outside the panel (on the dimmed background) to close it, or tap one of its items to navigate straight there.
5. While still narrow, toggle the language — the bottom bar and the "More" panel should both flip to right-to-left, same as the rest of the app.

---

## 5. Quick-Reference: Default Test Accounts

> **Credentials are deliberately not printed here.** All seeded accounts share one starting password, defined in `backend/seed.py`. Read it from there if you need it — it is not repeated in documentation, and it must be changed for every account before the portal is treated as production. Rotate passwords through **Users & Permissions → Reset Password**, not by editing the database.

| Username | Name | Role |
|---|---|---|
| `tamer.salem` | Tamer Salem | Admin |
| `hassan.falah` | Hassan Falah | Lawyer (Owner) |
| `jaber.barrak` | Jaber Barrak | Lawyer (Owner) |
| `mohammad.ahmad` | Mohammad Ahmad | Consultant |
| `mohammad.mahmoud` | Mohammad Mahmoud | Consultant |
| `ahmad.sayed` | Ahmad Sayed | Delegate |
| `ahmad.saber` | Ahmad Saber | Delegate |
| `jarrah.saad` | Jarrah Saad | Client |
| `fahad.fazzaa` | Fahad Fazzaa | Client |

---

## 6. Where Things Live (for developers)

| What | Where |
|---|---|
| Website pages (HTML/CSS/JS) | `index.html`, `css/styles.css`, `js/` |
| Backend API (Python/FastAPI) | `backend/app/` |
| The 3-layer pre-date notification engine + Smart Follow-up | `backend/app/escalation.py` |
| Kuwait business-calendar helpers (the single source of truth for "what day is it") | `backend/app/kuwait_time.py` |
| Backup / Import-Restore / Factory Reset endpoints | `backend/app/routers/admin.py` |
| Shared "Request Update" dialog (dashboard, search results, case timeline) | `js/request-update.js` |
| Print composer — builds the printable sheet for every Print button | `js/print.js` |
| Trusted-proxy client IP resolution + the per-request ContextVar every audit row reads | `backend/app/client_ip.py` |
| Database structure (tables only, no data) | `db/schema.sql` |
| Starting data loader | `backend/seed.py` |
| Backend settings (database password, etc.) | `backend/.env` — never share this file, never commit it |
| Uploaded documents (real files) | `backend/uploads/` |
| Backend runtime logs (production only) | `backend/logs/` |
| IIS site configuration | `web.config` (project root) |
| Procedural Intelligence engine (deadline/next-action computation) | `backend/app/procedures.py` |
| Procedural Intelligence API routers | `backend/app/routers/{procedures,deadlines,official_sync,rules,internal}.py` |
| Procedural Intelligence DB migration (drafted, not yet applied) + rollback + rule-catalogue seed | `db/migration_procedural_intelligence.sql`, `db/rollback_procedural_intelligence.sql`, `db/seed_procedure_rules.sql` |
| One-time backfill of pre-existing case history into the new event log | `backend/backfill_procedures.py` |
| Backend test suite (`pytest`) | `backend/tests/` |

Fonts and icons are loaded from a shared folder used by every site on this server (`C:\inetpub\sites\_shared`) rather than the internet, so the portal works even without an internet connection.

**Database additions for this round of features:** a `users.is_owner` column (the Owner flag), a `case_reminders.escalation_level` column (tracks which of the 3 nudge layers a reminder has already reached, so nobody gets the same notification twice), and a new `document_upload_grants` table (one row per temporary upload window opened for a client — who granted it, which case, when it expires, and whether it's still active, used, or expired).

The remaining sections ([§7](#7-architecture--requirements) onward) cover how to actually run, configure, deploy, and maintain the system — written for whoever is operating the server, not just using the app.

---

## 7. Architecture & Requirements

| Layer | Technology | Notes |
|---|---|---|
| Frontend | Vanilla HTML/CSS/JavaScript (ES modules), no build step | Hash-based routing (`#/dashboard`, `#/cases`, …) — the browser never sends the `#...` part to the server, so there is nothing to configure server-side for client-side routes |
| Backend | Python 3.11, FastAPI, served by Uvicorn (ASGI) | One process serves both the JSON API (`/api/*`) and the frontend's static files |
| Database | MySQL 8.4, accessed via SQLAlchemy + PyMySQL | Runs as a local Windows service; same server as the app in this deployment |
| Auth | JWT (HS256, `python-jose`) + bcrypt password hashing | Stateless bearer tokens, `Authorization: Bearer <token>`, no server-side session store |
| Production web server | IIS 10, via the `httpPlatformHandler` module | IIS starts, monitors, and restarts the Uvicorn process itself — see [§12](#12-production-deployment-iis) |

**Requirements to run this project:**
- Windows Server with IIS (production) — the following IIS modules must be installed: **URL Rewrite**, **Application Request Routing**, **httpPlatformHandler**. All three are already installed on this server.
- Python 3.11+, installed **machine-wide**. See [§12.3](#123-install-dependencies).
- MySQL 8.4 (or compatible 8.x), running as a local service, reachable at `127.0.0.1:3306` by default.
- The estate-wide shared assets folder `C:\inetpub\sites\_shared` (fonts, icons) — already present on this server.

There is no separate frontend build step (no npm/webpack/bundler) — "build" for the frontend still means nothing beyond "the files are static." The backend has an automated test suite (`backend/tests/`, `pytest`, introduced alongside Procedural Intelligence — see [§3.8](#38-procedural-intelligence) and [§10](#10-database)) covering the notification engine, permission scoping, and the deadline-computation engine, run entirely against a throwaway in-memory database. "Test" for the rest of the app still means the manual walkthrough in [§4](#4-step-by-step-testing-guide) plus the automated checks described in [§14](#14-verification-checklist).

**No virtual environment.** This project deliberately runs directly against the machine's own Python install rather than a project-local venv — one less thing to create, activate, or keep in sync between local dev and IIS. The trade-off, stated plainly: any other Python project on this same machine shares the same package versions as this one, so a future `pip install --upgrade` for a different project could change what this app sees too. On this server that risk is accepted deliberately; on a machine running several unrelated Python services, a dedicated environment (venv or otherwise) would be the safer default. See [§12.3](#123-install-dependencies) for the one thing this requires getting right (installing without `--user`).

---

## 8. Local Development Setup

This expands on [§4, Step 0–2](#4-step-by-step-testing-guide) with the exact commands, for a developer setting up the project on a new machine.

**No virtual environment, no activation step.** This project intentionally runs directly against the machine's normal Python install — see [§7](#7-architecture--requirements) and the note in [§12.3](#123-install-dependencies) for why, and the one thing to get right when installing dependencies (they must land in Python's *global* site-packages, not a per-user one).

1. **Confirm MySQL is running** (Windows service named `MySQL`, or whatever it was installed as — check `services.msc`) and that a database and app user exist (see [§10](#10-database)).
2. **Install dependencies** (one-time per machine):
   ```
   python -m pip install --no-user -r backend\requirements.txt
   ```
   `--no-user` is required, not optional — see [§12.3](#123-install-dependencies).
3. **Create `backend\.env`** by copying `backend\.env.example` and filling in real values (see [§9](#9-configuration-reference-env)). For local dev, the relative defaults (`UPLOAD_DIR=./uploads`, `FRONTEND_DIR=../`) are correct as long as you launch Uvicorn from inside `backend\` — the command below does exactly that.
4. **Seed the database** (first time only, or after a schema reset):
   ```
   cd backend
   python seed.py
   ```
5. **Run the dev server** (from inside `backend\`):
   ```
   cd backend
   python -m uvicorn app.main:app --reload
   ```
   `--reload` is safe and expected here — it's the opposite of production, where a persistent auto-reloading process is undesirable. Leave this terminal open; it serves both the API and the website at `http://127.0.0.1:8000`.
6. **Open the app**: `http://127.0.0.1:8000/` in a browser.

---

## 9. Configuration Reference (`.env`)

All backend configuration lives in `backend\.env` (never committed — see `.gitignore`), read by `backend/app/config.py`. `backend\.env.example` is the committed template; copy it to `.env` and fill in real values.

| Variable | Meaning | Local dev value | Production value (this server) |
|---|---|---|---|
| `DB_HOST` | MySQL host | `127.0.0.1` | `127.0.0.1` (same box) |
| `DB_PORT` | MySQL port | `3306` | `3306` |
| `DB_NAME` | Database name | `aslg_legal` | `aslg_legal` |
| `DB_USER` | MySQL app user | `aslg_app` | `aslg_app` |
| `DB_PASSWORD` | MySQL app user's password | — | — (never write this in any document; see [§10](#10-database)) |
| `JWT_SECRET` | Signs/verifies login tokens | any long random string | a long random string, generated once, never reused across environments |
| `JWT_ALGORITHM` | JWT signing algorithm | `HS256` | `HS256` |
| `JWT_EXPIRE_MINUTES` | How long a login session lasts | `720` (12h) | `720` |
| `UPLOAD_DIR` | Where uploaded documents are stored on disk | `./uploads` (relative to `backend/`, since dev launches Uvicorn from there) | **absolute path**: `C:\inetpub\sites\Platforms\ASLG\backend\uploads` |
| `MAX_UPLOAD_MB` | Upload size limit | `25` | `25` |
| `SHARED_ASSETS_DIR` | Estate-wide fonts/icons folder | `C:\inetpub\sites\_shared` | `C:\inetpub\sites\_shared` |
| `FRONTEND_DIR` | Project root, for serving `index.html`/`css/`/`js/` | `../` (relative, since dev launches Uvicorn from `backend/`) | **absolute path**: `C:\inetpub\sites\Platforms\ASLG` |
| `CORS_ALLOWED_ORIGINS` | Comma-separated list of origins allowed to call the API from browser JS | default already covers both dev and prod | default already covers both dev and prod |
| `ASLG_INTERNAL_TASK_TOKEN` | Shared secret for `POST /api/internal/run-escalations` (Procedural Intelligence's scheduler hook — see [§3.8](#38-procedural-intelligence) and [§12.10](#1210-procedural-intelligence-scheduled-task)). Generate with `python -c "import secrets; print(secrets.token_urlsafe(48))"` | any long random string, or leave unset to disable the endpoint | **set** on this server as of 16 Sep 2026 — a 64-character `token_urlsafe(48)` value, known only to the Scheduled Task that calls it |

**Why production needs absolute paths and dev doesn't:** `UPLOAD_DIR` and `FRONTEND_DIR` are resolved against the process's *current working directory* at startup. The documented dev workflow (`cd backend && uvicorn ...`) makes that `backend\`, so the relative defaults resolve correctly. IIS's `httpPlatformHandler`, however, starts the process with its working directory set to the folder containing `web.config` — the project root, one level up — so a relative `./uploads` or `../` would resolve to the wrong place in production. This isn't hypothetical: it was found and fixed during the September 2026 production-readiness pass (see [§17](#17-security-notes)). The production `backend\.env` on this server already uses the correct absolute paths.

---

## 10. Database

- **Engine:** MySQL 8.4, running as a local Windows service.
- **Database name:** `aslg_legal`. **App user:** `aslg_app` (least-privilege — only needs access to this one database, not full MySQL admin).
- **Schema:** `db/schema.sql` — table structure only, no data. This is the source of truth for the table layout; there is no separate migration tool in this project, so schema changes are applied by hand (or by re-running the relevant `CREATE`/`ALTER` statements) and then mirrored into `db/schema.sql`.
- **Starting data:** `backend/seed.py` — creates the roles, permission matrix, the 9 demo staff/client accounts (see [§5](#5-quick-reference-default-test-accounts)), and sample cases/documents. Intended to run once against an empty database; it exits immediately (no-op) if the `users` table already has any rows, so it is safe to invoke against an already-seeded database — it just won't do anything.
- **Procedural Intelligence migration (drafted, not yet applied):** `db/migration_procedural_intelligence.sql` adds the tables/columns described in [§3.8](#38-procedural-intelligence), entirely additively — no existing column is dropped or renamed, and `cases.stage` keeps its exact current meaning. Like `db/migration_user_case_links.sql` before it, this file is **never executed by the application or by an AI assistant** — it is a draft for a human with a privileged MySQL account to review and apply by hand, e.g.:
  ```
  mysql -h 127.0.0.1 -P 3306 -u root -p aslg_legal < db\migration_procedural_intelligence.sql
  mysql -h 127.0.0.1 -P 3306 -u root -p aslg_legal < db\seed_procedure_rules.sql
  ```
  `db/rollback_procedural_intelligence.sql` reverses it, dropping only what the migration added. After applying, mirror the new `CREATE TABLE`/`ALTER TABLE` statements into `db/schema.sql` (per this project's usual convention) and recycle the app pool. Then, optionally, backfill history for cases that predate the feature: `cd backend && python backfill_procedures.py` (dry run; add `--apply` to actually write). None of this is required for the app to keep working exactly as it does today — every new route 404s harmlessly until the migration is applied, and the app never attempts to write to a table that doesn't exist yet.
- **Backend test suite:** `backend/tests/` (`pytest`, first introduced alongside Procedural Intelligence). Runs entirely against a throwaway in-memory SQLite database — never against `aslg_legal` — via `backend/tests/conftest.py`'s fixtures. To run: `cd backend && pip install -r requirements-dev.txt && pytest -q`.
- **Connecting directly** (for inspection/admin — requires the MySQL client tools, e.g. `C:\Program Files\MySQL\MySQL Server 8.4\bin\mysql.exe`):
  ```
  mysql -h 127.0.0.1 -P 3306 -u aslg_app -p aslg_legal
  ```
  It will prompt for the password interactively rather than taking it on the command line, so it never ends up in shell history.
- **Backups:** there is no automated backup job configured as part of this project. Back up the `aslg_legal` database using your normal MySQL backup procedure (e.g. `mysqldump`) before any schema change or major deployment.

---

## 11. Authentication & Login Credential Management

The application has **no plaintext passwords anywhere** — not in the database, not in config files, not in source code. Every stored password is a **bcrypt hash** (`backend/app/security.py`, 12 rounds), and login is verified by hashing the submitted password and comparing hashes (`bcrypt.checkpw`), never by comparing plaintext. Sessions are stateless **JWT bearer tokens** signed with `JWT_SECRET`, valid for `JWT_EXPIRE_MINUTES` (12 hours by default) — logging out simply discards the token client-side; there's no server-side session table to invalidate.

There are two legitimate ways to manage user credentials. **Use the first one** unless it's genuinely unavailable (e.g. the only Admin account is locked out).

### 11.1 Application User CRUD (recommended)

Everything here is exposed through the **Users & Permissions** page (Admin role only) — see [§3.5](#35-it-admin--user--credential-management) for the walkthrough, and [§4, Step 9](#4-step-by-step-testing-guide) to test it. In API terms (all under `/api/users`, all requiring an Admin bearer token):

| Operation | How (UI) | Endpoint |
|---|---|---|
| **Create** a user | "New User" button, fill form, Save | `POST /api/users` |
| **Read** / list users | Users & Permissions page loads this automatically | `GET /api/users` |
| **Update** a user (name, email, role, active flag, owner flag) | Click a user's edit (pencil) icon | `PUT /api/users/{id}` |
| **Reset** a single password | Click a user's key icon, type new password | `POST /api/users/{id}/reset-password` |
| **Bulk activate/deactivate/reset-password** | Tick multiple rows, use the toolbar that appears | `POST /api/users/bulk` |
| **Delete** a user | Click a user's trash icon, confirm | `DELETE /api/users/{id}` |

A new password submitted through any of these never travels anywhere in plaintext except the one HTTPS/HTTP request from the admin's browser to the server; the server hashes it immediately (`hash_password()` in `security.py`) before it ever touches the database.

### 11.2 Database Administration (emergency use only)

Use this **only** when the application UI is genuinely unusable — for example, every Admin account is locked out or inactive. This requires direct MySQL access and is a database-administration action, not a normal application workflow.

**Never write a plaintext password into the `users` table.** The `password_hash` column must always contain a bcrypt hash. To produce one, use the application's own hashing function so the format matches exactly what the app expects:

```
cd C:\inetpub\sites\Platforms\ASLG\backend
python -c "from app.security import hash_password; print(hash_password('the-new-password'))"
```

That prints a string starting with `$2b$12$...` — copy it, then apply it with SQL:

```sql
-- Reset an existing user's password directly (emergency use):
UPDATE users SET password_hash = '$2b$12$...paste-the-generated-hash-here...' WHERE username = 'tamer.salem';

-- Reactivate a locked-out account:
UPDATE users SET is_active = 1 WHERE username = 'tamer.salem';
```

To create a brand-new user this way you would also need a valid `role_id` (see the `roles` table) — in practice, creating users is exactly what the Application User CRUD path in [§11.1](#111-application-user-crud-recommended) is for, so prefer that unless the reason you're in the database at all is that no Admin account can currently log in to use it.

**Deactivate/reactivate and delete** are also available at the database level (`UPDATE users SET is_active = 0/1 ...`, `DELETE FROM users WHERE ...`) but again should go through the application UI in the normal course of operations, since the UI enforces the same protections the API does (e.g. you can't delete your own account through the UI — that guard doesn't exist at the raw SQL level, so a direct `DELETE` is unprotected against mistakes).

**Inspecting current auth state:** `SELECT id, username, role_id, is_active, is_owner, last_login_at FROM users;` — read-only, safe to run any time.

---

## 12. Production Deployment (IIS)

This section documents the **actual, verified working configuration** for this deployment — `ASLG` on this server, physical path `C:\inetpub\sites\Platforms\ASLG`, bound to `app.alsaiflegalgroup.com` on port 80. Follow it step by step for a fresh deployment or a redeploy to a new machine.

### 12.1 Prerequisites
- IIS with the **URL Rewrite**, **Application Request Routing**, and **httpPlatformHandler** modules installed (already true on this server; see [§13](#13-iis-configuration-reference) for how to verify).
- Python 3.11+ installed **machine-wide** (not a per-user install) — this project runs directly against it, with no virtual environment and no activation step (see [§7](#7-architecture--requirements) for why).
- MySQL 8.4 running locally with the `aslg_legal` database and `aslg_app` user already created (see [§10](#10-database)).

### 12.2 Deploy the files
Copy the project to `C:\inetpub\sites\Platforms\ASLG` (or pull the git repository directly to that path). The physical path must contain, at minimum: `index.html`, `css/`, `js/`, `backend/`, `web.config`.

### 12.3 Install dependencies
```
python -m pip install --no-user -r backend\requirements.txt
```
**`--no-user` is not optional.** Without it, `pip` can silently install into the *current Windows user's* per-user site-packages folder (`%APPDATA%\Python\Python3xx\site-packages`) instead of the machine-wide one — which works fine when *you* run `python`, but IIS's `httpPlatformHandler` launches the process as the Application Pool identity (`IIS AppPool\ASLG`), a completely different Windows account with no access to your personal per-user folder. This is not a hypothetical: it happened during this exact deployment (`pip install fastapi uvicorn python-multipart` without `--no-user` landed in the developer's own per-user site-packages; production then failed at startup with `No module named uvicorn`, logged to `backend\logs\uvicorn-stdout.log_*`, until every affected package was reinstalled with `--force-reinstall --no-user`). If you ever hit `No module named <x>` in that log after a working deployment, this is almost certainly why — re-run the install command above, or force just the affected package: `python -m pip install --no-user --force-reinstall --no-deps <package>==<version>`.

The version pins in `backend\requirements.txt` matter for the same "works here, fails on a clean machine" reason — a stale/incorrect one was found and fixed during an earlier pass (`pymysql==2.2.8`, which never existed on PyPI).

### 12.4 Configure `backend\.env`
Copy `backend\.env.example` to `backend\.env` and fill in real values — **critically, `UPLOAD_DIR` and `FRONTEND_DIR` must be absolute paths in production** (see [§9](#9-configuration-reference-env) for why, and the exact values to use). Generate a fresh, long random `JWT_SECRET` per environment — never reuse a dev secret in production or vice versa.

### 12.5 Grant the App Pool identity write access
The IIS Application Pool identity (`IIS AppPool\<pool-name>` — `IIS AppPool\ASLG` on this server) needs:
- **Read & Execute** on the whole project folder (IIS grants this automatically when the site/app is created).
- **Modify** on `backend\uploads\` (the app writes uploaded documents there) and `backend\logs\` (Uvicorn's stdout log). These are **not** granted automatically for folders that already existed before the site was created, or that IIS didn't create itself — grant them explicitly:
  ```
  icacls "C:\inetpub\sites\Platforms\ASLG\backend\uploads" /grant "IIS AppPool\ASLG:(OI)(CI)M"
  icacls "C:\inetpub\sites\Platforms\ASLG\backend\logs" /grant "IIS AppPool\ASLG:(OI)(CI)M"
  ```
  (substitute the actual app pool name if different from `ASLG`.)

### 12.6 IIS site, application pool, and binding
On this server these already exist — see [§13](#13-iis-configuration-reference) for the exact settings to replicate on a new machine. In short: a site named `ASLG`, its own application pool also named `ASLG` (Integrated pipeline, "No Managed Code" isn't required — `v4.0`/Integrated works fine since httpPlatformHandler does the actual work, not the .NET runtime), physical path `C:\inetpub\sites\Platforms\ASLG`, one HTTP binding on port 80 for host name `app.alsaiflegalgroup.com`.

### 12.7 `web.config`
Already present at the project root (`web.config`) and configured for this exact deployment. It does three things:
1. **Request filtering** — blocks direct access to `.env`, `.sql`, `.bak`, `.log`, `.xlsx` files and to the `backend`, `db`, `__pycache__`, `.git` folders, as defense-in-depth (the FastAPI app itself no longer serves these either — see [§17](#17-security-notes)).
2. **`httpPlatformHandler`** — launches `python.exe -m uvicorn app.main:app --app-dir <path>\backend --host 127.0.0.1 --port %HTTP_PLATFORM_PORT%` (the machine's normal Python install, not a project-local copy) and proxies every request to it. IIS assigns the port dynamically and restarts the process if it crashes.

If you move this deployment to a different path or machine, edit the **three absolute paths** called out in `web.config`'s own comments (`processPath`, the app-dir value inside `arguments`, and `stdoutLogFile`) to match the new location — httpPlatformHandler requires an absolute `processPath`, so this can't be made relative.

### 12.8 Restart / recycle
After changing `web.config`, `.env`, or the installed packages, recycle the app pool so the running Uvicorn process picks up the change (editing `web.config` itself also triggers this automatically, since IIS watches it for changes):
```
%windir%\system32\inetsrv\appcmd.exe recycle apppool "ASLG"
```

### 12.9 Verify
See [§14](#14-verification-checklist) for the full checklist. At minimum: `http://app.alsaiflegalgroup.com/api/health` should return `{"status":"ok"}`, and `http://app.alsaiflegalgroup.com/` should show the login page.

### 12.10 Procedural Intelligence Scheduled Task

**Only relevant once `db/migration_procedural_intelligence.sql` has been applied (see [§10](#10-database)) — until then, skip this.** This app has no in-process scheduler (an APScheduler-style in-memory job would silently vanish every time IIS's `httpPlatformHandler` recycles the worker process), so periodic work — the notification engine's 7/3/1 pre-due alerts, and Procedural Intelligence's deadline sync/staleness sweep — has always run only opportunistically, whenever someone happened to load a page that triggers it. `POST /api/internal/run-escalations` (protected by the `ASLG_INTERNAL_TASK_TOKEN` header, see [§9](#9-configuration-reference-env)) exists so a real periodic tick can be added without an in-process scheduler:

1. Generate and set `ASLG_INTERNAL_TASK_TOKEN` in the production `backend\.env`, then recycle the app pool ([§12.8](#128-restart--recycle)).
2. Create a Windows Scheduled Task that runs every 15 minutes, calling:
   ```powershell
   Invoke-RestMethod -Method Post -Uri "http://127.0.0.1/api/internal/run-escalations" -Headers @{ "X-Internal-Task-Token" = "<the same value as ASLG_INTERNAL_TASK_TOKEN>" }
   ```
   (`schtasks /create /tn "ASLG Escalations" /tr "powershell -File C:\path\to\run-escalations.ps1" /sc minute /mo 15 /ru SYSTEM`, with the `Invoke-RestMethod` line above saved as that `.ps1` file.)
3. This is additive to, not a replacement for, the existing opportunistic calls from the dashboard/reminders/notifications pages — both paths call the same idempotent functions, so running both is redundant-safe, never double-fires a notification.

Leaving `ASLG_INTERNAL_TASK_TOKEN` unset (the default) simply leaves the endpoint refusing every request — the app behaves exactly as it did before this feature existed.

---

## 13. IIS Configuration Reference

The actual, live configuration on this server, as verified during the September 2026 production-readiness pass — use this as the reference to reproduce on another machine, and to sanity-check if something ever drifts.

| Setting | Value |
|---|---|
| Site name | `ASLG` |
| Physical path | `C:\inetpub\sites\Platforms\ASLG` |
| Application pool | `ASLG` — Integrated pipeline, `.NET CLR v4.0` (the .NET runtime version is irrelevant here; `httpPlatformHandler` does the real work, not managed code), Identity: `ApplicationPoolIdentity`, Start Mode: `OnDemand` |
| Binding | `http`, host name `app.alsaiflegalgroup.com`, port `80` |
| DNS | `app.alsaiflegalgroup.com` is proxied through Cloudflare — its public DNS records point to Cloudflare's edge IPs, not directly at this server. This is expected and doesn't affect anything documented here, but it does mean you can't verify this specific IIS binding by simply `curl`-ing the public hostname from this machine (that request goes to Cloudflare, not necessarily back to this box); use `curl --resolve app.alsaiflegalgroup.com:80:127.0.0.1 http://app.alsaiflegalgroup.com/...` to test the local IIS binding directly instead. |
| Required IIS modules | URL Rewrite, Application Request Routing, httpPlatformHandler — confirm with: `%windir%\system32\inetsrv\appcmd.exe list config -section:system.webServer/globalModules` |
| Handler | `web.config` wildcards `path="*"` to `httpPlatformHandler`, which launches Uvicorn (via the machine's normal Python install) and proxies everything to it (see [§12.7](#127-webconfig)) |
| Request filtering | Blocks `.env` / `.sql` / `.bak` / `.log` / `.xlsx` extensions and the `backend` / `db` / `__pycache__` / `.git` path segments, at the IIS level, independent of the Python app |

**Checking the site's current state** (from an elevated PowerShell or this project's shell):
```
%windir%\system32\inetsrv\appcmd.exe list site "ASLG" /text:*
%windir%\system32\inetsrv\appcmd.exe list apppool "ASLG" /text:*
%windir%\system32\inetsrv\appcmd.exe list wp
```
The last command lists running worker processes — `ASLG` should appear if the site has received at least one request recently (it uses `OnDemand` start mode, so the pool doesn't necessarily have a worker process running at all times).

---

## 14. Verification Checklist

Run through this after any deployment or configuration change.

**Static & API layer:**
- [ ] `http://app.alsaiflegalgroup.com/` (or `--resolve`-tested locally) returns the login page, HTTP 200
- [ ] `.../css/styles.css` and `.../js/app.js` return HTTP 200
- [ ] `.../_shared/fontawesome/7.3.1/css/all.min.css` returns HTTP 200
- [ ] `.../api/health` returns `{"status":"ok"}`
- [ ] `.../backend/.env`, `.../DB.xlsx`, `.../db/schema.sql` all return **404** (defense-in-depth check — see [§17](#17-security-notes))

**Application (browser, with real login):**
- [ ] Login with a real account succeeds and lands on the Dashboard
- [ ] Logout returns to the login screen and a page reload doesn't silently log back in
- [ ] Navigate to Cases, Documents, Search, Notifications, Reminders, Users & Permissions (as Admin) — each loads real data, no console errors
- [ ] A document preview/download works (exercises the authenticated file-serving path, not a static mount)
- [ ] The language toggle flips the whole UI to English/LTR and back
- [ ] No unexpected 401s in the Network tab for a logged-in session

**Responsive/UI** (see [§18](#18-responsive--ui-architecture) for what's already been validated — this is a quick spot-check, not a full re-test):
- [ ] No horizontal page overflow at 320px and 1440px on Dashboard and Search
- [ ] Mobile bottom navigation and the "More" sheet both work

---

## 15. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `/api/...` returns IIS's own 404 page (not a JSON error) | `web.config` is missing, malformed, or the `httpPlatformHandler` module isn't installed | Confirm `web.config` exists at the project root and is well-formed XML (an XML comment containing two hyphens in a row, `--`, breaks the whole file — this happened once during setup); confirm the module is installed (see [§13](#13-iis-configuration-reference)) |
| IIS shows a 500.19 error, "Configuration file is not well-formed XML" | Same as above — invalid XML in `web.config`, most commonly `--` inside a comment | Open `web.config`, find the offending comment, remove the double-hyphen |
| The app pool starts a worker process, but every request times out or 500s, and `backend\logs\uvicorn-stdout.log_<pid>_<n>.log` shows a `pydantic_core.ValidationError` for missing fields (`db_user`, `db_password`, `jwt_secret`, …) | The app can't find `backend\.env` — this happens if `Settings`' `env_file` path is ever changed back to a bare relative `".env"`, since httpPlatformHandler's working directory is the site root, not `backend\` | Confirm `backend/app/config.py` resolves `env_file` from `Path(__file__).resolve().parent.parent / ".env"` (an absolute path derived from the file's own location), not a bare `".env"` string |
| Document upload fails in production but works in local dev | `backend\.env`'s `UPLOAD_DIR` is still the relative dev default (`./uploads`), which resolves against the wrong working directory under IIS | Set `UPLOAD_DIR` to the absolute path in `backend\.env` (see [§9](#9-configuration-reference-env)) |
| The whole site 404s on every path, including `/` | `FRONTEND_DIR` is wrong/missing, or `index.html` isn't at the expected location | Confirm `FRONTEND_DIR` in `.env` points at the folder containing `index.html`, `css/`, and `js/` |
| `pip install -r backend\requirements.txt` fails with "no matching distribution" | A version pin in `requirements.txt` doesn't exist on PyPI (this happened with `pymysql==2.2.8`, fixed to `1.2.0`) | Check the failing package on PyPI for its actual available versions and correct the pin |
| A logged-in session behaves oddly across two browser tabs of the same browser | The app uses `sessionStorage`, not `localStorage`, for the session token — by design, each tab that wasn't open at login time won't see it | This is expected behavior, not a bug; log in again in the new tab |
| CSS/JS changes don't show up after editing, even after a hard refresh | Only relevant to local dev — see the `no_cache_for_app_assets` middleware in `main.py`, which already sends `Cache-Control: no-store` for `.css`/`.js` specifically to prevent this |
| Static assets (CSS/JS) load, but styling looks broken and `_shared` fonts/icons 404 | `SHARED_ASSETS_DIR` doesn't point at a real, reachable folder on this machine | Confirm `C:\inetpub\sites\_shared` exists and is readable by the app pool identity |
| `backend\logs\uvicorn-stdout.log_<pid>_<n>.log` shows `No module named <package>` even though `pip show <package>` finds it fine when you run it yourself | The package installed into your Windows user's *per-user* site-packages, not the machine-wide one — invisible to the IIS App Pool identity that actually runs the process (see [§12.3](#123-install-dependencies)) | `python -m pip install --no-user --force-reinstall --no-deps <package>==<version>`, then recycle the app pool |
| Browser console shows `Uncaught TypeError: Cannot read properties of undefined (reading 'startTime')` referencing `reportAllChanges`/`requestIdleCallback` in an anonymous script | **Not application code.** It is Google's `web-vitals`, carried by the Cloudflare Web Analytics beacon that Cloudflare's edge injects into the HTML on browser navigations (absent from `index.html` on disk and from the origin's own response; `reportAllChanges` appears nowhere in this source tree). Full analysis in [3.6d](#36d-the-reportallchanges--starttime-console-error) | It stopped once the application's own SPA render-lifecycle exceptions were fixed ([3.6c](#36c-spa-render-lifecycle--one-container-per-navigation)) and has not recurred. If it returns, either disable Web Analytics for the zone in the Cloudflare dashboard, or add a `script-src 'self' 'unsafe-inline'` CSP meta tag to `index.html` — both tested, both documented in 3.6d |
| A printout contains the sidebar, buttons, or a clipped table | The browser's own **Ctrl+P** was used without first pressing a page's **Print** button, so no `#print-root` sheet had been composed | Use the page's **Print** button. The `@media print` block hides `#app-root`, `.toast-container` and `.modal-overlay` and shows only `#print-root` — see [3.6b](#36b-printing-jsprintjs) |

**Where to look:** `backend\logs\uvicorn-stdout.log_<pid>_<n>.log` (production, one file per process start — httpPlatformHandler appends a pid/counter suffix) is the single most useful place to look; it captures the Python process's full stdout/stderr, including unhandled tracebacks.

---

## 16. Rollback

There is no automated deployment pipeline for this project — "rollback" means reverting the files and/or configuration by hand.

1. **Code rollback:** since the project is a git repository, revert to a known-good commit (`git log`, then `git checkout <commit>` or `git revert`) and redeploy those files to the IIS physical path.
2. **Dependency rollback:** if a `pip install` of updated `requirements.txt` breaks something, reinstall the previous, known-good `requirements.txt`:
   ```
   python -m pip install --no-user --force-reinstall -r backend\requirements.txt
   ```
   `--force-reinstall` ensures the older pinned versions actually overwrite whatever the broken update left behind, rather than pip seeing "already satisfied" and doing nothing.
3. **Configuration rollback:** `backend\.env` and `web.config` are not tracked by git (the former is gitignored on purpose; the latter should be backed up manually before editing, e.g. copy it to `web.config.bak` first). Keep a known-good copy of both outside the repo before making changes.
4. **Database rollback:** restore from your most recent `mysqldump` backup (see [§10](#10-database)) — there is no automatic schema-migration rollback, since there is no migration tool in this project.
5. **After any rollback:** recycle the app pool (`appcmd recycle apppool "ASLG"`) and re-run the [Verification Checklist](#14-verification-checklist).

---

## 17. Security Notes

Findings and fixes from the September 2026 production-readiness pass, kept here so the reasoning isn't lost:

- **Fixed — critical: unauthenticated exposure of the entire project root.** The frontend used to be served via `StaticFiles(directory=frontend_dir, html=True)` mounted at `/`, where `frontend_dir` is the *project root* (it also contains `backend/`, including `backend/.env` with the database password and JWT secret, all Python source, and `db/schema.sql`). This meant `GET /backend/.env`, `GET /backend/app/main.py`, `GET /db/schema.sql`, and `GET /DB.xlsx` were all directly downloadable by anyone, unauthenticated — confirmed exploitable before the fix. **Fixed** by mounting only `/css`, `/js`, and explicit `/`/`/index.html` routes in `backend/app/main.py`; nothing else is served. Verified 404 on all of the above after the fix, both via the local dev server and through the production IIS binding. A second, independent layer of defense against the same class of mistake was also added at the IIS level (`web.config` request filtering — see [§13](#13-iis-configuration-reference)), so a future regression in the Python app wouldn't be enough on its own to re-expose these files.
- **Fixed — CORS was wide open (`allow_origins=["*"]`).** Since the frontend is always same-origin with the API in every real deployment, this had no legitimate use and only widened the attack surface. **Fixed** by restricting to an explicit allowlist (`CORS_ALLOWED_ORIGINS` in config, covering the production hostname and local dev only).
- **Fixed — `backend\requirements.txt` had an unpinnable version.** `pymysql==2.2.8` does not exist on PyPI (the real latest is `1.2.0`); a clean `pip install` on a new machine would fail outright. This had gone unnoticed because the machine this was developed on already had a different version installed globally. **Fixed** by correcting the pin to match the actually-tested, working version.
- **Fixed — production file-permission gaps.** The IIS Application Pool identity (`IIS AppPool\ASLG`) had only Read & Execute on `backend\uploads\` and `backend\logs\`, which would have made document uploads and Uvicorn's own log file both fail silently in production (they worked in every session so far only because testing ran under a full-permission user account, not the app pool identity). **Fixed** by explicitly granting Modify on both folders to the app pool identity.
- **Fixed — relative-path settings broke under IIS.** `UPLOAD_DIR`, `FRONTEND_DIR`, and pydantic-settings' own `.env` file lookup were all resolved relative to the process's working directory, which is `backend/` in the documented dev workflow but the *project root* under `httpPlatformHandler`. This silently pointed uploads/frontend files at the wrong location (or, in `.env`'s case, made the app fail to start at all with a validation error) — see [§9](#9-configuration-reference-env) and [§15](#15-troubleshooting) for the full explanation and fix.
- **Verified clean:** no hardcoded secrets, passwords, or API keys anywhere in source (`grep`-checked); `DEBUG`/reload flags are not enabled in the production launch command; no `localhost`/`127.0.0.1` values appear anywhere they'd break production (the two occurrences that exist — `DB_HOST` default and one entry in the CORS allowlist — are both correct on purpose, since MySQL and the API are same-box/same-origin respectively); passwords are bcrypt-hashed everywhere, never stored or logged in plaintext; the 9 seeded accounts share one starting password that lives only in `backend/seed.py` and is not reproduced in any documentation (see [§5](#5-quick-reference-default-test-accounts)) — if this ever needs to serve real, non-demo users, treat those 9 accounts as needing a password reset first.
- **Recommendation, not yet done (low priority):** `/_shared` is currently proxied through the Python process like everything else. A sibling project on this server (`hrms`) instead serves its equivalent shared-assets path directly via IIS's own static handler, so icons/fonts stay up even if the Python process or its database connection is down. This would require adding an IIS virtual directory for `_shared` pointed at `C:\inetpub\sites\_shared`, which wasn't done in this pass to avoid unnecessary IIS-level changes beyond what correctness required — worth doing if resilience against backend outages becomes a priority.
- **Fixed — passwordless login endpoint removed for production.** `POST /api/auth/quick-login` (and the public, unauthenticated `GET /api/auth/users` roster that fed it) let anyone log in as *any* account by user ID alone, no password — a deliberate test-environment convenience (the login page's former "Quick Role Switch" grid) that had no place in a production deployment: leaving it live would have meant zero-credential admin access for anyone who found the endpoint. **Removed entirely** — both endpoints, the `QuickLoginRequest` schema, and the login page's quick-switch grid and admin-credential hint box. Verified: both routes now return 404. Real username/password login (`POST /api/auth/login`, bcrypt-verified) is unaffected and is now the only way in — see [§5](#5-quick-reference-default-test-accounts) for working credentials.
- **By design — Procedural Intelligence never automates access to a government portal.** Every official Kuwait channel researched (MOJ e-Services, Sahel, Sahel Business, the MOJ site) is either login+CAPTCHA gated or requires the caller's own personal sign-in; none publish an API. This app therefore never stores a government credential, never solves or bypasses a CAPTCHA, and never scrapes an authenticated government endpoint — see [§3.8](#38-procedural-intelligence). The only "sync" is a human opening the real portal themselves and recording what they saw.
- **By design — a legal deadline is never presented as fact without a named lawyer's sign-off.** Every `procedure_rules` row ships disabled with a source tier that is at best `official_inferred` at seed time; enabling one (asserting it as a fact the firm relies on) is restricted to Admin or an owner-Lawyer, requires an explicit `confirm: true`, and is refused outright if the rule's `source_tier` is still `unverified` — see `backend/app/routers/rules.py`. This is why the Cassation-appeal rule ships as two competing, both-disabled candidates (30 vs 60 days) rather than a guessed single value.

---

## 18. Responsive & UI Architecture

The frontend went through two dedicated responsive-engineering passes (documented in full in the project's session history; summarized here for future maintainers):

- **Design tokens:** a Primitive → Semantic → Component CSS custom-property hierarchy in `css/styles.css` (`--space-*`/`--text-*` primitives → `--surface`/`--text`/`--success` etc. semantic tokens → `--control-height`/`--gutter`/`--content-max` component tokens), with legacy aliases (`--color-bg`, etc.) so no existing component rule had to change during the migration.
- **Mobile is a layout adaptation, not a separate app:** one shared codebase for both modes. Below 768px, the sidebar is replaced by a bottom tab bar + a slide-up "More" sheet (`js/app.js`), all sharing the exact same routes/data/business logic as desktop.
- **Tables become mobile record cards, not horizontal-scroll tables:** row-based tables (search results, cases, documents, users) carry a `.data-table` class and per-cell `data-label` attributes; a CSS media query at ≤768px transforms them into stacked key/value cards, with the header row visually hidden but kept in the accessibility tree (not `display:none`, which would remove it entirely). The **Users → Permissions matrix is a deliberate exception** — it stays a plain, horizontally-scrollable table at every width, because a role × module comparison grid is genuinely two-dimensional and would lose its point if stacked into cards.
- **Navigation labels are content-aware:** the sidebar and the "More" sheet use full descriptive labels (`nav_reminders` = "Reminders & Follow-ups"); the bottom tab bar and the top bar's title use short labels (`nav_reminders_short` = "Reminders") via a shared `.label-full`/`.label-short` CSS pair that both markup locations render — the swap is a pure CSS breakpoint flip, never a JS viewport check.
- **Known, documented exceptions:** `.btn-sm` (36px) is intentionally below the 44px `--control-height` touch-target floor for dense, repeated inline table/case-list actions; the Search tab bar uses contained horizontal scroll as a deliberate choice (5 tabs genuinely don't fit a narrow screen without either scrolling or losing information). Cases no longer has a Kanban view at all (removed by request — table is now the only, default view), so that's no longer part of this list.
- **Form labels are wired up automatically, app-wide:** every `.form-group > label` in the app (login, search, cases, documents, reminders, users — several dozen fields) previously sat next to its `<input>`/`<select>`/`<textarea>` with no `for`/`id` pairing, which is exactly what triggers a browser's "a `<label>` isn't associated with a form field" warning. Rather than hand-adding `id`/`for` pairs at each of those call sites, `js/app.js` runs a single `MutationObserver` on `document.body` (covers `#app-root` and every modal, since modals mount directly on `document.body`) that auto-assigns an `id` and matching `label[for]` to any bare `.form-group` label it finds — fixes every current field and any future one, with no per-page-module changes required.
- **Not done, out of scope:** a wholesale px→rem conversion of the pre-existing (pre-audit) component CSS, which still uses raw pixel font sizes in many places — real browser zoom (Ctrl+/−) still works correctly on it, but OS-level "default font size" accessibility settings won't reach it. Flagged as a larger, separate future effort.

Both passes were validated by actually rendering the app (via a same-origin iframe harness, since this environment's browser-automation `resize_window` tool does not genuinely change a tab's viewport) at 320/360/375/390/414/768/1024/1280/1440px, checking both `scrollWidth`/`clientWidth` overflow and visual quality, in both English/LTR and Arabic/RTL.

---

## 19. Maintenance

- **Adding a new page/route:** add an entry to the `ROUTES` array in `js/app.js` (icon, permission key, `label`/`shortLabel` i18n keys, the page module), add the corresponding `nav_*`/`nav_*_short` strings to both language blocks in `js/i18n.js`, and create `js/pages/<name>.js` following the existing `render(container, user)` / `destroy()` pattern used by every other page module.
- **Adding a new data table:** reuse the `.data-table` class + `data-label` attribute pattern described in [§18](#18-responsive--ui-architecture) rather than a plain `<table>`, unless the data is a genuine two-dimensional comparison grid like the permissions matrix — see that section for the distinction.
- **Adding a new backend dependency:** add it to `backend/requirements.txt` with an exact, PyPI-verified version pin, then `python -m pip install --no-user -r backend/requirements.txt` and confirm the app still imports (`python -c "from app.main import app"`) before deploying. `--no-user` matters here too — see [§12.3](#123-install-dependencies).
- **Rotating `JWT_SECRET`:** changing it immediately invalidates every currently-logged-in session (all existing tokens fail signature verification) — plan for a brief mass-logout when doing this in production.
- **Changing the production hostname or path:** update the IIS binding and physical path, then update the three absolute paths inside `web.config` (see [§12.7](#127-webconfig)) and the absolute paths in `backend\.env` (`UPLOAD_DIR`, `FRONTEND_DIR`) to match — nothing in the application code itself is hostname- or path-specific.
- **Adding a page, or adding an `await` to an existing one:** the router hands every render its own container element (`app.js::handleRoute`), so a render that resumes after the user navigated on writes to a detached node rather than dereferencing `null`. Do not reintroduce a shared, long-lived `#page-content` reference. Wire any control the user can press *before* the first `await`, so the button is never dead while data loads.
- **Adding a Print button:** import `printRecord`/`printButton` from `js/print.js` and pass a data spec (`{title, subtitle, meta, sections}`). Never call `window.print()` directly and never add page-specific `@media print` rules to hide chrome — the sheet is composed from data, so there is no chrome to hide.
- **Adding a new audited action:** just call `log_activity(...)`. The client IP is filled in from the request context automatically — do not pass `ip_address=` and do not read `request.client.host`. If the new caller runs outside an HTTP request, it correctly records NULL.
- **Changing how the site is published** (removing the Cloudflare tunnel, adding a different reverse proxy, binding IIS to the public interface): re-read `backend/app/client_ip.py`. Its trust rule — "believe `CF-Connecting-IP` only when IIS's own peer was loopback" — is a statement about *this* topology. A new front-most hop makes it wrong, and the Activity Log's IP column is the thing that quietly degrades.
- **Changing the business week:** edit `WEEKEND_WEEKDAYS` (and `BUSINESS_WEEK_ORDER`) in `backend/app/kuwait_time.py` only. `escalation.py` reads the rule through `is_kuwait_weekend()` and holds no copy of it. Today: **Friday is the only weekend day; Saturday is a working day; Sunday starts the week.**
- **Asking any calendar question ("today", "which weekday", "hearings on this date"):** go through `backend/app/kuwait_time.py`. Never call `.date()` or `.weekday()` on a stored value directly — stored values are naive UTC and answer those questions in the wrong timezone for the first three hours of every Kuwait day. Instant-vs-instant comparisons (`x >= utcnow()`) need no conversion and should stay as they are.
- **Changing notification timing or wording:** everything lives in `backend/app/escalation.py`. Keep the two invariants in `_layer_moments()` intact (all layers strictly before the event; layers strictly increasing) and keep every message a pure function of `(event, layer)` — introducing "now" into a message string silently breaks `_notify_once()` deduping and causes repeat spam. Any change here must also be reflected in [§3.4](#34-reminders--status-update-requests-and-owner-task-assignment) and in the "three warnings" section of `GUIDELINES.md`.
- **Changing any user-visible label:** the string lives in **both** language blocks of `js/i18n.js`. `GUIDELINES.md` quotes visible UI text verbatim (page names, button labels, toast messages) so users can match what they read to what they see — update it in the same change, or the manual starts describing a UI that no longer exists.
