"""Small compatibility gate for admin-only routes."""
from fastapi import Depends, HTTPException

from . import access


def current_admin(scope: access.AccessScope = Depends(access.current_scope)) -> dict:
    if not scope.user_id or not (scope.unrestricted or access.is_admin(scope.user_id)):
        raise HTTPException(status_code=404, detail="not found")
    return {"id": scope.user_id}
