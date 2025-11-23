import os
from typing import Callable, List, Optional

from fastapi import Cookie, Depends, Header, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from pydantic import BaseModel, ValidationError

AUTH_SECRET_KEY = os.getenv("AUTH_SECRET_KEY", "change_this_secret")
AUTH_ALGORITHM = os.getenv("AUTH_ALGORITHM", "HS256")
AUTH_TOKEN_URL = os.getenv("AUTH_TOKEN_URL", "http://localhost:40155/auth/login")

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=AUTH_TOKEN_URL, auto_error=False)


class TokenPayload(BaseModel):
    user_id: int
    username: str
    permissions: List[str] = []


def decode_token(token: str) -> TokenPayload:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token inválido o expirado",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, AUTH_SECRET_KEY, algorithms=[AUTH_ALGORITHM])
        user_id = payload.get("sub")
        username = payload.get("username")
        permissions = payload.get("permissions") or []
        if user_id is None or username is None:
            raise credentials_exception
        return TokenPayload(user_id=int(user_id), username=username, permissions=permissions)
    except (JWTError, ValidationError, ValueError):
        raise credentials_exception

def _extract_token_from_header(header_value: Optional[str]) -> Optional[str]:
    if not header_value:
        return None
    header_value = header_value.strip()
    if not header_value.lower().startswith("bearer "):
        return None
    return header_value.split(" ", 1)[1].strip() or None


def _select_token(
    token: Optional[str],
    authorization: Optional[str],
    cookie_token: Optional[str],
) -> Optional[str]:
    return token or _extract_token_from_header(authorization) or cookie_token


def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
    authorization: Optional[str] = Header(default=None),
    cookie_token: Optional[str] = Cookie(default=None, alias="lpm_token"),
) -> TokenPayload:
    selected = _select_token(token, authorization, cookie_token)
    if not selected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return decode_token(selected)


def get_token_from_request(request: Request) -> Optional[str]:
    return _select_token(
        token=None,
        authorization=request.headers.get("Authorization"),
        cookie_token=request.cookies.get("lpm_token"),
    )


def require_permissions(required_permissions: List[str]) -> Callable:
    def dependency(current_user: TokenPayload = Depends(get_current_user)) -> TokenPayload:
        if not set(required_permissions).issubset(set(current_user.permissions)):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tiene permisos suficientes para esta operación",
            )
        return current_user

    return dependency
