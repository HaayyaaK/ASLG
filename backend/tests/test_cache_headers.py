"""Regression tests for the `no_cache_for_app_assets` middleware in
`app/main.py`.

This deployment IS the live site: files are edited in place, there is no
build step, and no content hash ever changes an asset's URL. So the only
thing standing between an operator's edit and a stale copy in a browser (or
in the Cloudflare cache in front of it) is this one response header. If it
silently stops covering a file type, nothing fails and no log records it —
the operator just sees their change "not take effect" some of the time, on
some machines. That is precisely the class of bug a test has to hold down.

The assertions deliberately do NOT depend on the file existing. The
middleware runs on the way out, so a 404 for /assets/background.jpg still
carries the header — which means these tests check the *policy*, and keep
passing whether or not FRONTEND_DIR happens to resolve in the environment
running them.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.mark.parametrize(
    "path",
    [
        "/",                            # the index.html shell (StaticFiles html=True)
        "/index.html",
        "/css/styles.css",
        "/js/app.js",
        "/assets/background.jpg",       # the login photograph, replaced in place
        "/assets/logo.png",
        "/assets/favicon.ico",
        "/assets/site.webmanifest.svg",
    ],
)
def test_editable_static_assets_are_never_stored(client, path):
    resp = client.get(path)
    assert resp.headers.get("Cache-Control") == "no-store", (
        f"{path} is served without no-store — a browser or Cloudflare may "
        "then apply *heuristic* freshness (a fraction of the age since "
        "Last-Modified), so an in-place edit to this file becomes visible "
        "at an unpredictable time, differently per client."
    )


@pytest.mark.parametrize(
    "path",
    ["/_shared/fonts/some-font.woff2", "/_shared/icons/x.svg", "/_shared/x.css"],
)
def test_shared_cross_project_assets_keep_their_cacheability(client, path):
    """/_shared is a cross-project asset directory that is not edited from
    this repo. It was excluded deliberately when the middleware only covered
    css/js; broadening the suffix list to images and HTML must not have
    swept it in as a side effect."""
    resp = client.get(path)
    assert "Cache-Control" not in resp.headers


@pytest.mark.parametrize(
    "path",
    ["/api/cases", "/api/dashboard/stats", "/api/documents/1/download"],
)
def test_api_responses_are_left_alone(client, path):
    """API responses are already uncacheable in practice and are not the
    middleware's business. This guards the tightening made when index.html
    was added: an early draft matched *any* path ending in "/", which also
    swept in API collection routes."""
    resp = client.get(path)
    assert "Cache-Control" not in resp.headers


def test_document_downloads_are_not_matched_by_the_image_suffixes(client):
    """`GET /api/documents/{id}/download` serves user-uploaded files, which
    may well be .jpg or .png. It must be matched on its *URL* (which has no
    extension), not on the file it happens to return — otherwise adding
    image suffixes to the list would quietly change caching for every
    uploaded document."""
    resp = client.get("/api/documents/7/download")
    assert "Cache-Control" not in resp.headers
