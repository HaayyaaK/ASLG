from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .database import get_db
from .models import RolePermission, Module, User
from .security import decode_access_token

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    payload = decode_access_token(creds.credentials)
    if payload is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    user = db.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account not found or disabled")
    return user


def require_roles(*allowed_role_codes: str):
    def _check(user: User = Depends(get_current_user)) -> User:
        if user.role.code not in allowed_role_codes:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient role for this action")
        return user

    return _check


def get_permission_level(db: Session, role_id: int, module_code: str) -> str:
    module = db.query(Module).filter(Module.code == module_code).first()
    if module is None:
        return "none"
    rp = (
        db.query(RolePermission)
        .filter(RolePermission.role_id == role_id, RolePermission.module_id == module.id)
        .first()
    )
    return rp.access_level if rp else "none"


def require_module(module_code: str, *acceptable_levels: str):
    def _check(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
        level = get_permission_level(db, user.role_id, module_code)
        if level == "none" or (acceptable_levels and level not in acceptable_levels):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"No access to '{module_code}'")
        return user

    return _check
