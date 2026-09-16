from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .client_ip import ClientIPMiddleware
from .config import settings
from .routers import (
    activity_log,
    admin,
    auth,
    cases,
    dashboard,
    deadlines,
    documents,
    internal,
    notifications,
    official_sync,
    procedures,
    reminders,
    rules,
    search,
    users,
)

app = FastAPI(title="ASLG Legal Portal API", version="1.0.0")

# Registered FIRST so it ends up INNERMOST — Starlette applies user middleware
# in reverse, so the earliest-added wraps the router most closely. That matters:
# it puts the ContextVar assignment inside anything that might run the rest of
# the stack in a separate task, so the resolved address is reliably visible to
# every endpoint and therefore to every audit row those endpoints write.
# See client_ip.py for the trust rules; this line is only plumbing.
app.add_middleware(ClientIPMiddleware)

# The frontend is same-origin in every real deployment (IIS serves both the
# static files and, via httpPlatformHandler, this API from one hostname) —
# nothing here actually needs cross-origin access. allow_origins is closed
# to an explicit allowlist rather than "*" so a token that ever leaked to
# client-side JS couldn't be replayed from an arbitrary third-party page;
# ALLOWED_ORIGINS lets a real cross-origin need (e.g. a separate marketing
# site embedding a widget) be added later without loosening this by default.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Extensions served straight off disk that an operator edits in place on the
# live site. Kept as a tuple rather than inlined so the list is one obvious
# thing to extend when a new asset type is added.
_NO_STORE_SUFFIXES = (
    ".css", ".js",
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".svg", ".ico",
    ".html",
)


@app.middleware("http")
async def no_cache_for_app_assets(request, call_next):
    """FastAPI's StaticFiles sends only ETag/Last-Modified, no explicit
    Cache-Control — several browsers (Chrome iframes in particular) then
    serve a stale copy on a plain reload without ever revalidating, so an
    edited stylesheet/script can silently keep rendering old behavior.
    That's actively dangerous during local development: a real fix can
    look like it "didn't work."

    The same applies to /assets images and to the index.html shell, and
    more sharply, because this deployment IS the live site: images are
    replaced in place (background.jpg has been swapped twice) and there is
    no build step or content hash to change the URL. Without an explicit
    header both the browser AND Cloudflare in front of it fall back to
    *heuristic* freshness — typically a fraction of the time since
    Last-Modified — which is the worst of both worlds: uncontrolled, and
    unpredictable per client. `no-store` makes a file edit visible on the
    next request, everywhere, with no purge step. index.html is included
    for the same reason: a stale shell keeps serving the old <script> and
    <link rel=preload> tags however fresh the files they point at are.

    This deliberately trades bandwidth for immediacy. The photograph is
    ~335 KB and is refetched per login page view; at this firm's traffic
    that is not a meaningful cost, and correctness of what the operator
    sees after an edit is worth more.

    Shared, rarely-changing assets under /_shared (fonts, icons) are left
    alone — they are not edited in place here, and they benefit from
    caching. Note `request.url.path` is the decoded path without the query
    string, so a `?v=` cache-buster cannot accidentally defeat the match."""
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/_shared/"):
        return response
    # "/" resolves to the index.html shell via StaticFiles(html=True). Routing
    # inside the SPA is hash-based, so that is the only extensionless HTML
    # entry point — no need for a broader "any trailing slash" rule, which
    # would also sweep in API paths.
    if path == "/" or path.endswith(_NO_STORE_SUFFIXES):
        response.headers["Cache-Control"] = "no-store"
    return response


app.include_router(auth.router)
app.include_router(users.router)
app.include_router(cases.router)
app.include_router(search.router)
app.include_router(documents.router)
app.include_router(notifications.router)
app.include_router(reminders.router)
app.include_router(dashboard.router)
app.include_router(activity_log.router)
app.include_router(admin.router)
app.include_router(procedures.router)
app.include_router(deadlines.router)
app.include_router(official_sync.router)
app.include_router(rules.router)
app.include_router(internal.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


# Mirrors the IIS estate-wide "/_shared" virtual directory locally, so the
# frontend's root-relative /_shared/... font & icon URLs resolve the same
# way under `uvicorn` as they do in production under IIS.
shared_dir = Path(settings.shared_assets_dir)
if shared_dir.exists():
    app.mount("/_shared", StaticFiles(directory=shared_dir), name="shared-assets")

# Serves the vanilla-JS frontend (index.html, css/, js/) as static files.
# In production this is normally IIS's job with /api reverse-proxied here;
# mounted last so it never shadows the API routes above.
#
# IMPORTANT: this mounts only the specific css/ and js/ subdirectories and
# index.html itself — never `frontend_dir` as a whole. frontend_dir is the
# project root, which also contains backend/ (including backend/.env: the
# DB password and JWT signing secret) and db/schema.sql. An earlier version
# of this mounted `StaticFiles(directory=frontend_dir, html=True)` at "/",
# which serves *any* file under that root over plain HTTP with no
# authentication — confirmed exploitable (backend/.env, backend/app/*.py,
# db/schema.sql were all directly downloadable). Routing is client-side
# hash fragments (#/dashboard etc.), which the browser never sends to the
# server, so no other top-level path needs to be served at all.
frontend_dir = Path(settings.frontend_dir).resolve()
if (frontend_dir / "index.html").exists():
    app.mount("/css", StaticFiles(directory=frontend_dir / "css"), name="frontend-css")
    app.mount("/js", StaticFiles(directory=frontend_dir / "js"), name="frontend-js")
    if (frontend_dir / "assets").exists():
        app.mount("/assets", StaticFiles(directory=frontend_dir / "assets"), name="frontend-assets")

    @app.get("/", include_in_schema=False)
    @app.get("/index.html", include_in_schema=False)
    def serve_index():
        return FileResponse(frontend_dir / "index.html")
