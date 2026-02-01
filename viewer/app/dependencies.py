from fastapi import Cookie, HTTPException, Request
from fastapi.responses import RedirectResponse

from .auth import COOKIE_NAME, verify_token


def get_current_user_api(paperflow_token: str | None = Cookie(None)) -> str:
    """Dependency for API routes - returns 401 if unauthenticated."""
    if not paperflow_token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    username = verify_token(paperflow_token)
    if not username:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return username


def get_current_user_page(request: Request) -> str | None:
    """Dependency for page routes - returns None if unauthenticated."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    return verify_token(token)
