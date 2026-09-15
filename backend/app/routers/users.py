from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..audit import log_activity
from ..database import get_db
from ..deps import require_roles
from ..models import Role, User
from ..schemas import (
    BulkUserActionRequest,
    PasswordResetRequest,
    UserCreateRequest,
    UserOut,
    UserUpdateRequest,
)
from ..security import hash_password

router = APIRouter(prefix="/api/users", tags=["users"], dependencies=[Depends(require_roles("Admin"))])


def _to_out(u: User) -> UserOut:
    return UserOut(
        id=u.id, name_en=u.name_en, name_ar=u.name_ar, username=u.username, email=u.email,
        occupation=u.occupation, role_code=u.role.code, civil_id=u.civil_id, is_owner=u.is_owner,
        is_active=u.is_active, last_login_at=u.last_login_at, created_at=u.created_at,
    )


def _role_id(db: Session, code: str) -> int:
    role = db.query(Role).filter(Role.code == code).first()
    if role is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown role '{code}'")
    return role.id


@router.get("", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db)):
    return [_to_out(u) for u in db.query(User).order_by(User.id).all()]


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(payload: UserCreateRequest, current: User = Depends(require_roles("Admin")), db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == payload.username).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Username already exists")
    user = User(
        name_en=payload.name_en, name_ar=payload.name_ar, username=payload.username,
        email=payload.email, occupation=payload.occupation, role_id=_role_id(db, payload.role_code),
        civil_id=payload.civil_id, is_owner=payload.is_owner, password_hash=hash_password(payload.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    log_activity(
        db, current.id, "user_create", entity_type="user", entity_id=user.id,
        meta={"username": user.username, "role": payload.role_code},
    )
    return _to_out(user)


@router.put("/{user_id}", response_model=UserOut)
def update_user(user_id: int, payload: UserUpdateRequest, current: User = Depends(require_roles("Admin")), db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    data = payload.model_dump(exclude_unset=True)
    if "role_code" in data:
        user.role_id = _role_id(db, data.pop("role_code"))
    for field, value in data.items():
        setattr(user, field, value)
    db.commit()
    db.refresh(user)
    # Field NAMES only — never the new values themselves (e.g. email/civil_id
    # changes shouldn't get echoed into the audit trail as free text).
    changed = list(payload.model_dump(exclude_unset=True).keys())
    log_activity(db, current.id, "user_update", entity_type="user", entity_id=user.id, meta={"fields_changed": changed})
    return _to_out(user)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: int, current: User = Depends(require_roles("Admin")), db: Session = Depends(get_db)):
    if user_id == current.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot delete your own account")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    username = user.username
    db.delete(user)
    db.commit()
    log_activity(db, current.id, "user_delete", entity_type="user", entity_id=user_id, meta={"username": username})


@router.post("/{user_id}/reset-password", status_code=status.HTTP_204_NO_CONTENT)
def reset_password(user_id: int, payload: PasswordResetRequest, current: User = Depends(require_roles("Admin")), db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    user.password_hash = hash_password(payload.new_password)
    db.commit()
    # Never the new password itself — just that a reset happened, and to whom.
    log_activity(db, current.id, "password_reset", entity_type="user", entity_id=user_id)


@router.post("/bulk", response_model=list[UserOut])
def bulk_action(payload: BulkUserActionRequest, current: User = Depends(require_roles("Admin")), db: Session = Depends(get_db)):
    if current.id in payload.user_ids and payload.action == "deactivate":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot deactivate your own account")
    users = db.query(User).filter(User.id.in_(payload.user_ids)).all()
    if payload.action == "activate":
        for u in users:
            u.is_active = True
    elif payload.action == "deactivate":
        for u in users:
            u.is_active = False
    elif payload.action == "reset_password":
        if not payload.new_password:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "new_password is required for bulk reset")
        for u in users:
            u.password_hash = hash_password(payload.new_password)
    else:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown bulk action '{payload.action}'")
    db.commit()
    log_activity(
        db, current.id, f"user_bulk_{payload.action}",
        meta={"user_ids": payload.user_ids, "count": len(users)},
    )
    return [_to_out(u) for u in users]
