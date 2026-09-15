"""System-wide activity/audit log.

Reuses the `audit_log` table that already existed in models.py/schema.sql —
designed for exactly this (its comment in schema.sql literally lists
"login, logout, case_update, document_upload, ..." as example actions) but
never wired up to anything. This module is the wiring, not a new store.

Logging is best-effort and never blocks the request it's attached to: it
runs after the caller's own commit, in its own try/except, so a transient
audit-write failure degrades to "no audit row" rather than failing the
actual user-create/document-upload/etc. it's describing.
"""

import logging

from sqlalchemy.orm import Session

from .client_ip import get_current_client_ip
from .models import AuditLog

logger = logging.getLogger("aslg.audit")

# Distinguishes "caller said nothing about the IP" (use the request context)
# from "caller explicitly said there is no IP" (store NULL). A plain None
# default could not tell those apart.
_FROM_REQUEST_CONTEXT = object()


def log_activity(
    db: Session,
    user_id: int | None,
    action: str,
    *,
    entity_type: str | None = None,
    entity_id: int | None = None,
    meta: dict | None = None,
    ip_address: str | None = _FROM_REQUEST_CONTEXT,  # type: ignore[assignment]
) -> None:
    """Write one audit row.

    The client IP is filled in automatically from the request context set by
    `client_ip.ClientIPMiddleware`, so every audited action performed through a
    real HTTP request carries the address it came from without any router
    having to ask for it. Anything invoked outside a request — a management
    script, a future scheduled job — gets None and stores NULL, which is the
    honest answer: there was no client. The server's own address is never
    substituted for a missing client address.

    Pass `ip_address=` explicitly only to override that, which no caller
    currently needs to do.
    """
    if ip_address is _FROM_REQUEST_CONTEXT:
        ip_address = get_current_client_ip()
    try:
        db.add(
            AuditLog(
                user_id=user_id,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                meta_json=meta,
                ip_address=ip_address,
            )
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Failed to write audit log entry (action=%s)", action)
