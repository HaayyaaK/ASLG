import csv
import io
import json

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from ..deps import require_roles
from ..models import AuditLog, User
from ..schemas import AuditLogOut

# Router-level dependency (same pattern as users.py): every route here is
# Admin-only, enforced server-side regardless of what the frontend shows or
# hides — the frontend nav entry is just a convenience, not the boundary.
router = APIRouter(prefix="/api/activity-log", tags=["activity-log"], dependencies=[Depends(require_roles("Admin"))])

EXPORT_ROW_LIMIT = 5000
LIST_ROW_LIMIT = 200


def _to_out(row: AuditLog) -> AuditLogOut:
    return AuditLogOut(
        id=row.id,
        user_id=row.user_id,
        user_name_ar=row.user.name_ar if row.user else None,
        user_name_en=row.user.name_en if row.user else None,
        action=row.action,
        entity_type=row.entity_type,
        entity_id=row.entity_id,
        meta=row.meta_json,
        ip_address=row.ip_address,
        created_at=row.created_at,
    )


def _query(db: Session, limit: int):
    return (
        db.query(AuditLog)
        .options(joinedload(AuditLog.user))
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(limit)
        .all()
    )


@router.get("", response_model=list[AuditLogOut])
def list_activity(limit: int = Query(LIST_ROW_LIMIT, ge=1, le=LIST_ROW_LIMIT), db: Session = Depends(get_db)):
    return [_to_out(r) for r in _query(db, limit)]


@router.get("/export")
def export_activity(db: Session = Depends(get_db)):
    rows = _query(db, EXPORT_ROW_LIMIT)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["timestamp_utc", "user", "action", "entity_type", "entity_id", "ip_address", "meta"])
    for r in rows:
        user_label = r.user.name_en if r.user else (f"user#{r.user_id}" if r.user_id else "—")
        writer.writerow([
            r.created_at.isoformat(),
            user_label,
            r.action,
            r.entity_type or "",
            r.entity_id if r.entity_id is not None else "",
            r.ip_address or "",
            json.dumps(r.meta_json, ensure_ascii=False) if r.meta_json else "",
        ])
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=activity-log.csv"},
    )
