"""Resolving the real client IP behind this deployment's proxy chain.

THE CHAIN
---------
A request reaching this application has passed through three hops:

    browser/device
      -> Cloudflare edge            (TLS terminates here; adds CF-Connecting-IP)
      -> cloudflared on THIS host   (outbound-only tunnel; connects to IIS
                                     over the loopback interface, so IIS sees
                                     the client as ::1)
      -> IIS :80                    (adds/overwrites X-Forwarded-For with its
                                     OWN peer, in IIS's non-standard
                                     "address:port" form, e.g. "[::1]:51203")
      -> httpPlatformHandler
      -> uvicorn on 127.0.0.1       (this process)

Because every hop is a proxy, `request.client.host` is useless on its own: it
is always the loopback address of the hop in front of us. Before this module
existed the Activity Log stored exactly that, and because IIS appends the
ephemeral source port the stored values looked like seventeen different
addresses ("[::1]:51203", "[::1]:51049", ...) when they were one machine
talking to itself.

THE TRUST BOUNDARY
------------------
`CF-Connecting-IP` is only meaningful if the request actually came through
Cloudflare. It is a plain request header, so anything that can reach IIS
directly can set it to any value it likes. This host is NOT provably
unreachable except through the tunnel: Windows Firewall has an inbound allow
rule for TCP/80 ("World Wide Web Services (HTTP Traffic-In)") and the machine
holds a globally-routable IPv6 address, so a direct hit on the origin is at
least possible.

So the header is never trusted on its own. Instead we use the one thing an
outside caller cannot forge: **IIS's own view of who connected to it**, which
IIS reports in X-Forwarded-For. The tunnel runs on this host, so a genuine
tunnelled request always shows IIS a loopback peer. Anything arriving over the
LAN or the public IPv6 shows IIS that real address instead, and its
CF-Connecting-IP header — forged or not — is discarded.

    IIS's peer is loopback  -> came from cloudflared -> trust CF-Connecting-IP
    IIS's peer is anything  -> came in directly      -> that peer IS the client
    no X-Forwarded-For      -> no proxy in front     -> our own peer is the client

The failure mode is deliberately the safe one: when in doubt we record the
address we can actually see rather than the one we were told about, so the
Activity Log can under-report but can never be made to name an innocent
third party.

NOTE ON UVICORN
---------------
uvicorn enables `--proxy-headers` by default and would rewrite
`request.client` from X-Forwarded-For itself, with `forwarded_allow_ips`
defaulting to 127.0.0.1 — which our peer always is. That silently replaced the
real peer with IIS's unparsed "address:port" string and left this module no
way to tell the two apart. `web.config` therefore passes `--no-proxy-headers`,
so `request.client` is the genuine TCP peer and every header decision is made
here, in one place, where it can be read and tested.
"""

from __future__ import annotations

import ipaddress
from contextvars import ContextVar

# Addresses that mean "this machine" — i.e. a hop we control, not a client.
_LOOPBACK_NETS = (
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
)

# The Activity Log column is a plain string; keep stored values bounded.
_MAX_LEN = 45  # longest possible textual IPv6 address


def _parse(value: str | None) -> ipaddress._BaseAddress | None:
    """Parse one address, tolerating the forms our proxies actually emit.

    Handles IIS's non-standard `address:port` X-Forwarded-For entries
    (`192.168.8.104:51203`, `[::1]:51203`) as well as plain addresses, and
    returns None for anything that is not a real IP — so a junk or hostile
    header value is dropped rather than stored.
    """
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None

    if raw.startswith("["):
        # "[::1]:51203" or "[::1]" — bracketed IPv6, port optional.
        end = raw.find("]")
        if end == -1:
            return None
        raw = raw[1:end]
    elif raw.count(":") == 1:
        # "1.2.3.4:5678" — IPv4 with a port. A bare IPv6 always has more than
        # one colon, so this cannot misfire on one.
        raw = raw.split(":", 1)[0]
    # Anything else is either a bare IPv4 or a bare, unbracketed IPv6.

    try:
        return ipaddress.ip_address(raw)
    except ValueError:
        return None


def _is_loopback(addr: ipaddress._BaseAddress | None) -> bool:
    if addr is None:
        return False
    return any(addr in net for net in _LOOPBACK_NETS)


def _last(header_value: str | None) -> str | None:
    """The RIGHT-most entry of a comma-separated forwarding header.

    This is the security-critical choice in this module, and the intuitive
    answer is the wrong one.

    `X-Forwarded-For` is *appended* to by each proxy it passes through, so it
    reads oldest-first: `<what the client sent>, <hop>, <hop>`. The left-most
    entry is conventionally "the original client" — but only when every hop in
    the chain is trusted. Here it is not: a caller can simply send an
    `X-Forwarded-For` of their own, and our infrastructure appends after it
    rather than replacing it. Reading the left-most entry therefore reads a
    value the caller chose.

    That was a real hole, caught by sending `X-Forwarded-For: 1.2.3.4` through
    the live site: the Activity Log dutifully recorded 1.2.3.4.

    The right-most entry is the one *our own* front-most hop appended, after
    any client-supplied text and with nothing downstream able to add to it. It
    is the only entry in the header a caller cannot influence, which is exactly
    what the trust decision needs.
    """
    if not header_value:
        return None
    return header_value.split(",")[-1].strip() or None


def client_ip(request) -> str | None:
    """The best address for this request that we are entitled to believe.

    Returns a plain address string with no port, or None when nothing can be
    determined. See the module docstring for the trust rules.
    """
    peer = _parse(request.client.host if request.client else None)

    # Hop 1: our own TCP peer. Under IIS this is always loopback; if it is
    # not, nothing is proxying us and the peer is the client.
    if not _is_loopback(peer):
        return str(peer)[:_MAX_LEN] if peer else None

    # Hop 2: who connected to IIS? IIS appends that to X-Forwarded-For, so it
    # is the RIGHT-most entry — see _last() for why the left-most one is
    # attacker-controlled. Absent header means no reverse proxy in front (a
    # direct local run), so our own peer stands and no header is consulted.
    iis_peer = _parse(_last(request.headers.get("x-forwarded-for")))
    if iis_peer is None:
        return str(peer)[:_MAX_LEN] if peer else None
    if not _is_loopback(iis_peer):
        # Someone reached IIS directly rather than through the tunnel. That
        # address is the client; any CF-Connecting-IP they sent is forged.
        return str(iis_peer)[:_MAX_LEN]

    # Hop 3: IIS's peer was this host's loopback, i.e. cloudflared. Only now
    # is Cloudflare's account of the original client worth believing.
    cf = _parse(request.headers.get("cf-connecting-ip"))
    if cf is not None:
        return str(cf)[:_MAX_LEN]

    # Tunnelled but no Cloudflare header (a direct call to cloudflared's local
    # target, or Cloudflare changing the header name): report what we saw.
    return str(iis_peer)[:_MAX_LEN]


# ---------------------------------------------------------------------------
# Making the resolved address available to the audit log
#
# `log_activity()` is called from deep inside request handlers that have no
# reason to know about HTTP — a document router should not have to thread a
# Request object through three layers just so the audit row can carry an IP.
# Passing `ip_address=` at all twenty-one call sites would also mean twenty-one
# chances to get it wrong, or to quietly reintroduce `request.client.host`.
#
# So the address is resolved exactly once per request, by the middleware below,
# and stashed in a ContextVar that `audit.log_activity()` reads by default.
# Two properties fall out of that for free:
#
#   * Anything running OUTSIDE a request — a management script, a future
#     scheduled job — sees the default, None, and writes NULL. Background work
#     can never be labelled with a stale address left over from some earlier
#     request, and the server's own address is never substituted for a missing
#     client one.
#   * There is still exactly one place the trust rules live: `client_ip()`
#     above. The middleware is plumbing, not policy.
# ---------------------------------------------------------------------------

_current_client_ip: ContextVar[str | None] = ContextVar("aslg_client_ip", default=None)


def get_current_client_ip() -> str | None:
    """The resolved client IP for the request being handled, or None outside one."""
    return _current_client_ip.get()


class ClientIPMiddleware:
    """Resolve the client IP once per request and publish it to the ContextVar.

    Deliberately a plain ASGI middleware rather than a Starlette
    `BaseHTTPMiddleware`: BaseHTTPMiddleware runs the downstream application in
    a separate anyio task, which makes ContextVar propagation subtle. A bare
    ASGI callable runs the rest of the stack inline, in this same task, so the
    value is visible to `async def` endpoints directly and to `def` endpoints
    through the copied context Starlette hands its threadpool.

    It is registered first in `main.py` so it ends up innermost — closest to
    the router, and therefore inside anything else that might spawn a task.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        # Imported here rather than at module scope: this module is pure
        # address logic and is unit-tested without Starlette installed.
        from starlette.requests import Request

        token = _current_client_ip.set(client_ip(Request(scope)))
        try:
            await self.app(scope, receive, send)
        finally:
            # Always restore, so a pooled task can never leak one request's
            # address into the next.
            _current_client_ip.reset(token)
