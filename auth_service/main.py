import os
from datetime import datetime, timedelta
from typing import List

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from auth_service.database import get_db
from auth_service import schemas
from scripts.db_init import (
    AuthUser,
    AuthRole,
    AuthPermission,
    AuthRolePermission,
    AuthUserRole,
)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
AUTH_SECRET_KEY = os.getenv("AUTH_SECRET_KEY", "change_this_secret")
AUTH_ALGORITHM = os.getenv("AUTH_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("AUTH_ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
SELF_REGISTER_ROLES = [
    role.strip()
    for role in os.getenv("AUTH_SELF_REGISTER_ROLES", "member").split(",")
    if role.strip()
]

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

app = FastAPI(title="Auth Service")

allowed_origins = os.getenv("AUTH_ALLOWED_ORIGINS", "http://localhost:40145").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in allowed_origins if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, AUTH_SECRET_KEY, algorithm=AUTH_ALGORITHM)


def get_user_by_username(db: Session, username: str) -> AuthUser | None:
    return db.query(AuthUser).filter(AuthUser.username == username).first()


def get_user_permissions(db: Session, user: AuthUser) -> List[str]:
    rows = (
        db.query(AuthPermission.code)
        .join(AuthRolePermission, AuthRolePermission.permission_id == AuthPermission.permission_id)
        .join(AuthRole, AuthRole.role_id == AuthRolePermission.role_id)
        .join(AuthUserRole, AuthUserRole.role_id == AuthRole.role_id)
        .filter(AuthUserRole.user_id == user.user_id)
        .all()
    )
    return sorted({code for (code,) in rows})


def get_user_roles(db: Session, user: AuthUser) -> List[str]:
    rows = (
        db.query(AuthRole.name)
        .join(AuthUserRole, AuthUserRole.role_id == AuthRole.role_id)
        .filter(AuthUserRole.user_id == user.user_id)
        .all()
    )
    return sorted({name for (name,) in rows})


def serialize_user(db: Session, user: AuthUser) -> schemas.UserRead:
    permissions = get_user_permissions(db, user)
    roles = get_user_roles(db, user)
    return schemas.UserRead(
        user_id=user.user_id,
        username=user.username,
        full_name=user.full_name,
        email=user.email,
        permissions=permissions,
        roles=roles,
        is_active=bool(user.is_active),
    )


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> AuthUser:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token inválido o expirado",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, AUTH_SECRET_KEY, algorithms=[AUTH_ALGORITHM])
        username: str = payload.get("username")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    user = get_user_by_username(db, username=username)
    if user is None or not user.is_active:
        raise credentials_exception
    return user


def require_permission(permission_code: str):
    def dependency(user: AuthUser = Depends(get_current_user), db: Session = Depends(get_db)) -> AuthUser:
        perms = set(get_user_permissions(db, user))
        if permission_code not in perms:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permisos insuficientes")
        return user

    return dependency


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.post("/auth/login", response_model=schemas.Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = get_user_by_username(db, form_data.username)
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales inválidas")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Usuario inactivo")
    permissions = get_user_permissions(db, user)
    access_token = create_access_token(
        data={"sub": str(user.user_id), "username": user.username, "permissions": permissions}
    )
    return schemas.Token(
        access_token=access_token,
        permissions=permissions,
        username=user.username,
        user_id=user.user_id,
    )


@app.get("/auth/me", response_model=schemas.UserRead)
def read_me(user: AuthUser = Depends(get_current_user), db: Session = Depends(get_db)):
    return serialize_user(db, user)


@app.post("/auth/register", response_model=schemas.UserRead)
def register_user(
    payload: schemas.UserCreate,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(get_current_user),
):
    # Solo administradores pueden registrar usuarios adicionales
    admin_perms = set(get_user_permissions(db, current_user))
    if "manage_users" not in admin_perms:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo administradores pueden registrar usuarios")
    if get_user_by_username(db, payload.username):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Usuario ya existe")
    hashed_password = get_password_hash(payload.password)
    new_user = AuthUser(
        username=payload.username,
        full_name=payload.full_name,
        email=payload.email,
        hashed_password=hashed_password,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    _sync_user_roles(db, new_user, payload.roles or [])
    return serialize_user(db, new_user)


@app.post("/auth/assign-role")
def assign_roles(
    assignment: schemas.RoleAssignment,
    db: Session = Depends(get_db),
    _: AuthUser = Depends(require_permission("manage_users")),
):
    user = get_user_by_username(db, assignment.username)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")
    _sync_user_roles(db, user, assignment.roles)
    return {"status": "ok", "roles": assignment.roles}


@app.get("/auth/permissions")
def list_permissions(_: AuthUser = Depends(require_permission("manage_users")), db: Session = Depends(get_db)):
    perms = db.query(AuthPermission).order_by(AuthPermission.code).all()
    return {"items": [{"code": p.code, "description": p.description} for p in perms]}


@app.post("/auth/self-register", response_model=schemas.UserRead)
def self_register(payload: schemas.SelfRegisterRequest, db: Session = Depends(get_db)):
    if get_user_by_username(db, payload.username):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Usuario ya existe")
    hashed_password = get_password_hash(payload.password)
    new_user = AuthUser(
        username=payload.username,
        full_name=payload.full_name,
        email=payload.email,
        hashed_password=hashed_password,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    _sync_user_roles(db, new_user, SELF_REGISTER_ROLES)
    return serialize_user(db, new_user)


@app.get("/auth/users", response_model=List[schemas.UserRead])
def list_users(
    _: AuthUser = Depends(require_permission("manage_users")),
    db: Session = Depends(get_db),
):
    users = db.query(AuthUser).order_by(AuthUser.username.asc()).all()
    return [serialize_user(db, user) for user in users]


@app.get("/auth/users/{username}", response_model=schemas.UserRead)
def read_user(
    username: str,
    _: AuthUser = Depends(require_permission("manage_users")),
    db: Session = Depends(get_db),
):
    user = get_user_by_username(db, username)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")
    return serialize_user(db, user)


@app.patch("/auth/users/{username}", response_model=schemas.UserRead)
def update_user(
    username: str,
    payload: schemas.UserUpdate,
    _: AuthUser = Depends(require_permission("manage_users")),
    db: Session = Depends(get_db),
):
    user = get_user_by_username(db, username)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")
    if payload.full_name is not None:
        user.full_name = payload.full_name
    if payload.email is not None:
        user.email = payload.email
    if payload.password:
        user.hashed_password = get_password_hash(payload.password)
    if payload.is_active is not None:
        user.is_active = payload.is_active
    db.add(user)
    db.commit()
    db.refresh(user)
    if payload.roles is not None:
        _sync_user_roles(db, user, payload.roles)
        db.refresh(user)
    return serialize_user(db, user)


@app.delete("/auth/users/{username}")
def delete_user(
    username: str,
    _: AuthUser = Depends(require_permission("manage_users")),
    db: Session = Depends(get_db),
):
    user = get_user_by_username(db, username)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")
    user.is_active = False
    db.add(user)
    db.commit()
    return {"status": "ok"}


def _sync_user_roles(db: Session, user: AuthUser, roles: List[str]) -> None:
    db.query(AuthUserRole).filter(AuthUserRole.user_id == user.user_id).delete()
    if not roles:
        db.commit()
        return
    role_map = {role.name: role.role_id for role in db.query(AuthRole).all()}
    for role_name in roles:
        role_id = role_map.get(role_name)
        if role_id:
            db.add(AuthUserRole(user_id=user.user_id, role_id=role_id))
    db.commit()
