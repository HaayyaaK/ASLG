from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..audit import log_activity
from ..database import get_db
from ..deps import get_current_user
from ..models import Module, RolePermission, User
from ..schemas import LoginRequest, TokenResponse, UserOut
from ..security import create_access_token, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _permissions_for_role(db: Session, role_id: int) -> dict[str, str]:
    rows = (
        db.query(Module.code, RolePermission.access_level)
        .join(RolePermission, RolePermission.module_id == Module.id)
        .filter(RolePermission.role_id == role_id)
        .all()
    )
    return {code: level for code, level in rows}


def _to_user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        name_en=user.name_en,
        name_ar=user.name_ar,
        username=user.username,
        email=user.email,
        occupation=user.occupation,
        role_code=user.role.code,
        civil_id=user.civil_id,
        is_owner=user.is_owner,
        is_active=user.is_active,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
    )


def _issue_token(user: User, db: Session) -> TokenResponse:
    user.last_login_at = datetime.utcnow()
    db.commit()
    token = create_access_token(user.id, user.role.code)
    return TokenResponse(
        access_token=token,
        user=_to_user_out(user),
        permissions=_permissions_for_role(db, user.role_id),
    )


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == payload.username, User.is_active == True).first()  # noqa: E712
    if user is None or not verify_password(payload.password, user.password_hash):
        # Never log which check failed (unknown username vs wrong password) —
        # the attempted username goes in meta, never the password itself.
        log_activity(db, None, "login_failed", meta={"username": payload.username})
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password")
    token = _issue_token(user, db)
    log_activity(db, user.id, "login_success", meta={"role": user.role.code})
    return token


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Tokens are stateless JWTs — there's no server-side session to
    invalidate here. This endpoint exists purely so logout has an audit
    trail; the frontend already discards the token client-side regardless
    of whether this call succeeds."""
    log_activity(db, user.id, "logout")


@router.get("/me", response_model=TokenResponse)
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    token = create_access_token(user.id, user.role.code)
    return TokenResponse(
        access_token=token,
        user=_to_user_out(user),
        permissions=_permissions_for_role(db, user.role_id),
    )
