from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..escalation import run_reminder_escalations
from ..models import Notification, User
from ..schemas import NotificationOut

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


def _scope(db: Session, user: User):
    return db.query(Notification).filter(
        or_(Notification.user_id == user.id, Notification.target_role_id == user.role_id)
    )


@router.get("", response_model=list[NotificationOut])
def list_notifications(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    run_reminder_escalations(db)
    rows = _scope(db, user).order_by(Notification.created_at.desc()).all()
    return [NotificationOut.model_validate(n) for n in rows]


@router.put("/{notif_id}/read", status_code=status.HTTP_204_NO_CONTENT)
def mark_read(notif_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    notif = _scope(db, user).filter(Notification.id == notif_id).first()
    if notif is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notification not found")
    notif.is_read = True
    db.commit()


@router.put("/read-all", status_code=status.HTTP_204_NO_CONTENT)
def mark_all_read(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _scope(db, user).update({Notification.is_read: True}, synchronize_session=False)
    db.commit()
