"""Regression tests for the three defects behind the reported "the app
freezes after a while" bug.

None of the three throws, logs, or fails a request. They are all *absences*:
something that should have been there wasn't, and the visible result was a
page stuck on its loading spinner. An absence is invisible to every other
kind of test, and trivially reintroduced by a future refactor, which is why
each one is pinned here.

The frontend has no build step and no JS test runner, so — exactly as
test_i18n_parity.py already does for the translation dictionaries — these
parse the source directly. That is a real guard against regression, not a
substitute for exercising the behaviour in a browser.

The three:

  1. `fetch` has no default timeout. A request that never gets a response
     waits forever, so the spinner never resolves. The trigger is routine:
     this deployment's IIS app pool is set `idleTimeout: 00:20:00` /
     `idleTimeoutAction: Terminate`, and the Windows event log records the
     ASLG worker being "shutdown due to inactivity" ten-plus times a day.
     The next request must cold-start Python + uvicorn (~1.4s just to import
     app.main, so 2-4s in practice).
  2. The router called each page module's `async render()` without awaiting
     it and without a `.catch()`, so a rejection became an unhandled promise
     — no error shown, spinner left on screen.
  3. Nothing logged unhandled rejections at all, so the above was silent in
     the console too.
"""

import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
API_JS = PROJECT_ROOT / "js" / "api.js"
APP_JS = PROJECT_ROOT / "js" / "app.js"
IDLE_JS = PROJECT_ROOT / "js" / "idle.js"
I18N_JS = PROJECT_ROOT / "js" / "i18n.js"


# ---------------------------------------------------------------- defect 1

def test_every_request_is_bounded_by_a_timeout():
    """`request()` must route through an AbortController-backed helper. If
    a future edit calls `fetch` directly again, the unbounded-wait freeze
    comes straight back."""
    src = API_JS.read_text(encoding="utf-8")
    assert "AbortController" in src
    assert "controller.abort()" in src
    # Every fetch call in the file must pass a signal.
    for call in re.findall(r"fetch\(([^;]*?)\)\s*;", src, re.S):
        assert "signal" in call, f"fetch call without an abort signal: {call.strip()[:120]}"


def test_timeouts_are_a_distinguishable_error_type():
    """The page error state shows a different message (and a Retry that is
    actually worth pressing) for a timeout than for a 4xx/5xx. That relies
    on the thrown error being identifiable rather than a bare Error."""
    src = API_JS.read_text(encoding="utf-8")
    assert "class RequestTimeoutError" in src
    assert "isTimeout" in src
    assert "isTimeout" in APP_JS.read_text(encoding="utf-8")


def test_uploads_get_a_longer_timeout_than_ordinary_requests():
    """MAX_UPLOAD_MB is 25. Applying the normal request timeout to a file
    upload would abort healthy uploads on a slow connection — a fix that
    introduces a worse bug than the one it removes."""
    src = API_JS.read_text(encoding="utf-8")
    normal = int(re.search(r"REQUEST_TIMEOUT_MS\s*=\s*(\d+)", src).group(1))
    upload = int(re.search(r"UPLOAD_TIMEOUT_MS\s*=\s*(\d+)", src).group(1))
    assert upload > normal


def test_a_timed_out_request_is_never_retried():
    """Two reasons, both learned by measuring the real thing in a browser:

    Safety — a timed-out POST may already have been applied server-side, so
    replaying it could create a duplicate case or note. Only a rejected
    `fetch` (no response received at all, i.e. the cold-start window, which
    fails in milliseconds) is safe to replay.

    Speed — an earlier version retried timed-out GETs. Measured end-to-end
    against the live site with a hanging `fetch`, the user waited 43s
    (20s + 1.2s + 20s) before seeing anything. One timeout then the error
    state's Retry button is both faster and more honest.
    """
    src = API_JS.read_text(encoding="utf-8")
    assert re.search(r"if\s*\(\s*err\.isTimeout\s*\)\s*throw\s+err\s*;", src), (
        "the retry guard no longer refuses to retry timed-out requests"
    )
    retry_block = src.split("let res;")[1].split("if (res.status === 401)")[0]
    assert retry_block.count("fetchWithTimeout") == 2, (
        "expected exactly one initial attempt plus one retry"
    )


# ---------------------------------------------------------------- defect 2

def test_page_render_failures_are_caught_and_shown():
    """`target.page.render(...)` must not be left as a bare unawaited call."""
    src = APP_JS.read_text(encoding="utf-8")
    assert re.search(r"\.catch\(\s*\(?err\)?\s*=>\s*renderPageError", src), (
        "router no longer routes page-render rejections into an error state"
    )
    assert "function renderPageError" in src
    assert not re.search(r"^\s*target\.page\.render\([^)]*\);\s*$", src, re.M), (
        "found a bare, uncaught target.page.render(...) call again"
    )


def test_the_error_state_offers_a_retry():
    """A dead end is only marginally better than a spinner: the cold-start
    case is fixed by simply trying again, so the user must be able to."""
    src = APP_JS.read_text(encoding="utf-8")
    assert "page-error-retry" in src
    assert "handleRoute()" in src


# ---------------------------------------------------------------- defect 3

def test_unhandled_rejections_are_surfaced():
    src = APP_JS.read_text(encoding="utf-8")
    assert "unhandledrejection" in src
    assert "installGlobalErrorHandlers" in src


# ---------------------------------------------------------------- idle timer

def test_idle_thresholds_warn_before_they_log_out():
    """A warning that fires at or after the logout moment is not a warning."""
    src = IDLE_JS.read_text(encoding="utf-8")
    logout = eval(re.search(r"IDLE_LOGOUT_MS\s*=\s*([\d\s*]+);", src).group(1))
    warning = eval(re.search(r"IDLE_WARNING_MS\s*=\s*([\d\s*]+);", src).group(1))
    assert warning < logout
    assert logout == 15 * 60 * 1000
    assert logout - warning == 2 * 60 * 1000


def test_activity_is_ignored_while_the_warning_is_shown():
    """Without this guard, moving the mouse toward the "Stay signed in"
    button counts as activity, resets the clock and dismisses the warning —
    so the dialog can never be answered and nobody is ever signed out. The
    feature would look implemented and do nothing."""
    src = IDLE_JS.read_text(encoding="utf-8")
    body = src.split("function markActive()")[1].split("}")[0]
    assert "if (warningEl) return;" in body


def test_staying_signed_in_renews_the_token_server_side():
    """Resetting only the local timer would leave the JWT expiring on its
    original schedule, bouncing the user to the login screen mid-task — the
    exact failure this change exists to remove."""
    src = IDLE_JS.read_text(encoding="utf-8")
    assert "refreshSession" in src and "setSession" in src
    assert "refreshSession" in API_JS.read_text(encoding="utf-8")


def test_idle_timer_is_stopped_on_logout_and_on_the_login_screen():
    """A timer left running after logout would fire against a signed-out
    app; one left running across sessions would use the previous user's
    clock."""
    src = APP_JS.read_text(encoding="utf-8")
    assert src.count("stopIdleTimer()") >= 2
    assert "startIdleTimer(doLogout)" in src


@pytest.mark.parametrize(
    "key",
    [
        "idle_warning_title", "idle_warning_body", "idle_stay_signed_in",
        "idle_sign_out_now", "idle_signed_out", "page_error_title",
        "page_timeout_title", "page_timeout_body", "retry", "unexpected_error",
    ],
)
def test_new_strings_exist_in_both_languages(key):
    """test_i18n_parity.py already enforces this globally; naming the keys
    explicitly here makes a deletion fail against the feature that owns
    them rather than against a generic parity count."""
    src = I18N_JS.read_text(encoding="utf-8")
    assert len(re.findall(rf"^\s{{4}}{key}:", src, re.M)) == 2, (
        f"{key} is not defined in exactly both the Arabic and English dictionaries"
    )
