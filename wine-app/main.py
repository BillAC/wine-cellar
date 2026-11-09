import os
import signal
import uuid
import asyncio
import threading
import shutil
from io import BytesIO
from datetime import date, datetime, timezone
from typing import List, Optional
import secrets
import re

from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session, joinedload, selectinload
from sqlalchemy import func
from PIL import Image, UnidentifiedImageError

import models
import crud
import auth
from database import engine, get_db, migrate_wine_metadata_columns, init_admin_user, SessionLocal
from enrichment_service import WineEnrichmentService
from vision_service import VisionService
from email_service import EmailService
from pydantic import BaseModel, ConfigDict, Field, model_validator

import logging.config
import mimetypes
from sqlalchemy.exc import IntegrityError
from urllib.parse import parse_qs, unquote, urlparse
from env_settings import APP_DIR, get_settings, load_app_env
import generate_labels
import zxingcpp

LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "()": "uvicorn.logging.DefaultFormatter",
            "fmt": "%(levelprefix)s %(message)s",
            "use_colors": None,
        },
        "access": {
            "()": "uvicorn.logging.AccessFormatter",
            "fmt": '%(asctime)s %(client_addr)s - "%(request_line)s" %(status_code)s',
        },
    },
    "handlers": {
        "default": {
            "formatter": "default",
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stderr",
        },
        "access": {
            "formatter": "access",
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
        },
    },
    "loggers": {
        "uvicorn": {"handlers": ["default"], "level": "INFO"},
        "uvicorn.error": {"level": "INFO"},
        "uvicorn.access": {"handlers": ["access"], "level": "INFO", "propagate": False},
    },
}

logging.config.dictConfig(LOGGING_CONFIG)
logging.getLogger("test").info("test startup message")

load_app_env()
auth.validate_configuration()

# Create all tables on startup
models.Base.metadata.create_all(bind=engine)
migrate_wine_metadata_columns(engine)
init_admin_user(engine)

app = FastAPI(title="The Local AI Wine Hub 🍷")
enricher = WineEnrichmentService()
vision = VisionService()
mailer = EmailService()

STATIC_DIR = os.path.join(APP_DIR, "static")
WINE_LABELS_DIR = get_settings().wine_labels_dir
UPLOAD_DIR = WINE_LABELS_DIR  # Kept as alias for backwards compatibility
MAX_LABEL_SIZE_BYTES = get_settings().max_label_size_mb * 1024 * 1024
os.makedirs(WINE_LABELS_DIR, exist_ok=True)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.middleware("http")
async def protect_cellar_api(request: Request, call_next):
    path = request.url.path
    method = request.method

    if (
        method == "GET"
        and path.startswith("/wines/")
        and path != "/wines/"
        and "/" not in path[len("/wines/"):]
        and "text/html" in request.headers.get("accept", "")
    ):
        response = FileResponse(os.path.join(STATIC_DIR, "index.html"))
        response.headers["Cache-Control"] = "no-cache"
        return response

    protected_path = any(
        path == prefix or path.startswith(f"{prefix}/")
        for prefix in (
            "/wines",
            "/locations",
            "/enrichment",
            "/grapeminds",
            "/admin",
            "/wine-labels",
            "/uploads",
            "/auth/logout",
            "/auth/change-password",
        )
    )
    if protected_path:
        session_data = auth.decode_session_token(request.cookies.get(auth.SESSION_COOKIE))
        if not session_data:
            return JSONResponse(status_code=401, content={"detail": "Sign-in required."})

        is_admin = session_data.get("role") == "admin"
        is_admin_endpoint = (
            path == "/admin"
            or path.startswith("/admin/")
            or (path.startswith("/wines/") and method == "DELETE")
            or path == "/wines/batch"
            or path == "/wines/batch/delete"
            or (path.startswith("/locations") and method in {"POST", "PUT", "PATCH", "DELETE"})
        )
        if is_admin_endpoint and not is_admin:
            return JSONResponse(status_code=403, content={"detail": "Admin privileges required."})

    if (
        protected_path
        and method in {"POST", "PUT", "PATCH", "DELETE"}
        and request.headers.get("X-Requested-With") != "WineCellar"
    ):
        return JSONResponse(
            status_code=403,
            content={"detail": "Invalid request origin."},
        )
    response = await call_next(request)
    if path == "/" or path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


# --- Pydantic Schemas ---

class LocationBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    sub_location: Optional[str] = Field(default=None, max_length=120)
    parent_location_id: Optional[int] = None


class LocationUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    sub_location: Optional[str] = Field(default=None, max_length=120)


class LocationResponse(LocationBase):
    id: int
    model_config = ConfigDict(from_attributes=True)


class TastingNoteBase(BaseModel):
    notes: Optional[str] = None
    tasting_date: Optional[date] = None
    tannin: float = 0.5
    acidity: float = 0.5
    body: float = 0.5
    alcohol: float = 0.5
    fruit_intensity: float = 0.5
    aroma_tags: Optional[str] = None
    author_name: Optional[str] = None


class TastingNoteResponse(TastingNoteBase):
    id: int
    wine_entry_id: int
    model_config = ConfigDict(from_attributes=True)


class WineRemovalRequest(BaseModel):
    status: models.WineStatus = models.WineStatus.REMOVED
    checkout_date: Optional[date] = None
    comment: Optional[str] = Field(default=None, max_length=1000)
    pairing: Optional[dict | str] = None
    grapeminds_tasting_notes: Optional[dict | str] = None
    apply_to_group_qr_ids: Optional[List[str]] = None
    tasting_note: Optional[TastingNoteBase] = None


class WineBase(BaseModel):
    qr_id: str
    grapeminds_id: Optional[str] = Field(default=None, max_length=64)
    name: Optional[str] = None
    vintage: Optional[int] = None
    winery: Optional[str] = None
    region: Optional[str] = None
    country_of_origin: Optional[str] = None
    grape_type: Optional[str] = None
    color: Optional[str] = None
    grape_varieties: Optional[List[dict | str]] = None
    description: Optional[dict | str] = None
    pairing: Optional[dict | str] = None
    grapeminds_tasting_notes: Optional[dict | str] = None
    flavor_profile: Optional[dict] = None
    comment: Optional[str] = Field(default=None, max_length=1000)
    location_id: Optional[int] = None
    photo_path: Optional[str] = None
    purchase_date: Optional[date] = None
    checkout_date: Optional[date] = None
    drink_from: Optional[int] = Field(default=None, ge=1800, le=2200)
    drink_until: Optional[int] = Field(default=None, ge=1800, le=2200)
    purchase_price: Optional[float] = None
    market_price: Optional[float] = None
    is_verified: bool = False

    @model_validator(mode="after")
    def validate_drinking_window(self):
        if (
            self.drink_from is not None
            and self.drink_until is not None
            and self.drink_until < self.drink_from
        ):
            raise ValueError("drink_until cannot be earlier than drink_from.")
        return self


class WineCreate(WineBase):
    pass


class WineUpdate(BaseModel):
    grapeminds_id: Optional[str] = None
    name: Optional[str] = None
    vintage: Optional[int] = None
    winery: Optional[str] = None
    region: Optional[str] = None
    country_of_origin: Optional[str] = None
    grape_type: Optional[str] = None
    color: Optional[str] = None
    grape_varieties: Optional[List[dict | str]] = None
    description: Optional[dict | str] = None
    pairing: Optional[dict | str] = None
    grapeminds_tasting_notes: Optional[dict | str] = None
    flavor_profile: Optional[dict] = None
    comment: Optional[str] = Field(default=None, max_length=1000)
    location_id: Optional[int] = None
    purchase_date: Optional[date] = None
    checkout_date: Optional[date] = None
    drink_from: Optional[int] = Field(default=None, ge=1800, le=2200)
    drink_until: Optional[int] = Field(default=None, ge=1800, le=2200)
    purchase_price: Optional[float] = None
    market_price: Optional[float] = None

    @model_validator(mode="after")
    def validate_drinking_window(self):
        if (
            self.drink_from is not None
            and self.drink_until is not None
            and self.drink_until < self.drink_from
        ):
            raise ValueError("drink_until cannot be earlier than drink_from.")
        return self


class WineBatchUpdate(BaseModel):
    qr_ids: List[str] = Field(min_length=1, max_length=100)
    updates: WineUpdate
    force_move: bool = False


class WineBatchDelete(BaseModel):
    qr_ids: List[str] = Field(min_length=1, max_length=100)


class WineBatchCreate(BaseModel):
    wines: List[WineCreate] = Field(min_length=1, max_length=100)


class WineResponse(WineBase):
    id: int
    status: models.WineStatus
    created_at: datetime
    tasting_notes: List[TastingNoteResponse] = []
    location: Optional[LocationResponse] = None
    model_config = ConfigDict(from_attributes=True)


class GrapemindsLookupRequest(BaseModel):
    grapeminds_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_:-]+$")


class WineEnrichmentLookupResponse(BaseModel):
    status: str
    metadata: Optional[dict] = None


class GrapemindsApplyRequest(BaseModel):
    grapeminds_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_:-]+$")
    selected_fields: List[str] = Field(default_factory=list)
    metadata: dict


GRAPEMINDS_APPLY_FIELDS = {
    "name",
    "winery",
    "vintage",
    "region",
    "country_of_origin",
    "grape_type",
    "color",
    "grape_varieties",
    "description",
    "pairing",
    "grapeminds_tasting_notes",
    "flavor_profile",
    "market_price",
}


class WineDraftResponse(BaseModel):
    """Label scan suggestions; nothing is saved until the user confirms."""
    qr_id: str
    photo_path: str
    vision_extraction: dict
    enrichment_metadata: Optional[dict] = None
    enrichment_status: str
    suggested_fields: dict
    grapeminds_id: Optional[str] = None


class LoginRequest(BaseModel):
    username: str
    password: str


class RestartResponse(BaseModel):
    status: str
    message: str


class UserRequestAccess(BaseModel):
    username: str = Field(min_length=3, max_length=30, pattern=r"^[A-Za-z0-9_.-]+$")
    email: str = Field(min_length=5, max_length=255)
    password: Optional[str] = Field(default=None, min_length=8)


class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    role: models.UserRole
    status: models.UserStatus
    created_at: Optional[datetime] = None
    approved_at: Optional[datetime] = None
    last_login: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)


class UserStatusUpdate(BaseModel):
    status: models.UserStatus


class UserRoleUpdate(BaseModel):
    role: models.UserRole


class ForgotPasswordRequest(BaseModel):
    identifier: str = Field(min_length=3, max_length=255)


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=16, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


class LabelGenerateRequest(BaseModel):
    starting_label: str = Field(min_length=1, max_length=64)
    force: bool = False


class LabelCheckRequest(BaseModel):
    starting_label: str = Field(min_length=1, max_length=64)


class LabelCheckResponse(BaseModel):
    starting_label: str
    first_label: str
    last_label: str
    total_count: int
    prefix: str
    start_number: int
    end_number: int
    conflicts: List[int]
    has_conflicts: bool


class LabelInfoResponse(BaseModel):
    template: str
    label_count: int
    dimensions: str
    sheet_size: str
    next_starting_label: str
    columns: int
    rows: int


# --- Endpoints ---

@app.get("/")
def read_root():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.post("/auth/login")
def login(credentials: LoginRequest, db: Session = Depends(get_db)):
    settings = get_settings()
    configured_username = settings.cellar_username
    configured_password = settings.cellar_password

    role = "user"
    authenticated_username = credentials.username.strip()

    # Check root admin credentials from environment first
    if secrets.compare_digest(credentials.username, configured_username) and secrets.compare_digest(
        credentials.password, configured_password
    ):
        role = "admin"
        authenticated_username = configured_username
    else:
        # Check database user records
        user_obj = crud.get_user_by_username_or_email(db, credentials.username)
        if not user_obj:
            raise HTTPException(status_code=401, detail="Incorrect username or password.")

        if user_obj.status == models.UserStatus.PENDING:
            raise HTTPException(
                status_code=403,
                detail="Your access request is currently pending approval by the cellar administrator.",
            )
        if user_obj.status == models.UserStatus.REJECTED:
            raise HTTPException(
                status_code=403,
                detail="Your access request was declined.",
            )
        if user_obj.status == models.UserStatus.DISABLED:
            raise HTTPException(
                status_code=403,
                detail="Your account has been deactivated. Please contact the administrator.",
            )

        if not auth.verify_password(credentials.password, user_obj.hashed_password):
            raise HTTPException(status_code=401, detail="Incorrect username or password.")

        role = user_obj.role.value
        authenticated_username = user_obj.username
        user_obj.last_login = datetime.now(timezone.utc)
        db.commit()

    token = auth.create_session_token(username=authenticated_username, role=role)
    response = JSONResponse({
        "authenticated": True,
        "username": authenticated_username,
        "role": role,
    })
    response.set_cookie(
        key=auth.SESSION_COOKIE,
        value=token,
        max_age=auth.session_ttl_seconds(),
        httponly=True,
        secure=auth.secure_cookie_enabled(),
        samesite="strict",
        path="/",
    )
    return response


@app.post("/auth/logout")
def logout():
    response = JSONResponse({"authenticated": False})
    response.delete_cookie(
        key=auth.SESSION_COOKIE,
        httponly=True,
        secure=auth.secure_cookie_enabled(),
        samesite="strict",
        path="/",
    )
    return response


@app.get("/auth/session")
def session_status(request: Request, db: Session = Depends(get_db)):
    session_data = auth.decode_session_token(request.cookies.get(auth.SESSION_COOKIE))
    if not session_data:
        return {"authenticated": False}

    username = session_data["username"]
    role = session_data.get("role", "user")

    if username.lower() == get_settings().cellar_username.lower():
        user = crud.get_user_by_username_or_email(db, username)
        email = user.email if user else f"{username}@local"
        return {
            "authenticated": True,
            "username": username,
            "email": email,
            "role": "admin",
        }

    user = crud.get_user_by_username_or_email(db, username)
    if not user or user.status != models.UserStatus.APPROVED:
        return {"authenticated": False}

    return {
        "authenticated": True,
        "username": user.username,
        "email": user.email,
        "role": user.role.value,
    }


@app.post("/auth/request-access", status_code=201)
def request_access_endpoint(request_data: UserRequestAccess, db: Session = Depends(get_db)):
    username = request_data.username.strip()
    email = request_data.email.strip().lower()

    if "@" not in email or "." not in email:
        raise HTTPException(status_code=422, detail="Please provide a valid email address.")

    if username.lower() == get_settings().cellar_username.lower():
        raise HTTPException(status_code=409, detail="That username is reserved.")

    existing_user = (
        db.query(models.User)
        .filter(
            (func.lower(models.User.username) == username.lower())
            | (func.lower(models.User.email) == email)
        )
        .first()
    )
    if existing_user:
        if existing_user.username.lower() == username.lower():
            raise HTTPException(status_code=409, detail="That username is already taken.")
        raise HTTPException(
            status_code=409,
            detail="An account or pending request with that email address already exists.",
        )

    user = crud.create_user_request(
        db,
        username=username,
        email=email,
        password=request_data.password,
    )
    return {
        "status": "pending",
        "message": "Access request submitted successfully. You will receive an email once approved by the administrator.",
        "username": user.username,
    }


@app.post("/auth/forgot-password")
def forgot_password_endpoint(request_data: ForgotPasswordRequest, db: Session = Depends(get_db)):
    identifier = request_data.identifier.strip().lower()
    user = crud.get_user_by_username_or_email(db, identifier)
    if user and user.status == models.UserStatus.APPROVED:
        token_record = crud.create_password_reset_token(
            db, user.id, ttl_hours=get_settings().password_reset_ttl_hours
        )
        mailer.send_password_reset_email(user.email, user.username, token_record.token)

    return {
        "message": "If an account matching that username or email exists, a password reset link has been sent to the email address on file."
    }


@app.post("/auth/reset-password")
def reset_password_endpoint(request_data: ResetPasswordRequest, db: Session = Depends(get_db)):
    token_record = crud.get_valid_reset_token(db, request_data.token.strip())
    if not token_record:
        raise HTTPException(status_code=400, detail="This reset link is invalid or has expired.")

    crud.reset_password_with_token(db, token_record, request_data.new_password)
    return {"message": "Password updated successfully. You can now sign in with your new password."}


@app.post("/auth/change-password")
def change_password_endpoint(
    request_data: ChangePasswordRequest, request: Request, db: Session = Depends(get_db)
):
    session_data = auth.decode_session_token(request.cookies.get(auth.SESSION_COOKIE))
    if not session_data:
        raise HTTPException(status_code=401, detail="Sign-in required.")

    username = session_data["username"]
    user = crud.get_user_by_username_or_email(db, username)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    valid_current = auth.verify_password(request_data.current_password, user.hashed_password)
    if not valid_current:
        # Also check env password if root admin
        settings = get_settings()
        if username.lower() == settings.cellar_username.lower() and secrets.compare_digest(
            request_data.current_password, settings.cellar_password
        ):
            valid_current = True

    if not valid_current:
        raise HTTPException(status_code=400, detail="Incorrect current password.")

    user.hashed_password = auth.hash_password(request_data.new_password)
    db.commit()
    return {"message": "Password changed successfully."}


# --- Admin User Management Endpoints ---

@app.get("/admin/users", response_model=List[UserResponse])
def list_users_endpoint(
    status: Optional[models.UserStatus] = None,
    db: Session = Depends(get_db),
):
    """List cellar users, optionally filtered by status (pending, approved, etc.)."""
    return crud.list_users(db, status=status)


@app.post("/admin/users/{user_id}/approve", response_model=UserResponse)
def approve_user_endpoint(user_id: int, db: Session = Depends(get_db)):
    """Approve a pending user access request and email them an activation/confirmation link."""
    user = crud.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    if user.status == models.UserStatus.APPROVED:
        return user

    token = None
    if not user.hashed_password:
        token_record = crud.create_password_reset_token(
            db, user.id, ttl_hours=get_settings().account_activation_ttl_hours
        )
        token = token_record.token

    crud.approve_user(db, user)
    mailer.send_approval_email(user.email, user.username, reset_token=token)
    return user


@app.post("/admin/users/{user_id}/reject", response_model=UserResponse)
def reject_user_endpoint(user_id: int, db: Session = Depends(get_db)):
    """Reject a pending user access request."""
    user = crud.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    if user.username.lower() == get_settings().cellar_username.lower():
        raise HTTPException(status_code=400, detail="Cannot reject the root admin account.")
    return crud.reject_user(db, user)


@app.patch("/admin/users/{user_id}/status", response_model=UserResponse)
def update_user_status_endpoint(
    user_id: int, update: UserStatusUpdate, request: Request, db: Session = Depends(get_db)
):
    """Enable or disable an existing user account."""
    user = crud.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    session_data = auth.decode_session_token(request.cookies.get(auth.SESSION_COOKIE))
    if session_data and session_data.get("username", "").lower() == user.username.lower():
        raise HTTPException(status_code=400, detail="You cannot modify your own account status.")
    if user.username.lower() == get_settings().cellar_username.lower():
        raise HTTPException(status_code=400, detail="Cannot change status of the root admin account.")
    return crud.update_user_status(db, user, update.status)


@app.patch("/admin/users/{user_id}/role", response_model=UserResponse)
def update_user_role_endpoint(
    user_id: int, update: UserRoleUpdate, request: Request, db: Session = Depends(get_db)
):
    """Promote or demote a user's role (admin vs user)."""
    user = crud.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    session_data = auth.decode_session_token(request.cookies.get(auth.SESSION_COOKIE))
    if session_data and session_data.get("username", "").lower() == user.username.lower():
        raise HTTPException(status_code=400, detail="You cannot modify your own role.")
    if user.username.lower() == get_settings().cellar_username.lower():
        raise HTTPException(status_code=400, detail="Cannot demote the root admin account.")
    return crud.update_user_role(db, user, update.role)


@app.delete("/admin/users/{user_id}", status_code=204)
def delete_user_endpoint(user_id: int, request: Request, db: Session = Depends(get_db)):
    """Permanently delete a user account."""
    user = crud.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    session_data = auth.decode_session_token(request.cookies.get(auth.SESSION_COOKIE))
    if session_data and session_data.get("username", "").lower() == user.username.lower():
        raise HTTPException(status_code=400, detail="You cannot delete your own account.")
    if user.username.lower() == get_settings().cellar_username.lower():
        raise HTTPException(status_code=400, detail="Cannot delete the root admin account.")
    crud.delete_user(db, user)


@app.post("/admin/restart", response_model=RestartResponse, status_code=202)
def restart_server():
    """Ask systemd to restart this server by exiting under Restart=always."""
    if os.getenv("WINE_APP_SUPERVISED") != "systemd":
        raise HTTPException(
            status_code=503,
            detail="Server restart is available only when managed by the wine-app user service.",
        )

    def stop_for_supervised_restart():
        os.kill(os.getpid(), signal.SIGTERM)

    timer = threading.Timer(2.0, stop_for_supervised_restart)
    timer.daemon = True
    timer.start()
    return RestartResponse(
        status="restarting",
        message="The cellar service is restarting. Reconnect in a few seconds.",
    )


def clean_orphan_label_file(photo_filename: str):
    """Deletes an image file from wine-labels (or legacy uploads) if no longer needed."""
    if not photo_filename:
        return
    filename = os.path.basename(photo_filename.strip())
    for folder in (WINE_LABELS_DIR, os.path.join(APP_DIR, "uploads")):
        if os.path.isdir(folder):
            target = os.path.join(folder, filename)
            if os.path.isfile(target):
                try:
                    os.remove(target)
                    logging.info("Housekeeping: Removed orphaned label image %s from %s", filename, folder)
                except OSError as e:
                    logging.warning("Could not remove orphaned label %s: %s", filename, e)


def sync_wine_labels_housekeeping(db: Session, labels_dir: str = None) -> dict:
    """
    Housekeeping: Syncs database with the wine-labels directory.
    - Ensures wine-labels/ directory exists.
    - Migrates any legacy files from uploads/ into wine-labels/.
    - Collects all photo_path filenames referenced in WineEntry.
    - Deletes all unreferenced files from wine-labels/ (and uploads/ if present).
    - If uploads/ was a separate directory, links it to wine-labels/ for compatibility.
    """
    target_dir = labels_dir or WINE_LABELS_DIR
    os.makedirs(target_dir, exist_ok=True)
    legacy_dir = os.path.join(APP_DIR, "uploads") if labels_dir is None else None

    # 1. Query all referenced photo filenames in the database
    db_rows = db.query(models.WineEntry.photo_path).filter(
        models.WineEntry.photo_path.isnot(None)
    ).all()
    referenced_filenames = {
        os.path.basename(row[0].strip())
        for row in db_rows
        if row[0] and row[0].strip()
    }

    # 2. Migrate any referenced files from legacy uploads/ into wine-labels/
    if legacy_dir and target_dir != legacy_dir and os.path.isdir(legacy_dir) and not os.path.islink(legacy_dir):
        for fname in os.listdir(legacy_dir):
            src = os.path.join(legacy_dir, fname)
            dst = os.path.join(target_dir, fname)
            if os.path.isfile(src) and fname in referenced_filenames:
                if not os.path.exists(dst):
                    try:
                        shutil.copy2(src, dst)
                    except OSError:
                        pass

    # 3. Prune files in target_dir not referenced by DB
    disk_files = [
        f for f in os.listdir(target_dir)
        if os.path.isfile(os.path.join(target_dir, f)) and not f.startswith(".")
    ]
    pruned = []
    retained = []
    for filename in disk_files:
        if filename not in referenced_filenames:
            try:
                os.remove(os.path.join(target_dir, filename))
                pruned.append(filename)
            except OSError as e:
                logging.warning("Failed to prune orphan label %s: %s", filename, e)
        else:
            retained.append(filename)

    # 4. Clean up legacy uploads directory and replace with symlink if applicable
    if legacy_dir and target_dir != legacy_dir and os.path.isdir(legacy_dir) and not os.path.islink(legacy_dir):
        for fname in os.listdir(legacy_dir):
            target = os.path.join(legacy_dir, fname)
            if os.path.isfile(target) or os.path.islink(target):
                try:
                    os.remove(target)
                except OSError:
                    pass
        try:
            os.rmdir(legacy_dir)
            os.symlink(os.path.basename(target_dir), legacy_dir)
            logging.info("Housekeeping: Replaced legacy uploads directory with symlink to %s", os.path.basename(target_dir))
        except OSError as e:
            logging.warning("Housekeeping: Could not symlink legacy uploads directory: %s", e)

    logging.info(
        "Housekeeping complete: %d labels kept, %d orphan files pruned.",
        len(retained),
        len(pruned),
    )
    return {
        "retained": sorted(retained),
        "pruned": sorted(pruned),
        "retained_count": len(retained),
        "pruned_count": len(pruned),
    }


@app.on_event("startup")
def on_startup():
    db = SessionLocal()
    try:
        sync_wine_labels_housekeeping(db)
    except Exception as e:
        logging.warning("Housekeeping on startup encountered an error: %s", e)
    finally:
        db.close()


@app.get("/wine-labels/{filename}")
def get_wine_label(filename: str):
    if os.path.basename(filename) != filename:
        raise HTTPException(status_code=404, detail="Image not found.")
    target_dir = UPLOAD_DIR
    image_path = os.path.join(target_dir, filename)
    if not os.path.isfile(image_path):
        legacy_path = os.path.join(APP_DIR, "uploads", filename)
        if os.path.isfile(legacy_path):
            image_path = legacy_path
        else:
            raise HTTPException(status_code=404, detail="Image not found.")
    media_type = mimetypes.guess_type(filename)[0]
    return FileResponse(image_path, media_type=media_type)


@app.get("/uploads/{filename}")
def get_uploaded_label_legacy(filename: str):
    return get_wine_label(filename)


@app.post("/admin/housekeeping/sync-labels")
def admin_sync_labels_endpoint(
    db: Session = Depends(get_db),
    http_request: Request = None,
):
    """Sync wine-labels directory with the database by pruning orphan images (Admin only)."""
    if http_request:
        session_data = auth.decode_session_token(http_request.cookies.get(auth.SESSION_COOKIE))
        if not session_data or session_data.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Admin privileges required.")
    return sync_wine_labels_housekeeping(db)


# --- Bottle Label Generation Endpoints (Admin Only) ---

@app.get("/admin/labels/info", response_model=LabelInfoResponse)
def get_label_info_endpoint(
    db: Session = Depends(get_db),
    http_request: Request = None,
):
    """Returns template specifications and next recommended starting label (Admin only)."""
    if http_request:
        session_data = auth.decode_session_token(http_request.cookies.get(auth.SESSION_COOKIE))
        if not session_data or session_data.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Admin privileges required.")

    next_label = generate_labels.get_next_starting_label(db=db)
    return LabelInfoResponse(
        template=generate_labels.TEMPLATE_NAME,
        label_count=generate_labels.LABEL_COUNT,
        dimensions='1" x 0.5"',
        sheet_size=f'{generate_labels.PAGE_WIDTH_IN}" x {generate_labels.PAGE_HEIGHT_IN}" (US Letter)',
        next_starting_label=next_label,
        columns=generate_labels.COLUMNS,
        rows=generate_labels.ROWS,
    )


@app.post("/admin/labels/check", response_model=LabelCheckResponse)
def check_labels_endpoint(
    payload: LabelCheckRequest,
    db: Session = Depends(get_db),
    http_request: Request = None,
):
    """Checks the starting label range for conflicts with existing bottles or sheets (Admin only)."""
    if http_request:
        session_data = auth.decode_session_token(http_request.cookies.get(auth.SESSION_COOKIE))
        if not session_data or session_data.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Admin privileges required.")

    try:
        conflicts_info = generate_labels.check_label_conflicts(
            starting_label=payload.starting_label,
            db=db,
        )
        return LabelCheckResponse(**conflicts_info)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@app.post("/admin/labels/generate")
def generate_labels_endpoint(
    payload: LabelGenerateRequest,
    db: Session = Depends(get_db),
    http_request: Request = None,
):
    """Generates an 84-label PDF sheet (Admin only) and returns the PDF file for download."""
    if http_request:
        session_data = auth.decode_session_token(http_request.cookies.get(auth.SESSION_COOKIE))
        if not session_data or session_data.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Admin privileges required.")

    try:
        prefix, start_num, num_width = generate_labels.parse_starting_label(payload.starting_label)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    if not payload.force:
        conflicts_info = generate_labels.check_label_conflicts(
            starting_label=payload.starting_label,
            db=db,
        )
        if conflicts_info["has_conflicts"]:
            conflict_samples = ", ".join(str(n) for n in conflicts_info["conflicts"][:5])
            if len(conflicts_info["conflicts"]) > 5:
                conflict_samples += f" (+{len(conflicts_info['conflicts']) - 5} more)"
            raise HTTPException(
                status_code=409,
                detail=f"Label numbers conflict with previously used or existing bottles: {conflict_samples}. Confirm to proceed.",
            )

    last_num = start_num + generate_labels.LABEL_COUNT - 1
    first_label = f"{prefix}{start_num:0{num_width}d}"
    last_label = f"{prefix}{last_num:0{num_width}d}"

    safe_first = re.sub(r"[^A-Za-z0-9._-]+", "_", first_label).strip("._-")
    safe_last = re.sub(r"[^A-Za-z0-9._-]+", "_", last_label).strip("._-")
    filename = f"labels_{safe_first}_to_{safe_last}.pdf"
    output_dir = generate_labels.DEFAULT_OUTPUT_DIR
    output_path = output_dir / filename

    base_url = None
    if http_request:
        base_url = str(http_request.base_url).rstrip("/")
    env_url = get_settings().public_base_url
    if env_url:
        base_url = env_url.rstrip("/")

    generate_labels.create_label_pdf(
        starting_label=payload.starting_label,
        output_path=output_path,
        base_url=base_url,
    )

    hist_path = output_dir / generate_labels.HISTORY_FILENAME
    used = generate_labels.load_used_numbers(hist_path, output_dir)
    requested = set(range(start_num, last_num + 1))
    generate_labels.save_used_numbers(hist_path, used | requested)

    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "X-First-Label": first_label,
        "X-Last-Label": last_label,
        "X-Label-Count": str(generate_labels.LABEL_COUNT),
    }
    return FileResponse(
        str(output_path),
        media_type="application/pdf",
        headers=headers,
    )


# --- Sprint 3: The Two-Step Registration Flow ---



@app.post("/wines/scan-qr")
async def scan_bottle_qr_image(
    photo: UploadFile = File(...),
):
    """Decode a bottle QR code photo when browser BarcodeDetector is unavailable."""
    photo_bytes = await photo.read(MAX_LABEL_SIZE_BYTES + 1)
    if not photo_bytes or len(photo_bytes) > MAX_LABEL_SIZE_BYTES:
        raise HTTPException(status_code=400, detail="Upload a valid image up to 10 MB.")

    try:
        with Image.open(BytesIO(photo_bytes)) as image:
            image.verify()
    except Exception:
        raise HTTPException(status_code=415, detail="Upload a valid image file.")

    with Image.open(BytesIO(photo_bytes)) as image:
        barcodes = zxingcpp.read_barcodes(
            image,
            formats=zxingcpp.BarcodeFormat.QRCode,
        )
    if not barcodes:
        raise HTTPException(
            status_code=422,
            detail="Could not read a QR code from that image. Ensure the full code is visible and try again.",
        )

    qr_value = barcodes[0].text.strip()
    parsed = urlparse(qr_value)
    path_match = re.search(r"/wines/([^/?#]+)", parsed.path, re.IGNORECASE)
    if path_match:
        qr_id = unquote(path_match.group(1))
    else:
        query = parse_qs(parsed.query)
        qr_id = (query.get("checkout") or query.get("qr_id") or [qr_value])[0].strip()
    return {"qr_id": qr_id}


@app.post("/wines/scan", response_model=WineDraftResponse)
async def scan_wine_label(
    qr_id: Optional[str] = Form(None),
    photo: UploadFile = File(...),
):
    """
    Reads a label and returns editable suggestions. Nothing is committed until
    the user calls /wines/confirm; Grapeminds lookup is a separate optional step.
    """
    qr_id = (qr_id or "").strip()
    if len(qr_id) > 64:
        raise HTTPException(status_code=422, detail="QR ID cannot exceed 64 characters.")

    photo_bytes = await photo.read(MAX_LABEL_SIZE_BYTES + 1)
    if not photo_bytes:
        raise HTTPException(status_code=400, detail="The uploaded image is empty.")
    if len(photo_bytes) > MAX_LABEL_SIZE_BYTES:
        raise HTTPException(status_code=413, detail="Image must be 10 MB or smaller.")

    try:
        with Image.open(BytesIO(photo_bytes)) as image:
            if image.width * image.height > 40_000_000:
                raise HTTPException(
                    status_code=413,
                    detail="Image dimensions must not exceed 40 megapixels.",
                )
            image.verify()
            image_format = image.format
    except HTTPException:
        raise
    except (
        UnidentifiedImageError,
        Image.DecompressionBombError,
        OSError,
        ValueError,
    ):
        raise HTTPException(status_code=415, detail="Upload a valid image file.")

    image_mime_type = Image.MIME.get(image_format or "")
    allowed_image_types = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }
    if image_mime_type not in allowed_image_types:
        raise HTTPException(
            status_code=415,
            detail="Use a JPEG, PNG, WebP, or GIF image.",
        )

    photo_filename = f"{uuid.uuid4().hex}{allowed_image_types[image_mime_type]}"
    photo_path = os.path.join(UPLOAD_DIR, photo_filename)
    with open(photo_path, "wb") as f:
        f.write(photo_bytes)

    # 2. Run local vision extraction (Anchor)
    print(f"👁️ Running vision extraction on {photo_filename}...")
    vision_result = await asyncio.to_thread(
        vision.extract_from_image,
        photo_bytes,
        image_mime_type,
    )
    print(f"   Vision found: {vision_result}")

    suggested = {
        field: vision_result.get(field)
        for field in (
            "winery",
            "name",
            "vintage",
            "region",
            "country_of_origin",
            "grape_type",
        )
    }
    if vision_result.get("color"):
        suggested["color"] = vision_result.get("color")

    return WineDraftResponse(
        qr_id=qr_id,
        photo_path=photo_filename,
        vision_extraction=vision_result,
        enrichment_metadata=None,
        enrichment_status="not_attempted",
        suggested_fields=suggested,
        grapeminds_id=vision_result.get("_wineapi_id"),
    )


@app.post(
    "/wines/enrichment/lookup",
    response_model=WineEnrichmentLookupResponse,
)
def lookup_wine_draft_enrichment(request: GrapemindsLookupRequest):
    """Fetch a Grapeminds record by an ID the user has already identified."""
    metadata, status = enricher.enrich_by_id(request.grapeminds_id)
    return WineEnrichmentLookupResponse(status=status, metadata=metadata)


@app.post("/wines/confirm", response_model=WineResponse)
def confirm_wine_draft(
    wine: WineCreate,
    db: Session = Depends(get_db),
):
    """
    Step 2 of Registration (Hybrid Enrichment).
    Receives the user's verified/corrected data from the Review Card and commits it.
    `is_verified=True` MUST be set by the user — that's our HITL guarantee.
    """
    if not wine.is_verified:
        raise HTTPException(
            status_code=400,
            detail="is_verified must be True. The user must confirm the draft before commit."
        )

    # Check for duplicate QR ID
    existing = crud.get_wine_by_qr_id(db, wine.qr_id)
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Wine with qr_id '{wine.qr_id}' already exists."
        )

    if wine.location_id is not None and not db.get(models.Location, wine.location_id):
        raise HTTPException(status_code=422, detail="Selected storage location does not exist.")

    try:
        return crud.create_wine(db, wine.model_dump())
    except Exception:
        logging.exception("Failed to save confirmed wine draft.")
        raise HTTPException(status_code=500, detail="Could not save the wine.")


@app.post("/wines/confirm/batch", response_model=List[WineResponse])
def confirm_wine_batch(
    batch: WineBatchCreate,
    db: Session = Depends(get_db),
):
    wines = batch.wines
    if any(not wine.is_verified for wine in wines):
        raise HTTPException(
            status_code=400,
            detail="Every wine must be verified before the batch can be saved.",
        )

    qr_ids = [wine.qr_id for wine in wines]
    if len(set(qr_ids)) != len(qr_ids):
        raise HTTPException(status_code=409, detail="The batch contains duplicate QR IDs.")

    existing_ids = {
        row[0]
        for row in db.query(models.WineEntry.qr_id)
        .filter(models.WineEntry.qr_id.in_(qr_ids))
        .all()
    }
    if existing_ids:
        raise HTTPException(
            status_code=409,
            detail=f"QR ID '{sorted(existing_ids)[0]}' already exists.",
        )

    location_ids = {wine.location_id for wine in wines if wine.location_id is not None}
    if location_ids:
        existing_location_ids = {
            row[0]
            for row in db.query(models.Location.id)
            .filter(models.Location.id.in_(location_ids))
            .all()
        }
        if location_ids - existing_location_ids:
            raise HTTPException(status_code=422, detail="Selected storage location does not exist.")

    entries = [models.WineEntry(**wine.model_dump()) for wine in wines]
    try:
        db.add_all(entries)
        db.commit()
        for entry in entries:
            db.refresh(entry)
        return entries
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="A QR ID in this batch was added by another request. No bottles were saved.",
        ) from error
    except Exception:
        db.rollback()
        logging.exception("Failed to save confirmed wine batch.")
        raise HTTPException(status_code=500, detail="Could not save the wine batch.")


# --- Wine CRUD ---

@app.post("/wines/", response_model=WineResponse)
def create_wine_endpoint(wine: WineCreate, db: Session = Depends(get_db)):
    """Direct creation (skips vision/enrichment). Useful for testing/manual entry."""
    if existing := crud.get_wine_by_qr_id(db, wine.qr_id):
        raise HTTPException(status_code=409, detail=f"QR ID '{wine.qr_id}' already exists.")
    if wine.location_id is not None and not db.get(models.Location, wine.location_id):
        raise HTTPException(status_code=422, detail="Selected storage location does not exist.")
    try:
        return crud.create_wine(db, wine.model_dump())
    except Exception:
        logging.exception("Failed to create wine.")
        raise HTTPException(status_code=500, detail="Could not create the wine.")


@app.get("/wines/", response_model=List[WineResponse])
def list_wines_endpoint(
    status: Optional[models.WineStatus] = None,
    grapeminds_id: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    """List wines, optionally filtered by status (in_cellar, removed, gifted, broken) or grapeminds_id."""
    query = db.query(models.WineEntry).options(
        joinedload(models.WineEntry.location),
        selectinload(models.WineEntry.tasting_notes),
    )
    if status:
        query = query.filter(models.WineEntry.status == status)
    if grapeminds_id:
        query = query.filter(models.WineEntry.grapeminds_id == grapeminds_id)
    return query.offset(skip).limit(int(limit)).all()


@app.get("/wines/{qr_id}", response_model=WineResponse)
def get_wine_endpoint(qr_id: str, db: Session = Depends(get_db)):
    db_wine = crud.get_wine_by_qr_id(db, qr_id)
    if not db_wine:
        raise HTTPException(status_code=404, detail="Wine not found")
    return db_wine


@app.patch("/wines/{qr_id}", response_model=WineResponse)
def update_wine_endpoint(
    qr_id: str,
    updates: WineUpdate,
    db: Session = Depends(get_db),
):
    db_wine = crud.get_wine_by_qr_id(db, qr_id)
    if not db_wine:
        raise HTTPException(status_code=404, detail="Wine not found.")

    changed_fields = updates.model_dump(exclude_unset=True)
    if not changed_fields:
        raise HTTPException(status_code=422, detail="Provide at least one wine field to update.")
    location_id = changed_fields.get("location_id")
    if location_id is not None and not db.get(models.Location, location_id):
        raise HTTPException(status_code=422, detail="Selected storage location does not exist.")

    for field, value in changed_fields.items():
        setattr(db_wine, field, value)
    try:
        db.commit()
        db.refresh(db_wine)
    except Exception:
        db.rollback()
        logging.exception("Failed to update wine %s.", qr_id)
        raise HTTPException(status_code=500, detail="Could not update the wine.")
    return db_wine


@app.patch("/wines/batch/update", response_model=List[WineResponse])
def update_wine_batch_endpoint(
    batch: WineBatchUpdate,
    db: Session = Depends(get_db),
):
    updates = batch.updates.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(
            status_code=422,
            detail="Provide at least one wine field to update.",
        )

    location_id = updates.get("location_id")
    if location_id is not None and not db.get(models.Location, location_id):
        raise HTTPException(
            status_code=422,
            detail="Selected storage location does not exist.",
        )

    if "location_id" in updates and not batch.force_move:
        wines = (
            db.query(models.WineEntry)
            .filter(models.WineEntry.qr_id.in_(batch.qr_ids))
            .all()
        )
        current_locations = {wine.location_id for wine in wines}
        if len(current_locations) > 1:
            conflicts = []
            for wine in wines:
                loc_name = "Unknown"
                if wine.location_id:
                    loc = db.get(models.Location, wine.location_id)
                    if loc:
                        parts = [loc.name]
                        if loc.sub_location:
                            parts.append(loc.sub_location)
                        loc_name = " · ".join(parts)
                conflicts.append({"qr_id": wine.qr_id, "current_location": loc_name})

            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Conflict: This batch is spread across multiple locations. Use force_move=True to override.",
                    "conflicts": conflicts
                }
            )

    if len(set(batch.qr_ids)) != len(batch.qr_ids):
        raise HTTPException(
            status_code=409,
            detail="The batch contains duplicate bottle IDs.",
        )

    wines = (
        db.query(models.WineEntry)
        .filter(models.WineEntry.qr_id.in_(batch.qr_ids))
        .all()
    )
    by_qr_id = {wine.qr_id: wine for wine in wines}
    if len(by_qr_id) != len(batch.qr_ids):
        raise HTTPException(
            status_code=404,
            detail="One or more bottles in the group no longer exist.",
        )

    for wine in wines:
        for field, value in updates.items():
            setattr(wine, field, value)
    try:
        db.commit()
        for wine in wines:
            db.refresh(wine)
        return [by_qr_id[qr_id] for qr_id in batch.qr_ids]
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="A QR ID in this batch was added by another request. No bottles were saved.",
        ) from error
    except Exception:
        db.rollback()
        logging.exception("Failed to update wine group.")
        raise HTTPException(
            status_code=500,
            detail="Could not update the wine group.",
        )


@app.post(
    "/wines/{qr_id}/enrichment/lookup",
    response_model=WineEnrichmentLookupResponse,
)
def lookup_existing_wine_enrichment_endpoint(
    qr_id: str,
    request: GrapemindsLookupRequest,
    db: Session = Depends(get_db),
):
    """Preview Grapeminds metadata by ID for an existing bottle."""
    db_wine = crud.get_wine_by_qr_id(db, qr_id)
    if not db_wine:
        raise HTTPException(status_code=404, detail="Wine not found.")
    metadata, status = enricher.enrich_by_id(request.grapeminds_id)
    return WineEnrichmentLookupResponse(status=status, metadata=metadata)


def apply_grapeminds_metadata(db_wine, request: GrapemindsApplyRequest, db: Session):
    unknown_fields = set(request.selected_fields) - GRAPEMINDS_APPLY_FIELDS
    if unknown_fields:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported Grapeminds fields: {', '.join(sorted(unknown_fields))}.",
        )

    db_wine.grapeminds_id = request.grapeminds_id
    for field in request.selected_fields:
        value = request.metadata.get(field)
        if value is not None:
            setattr(db_wine, field, value)
        if field == "grape_type" and request.metadata.get("grape_varieties") is not None:
            db_wine.grape_varieties = request.metadata["grape_varieties"]
    try:
        db.commit()
        db.refresh(db_wine)
    except Exception:
        db.rollback()
        logging.exception("Failed to save Grapeminds metadata.")
        raise HTTPException(status_code=500, detail="Could not save Grapeminds details.")
    return db_wine


@app.post("/wines/{qr_id}/enrichment/apply", response_model=WineResponse)
def apply_existing_wine_enrichment_endpoint(
    qr_id: str,
    request: GrapemindsApplyRequest,
    db: Session = Depends(get_db),
):
    """Save only user-selected Grapeminds fields and the confirmed catalog ID."""
    db_wine = crud.get_wine_by_qr_id(db, qr_id)
    if not db_wine:
        raise HTTPException(status_code=404, detail="Wine not found.")
    return apply_grapeminds_metadata(db_wine, request, db)


@app.patch("/wines/{qr_id}/status", response_model=WineResponse)
def update_wine_status_endpoint(
    qr_id: str,
    new_status: models.WineStatus,
    db: Session = Depends(get_db),
):
    """Marks a wine as removed/gifted/broken."""
    db_wine = crud.update_wine_status(db, qr_id, new_status)
    if not db_wine:
        raise HTTPException(status_code=404, detail="Wine not found")
    return db_wine


@app.post("/wines/{qr_id}/checkout", response_model=WineResponse)
@app.post("/wines/{qr_id}/remove", response_model=WineResponse)
def remove_wine_endpoint(
    qr_id: str,
    request: WineRemovalRequest,
    db: Session = Depends(get_db),
    http_request: Request = None,
):
    """Checks out a bottle from the active collection (marking it inactive while
    preserving it in the database), records checkout_date, comment, and optional
    taste/pairing updates (for this bottle or the wine group) and tasting notes.
    """
    db_wine = crud.get_wine_by_qr_id(db, qr_id)
    if not db_wine:
        raise HTTPException(status_code=404, detail="Wine not found")

    db_wine.status = request.status
    effective_date = (
        request.checkout_date
        or (
            request.tasting_note.tasting_date
            if request.tasting_note and request.tasting_note.tasting_date
            else None
        )
        or date.today()
    )
    db_wine.checkout_date = effective_date

    fields_set = request.model_fields_set
    if "comment" in fields_set:
        db_wine.comment = (request.comment or "").strip() or None

    shared_updates = {}
    if "pairing" in fields_set:
        val = request.pairing.strip() if isinstance(request.pairing, str) else request.pairing
        shared_updates["pairing"] = val or None
    if "grapeminds_tasting_notes" in fields_set:
        val = (
            request.grapeminds_tasting_notes.strip()
            if isinstance(request.grapeminds_tasting_notes, str)
            else request.grapeminds_tasting_notes
        )
        shared_updates["grapeminds_tasting_notes"] = val or None

    if shared_updates:
        for field, val in shared_updates.items():
            setattr(db_wine, field, val)
        if request.apply_to_group_qr_ids:
            group_wines = (
                db.query(models.WineEntry)
                .filter(models.WineEntry.qr_id.in_(request.apply_to_group_qr_ids))
                .all()
            )
            for gw in group_wines:
                for field, val in shared_updates.items():
                    setattr(gw, field, val)

    if request.tasting_note:
        note_dict = request.tasting_note.model_dump(exclude_unset=True)
        if "notes" in note_dict and isinstance(note_dict["notes"], str):
            note_dict["notes"] = note_dict["notes"].strip() or None
        if "aroma_tags" in note_dict and isinstance(note_dict["aroma_tags"], str):
            note_dict["aroma_tags"] = note_dict["aroma_tags"].strip() or None
        if not note_dict.get("tasting_date"):
            note_dict["tasting_date"] = effective_date
        if not note_dict.get("author_name") and http_request:
            session_data = auth.decode_session_token(http_request.cookies.get(auth.SESSION_COOKIE))
            if session_data:
                note_dict["author_name"] = session_data.get("username")
        crud.create_tasting_note(db, wine_entry_id=db_wine.id, **note_dict)

    db.commit()
    db.refresh(db_wine)
    return db_wine


@app.delete("/wines/{qr_id}")
def delete_wine_endpoint(
    qr_id: str,
    db: Session = Depends(get_db),
    http_request: Request = None,
):
    """Permanently deletes a wine entry and all its tasting notes (Admin only)."""
    if http_request:
        session_data = auth.decode_session_token(http_request.cookies.get(auth.SESSION_COOKIE))
        if not session_data or session_data.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Admin privileges required.")

    db_wine = crud.get_wine_by_qr_id(db, qr_id)
    if not db_wine:
        raise HTTPException(status_code=404, detail="Wine not found")

    photo_to_check = db_wine.photo_path
    wine_id = db_wine.id

    db.delete(db_wine)
    db.commit()

    if photo_to_check:
        remaining = db.query(models.WineEntry.id).filter(
            models.WineEntry.photo_path == photo_to_check,
            models.WineEntry.id != wine_id,
        ).first()
        if not remaining:
            clean_orphan_label_file(photo_to_check)

    return {"deleted": qr_id}


@app.post("/wines/batch/delete")
@app.delete("/wines/batch")
def delete_wine_batch_endpoint(
    batch: WineBatchDelete,
    db: Session = Depends(get_db),
    http_request: Request = None,
):
    """Permanently deletes a batch of wine entries and all their tasting notes (Admin only)."""
    if http_request:
        session_data = auth.decode_session_token(http_request.cookies.get(auth.SESSION_COOKIE))
        if not session_data or session_data.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Admin privileges required.")

    if not batch.qr_ids:
        raise HTTPException(status_code=422, detail="Provide at least one bottle ID to delete.")

    unique_qr_ids = list(dict.fromkeys(batch.qr_ids))
    wines = (
        db.query(models.WineEntry)
        .filter(models.WineEntry.qr_id.in_(unique_qr_ids))
        .all()
    )
    if not wines:
        raise HTTPException(status_code=404, detail="No matching wines found.")

    photos_to_check = {w.photo_path for w in wines if w.photo_path}
    deleted_ids = [wine.id for wine in wines]
    deleted_qr_ids = [wine.qr_id for wine in wines]

    for wine in wines:
        db.delete(wine)
    db.commit()

    for photo in photos_to_check:
        remaining = db.query(models.WineEntry.id).filter(
            models.WineEntry.photo_path == photo,
            models.WineEntry.id.notin_(deleted_ids),
        ).first()
        if not remaining:
            clean_orphan_label_file(photo)

    return {"deleted": deleted_qr_ids, "count": len(deleted_qr_ids)}


# --- Tasting Note Endpoints ---

@app.post("/wines/{qr_id}/tasting-notes", response_model=TastingNoteResponse)
def add_tasting_note_endpoint(
    qr_id: str,
    note: TastingNoteBase,
    db: Session = Depends(get_db),
    http_request: Request = None,
):
    """Adds a tasting note to an existing wine."""
    db_wine = crud.get_wine_by_qr_id(db, qr_id)
    if not db_wine:
        raise HTTPException(status_code=404, detail="Wine not found")
    note_dict = note.model_dump()
    if not note_dict.get("author_name") and http_request:
        session_data = auth.decode_session_token(http_request.cookies.get(auth.SESSION_COOKIE))
        if session_data:
            note_dict["author_name"] = session_data.get("username")
    return crud.create_tasting_note(db, wine_entry_id=db_wine.id, **note_dict)


# --- Location Endpoints ---

@app.post("/locations/", response_model=LocationResponse)
def create_location_endpoint(
    location: LocationBase,
    db: Session = Depends(get_db),
    http_request: Request = None,
):
    """Creates a new storage location (Admin only)."""
    if http_request:
        session_data = auth.decode_session_token(http_request.cookies.get(auth.SESSION_COOKIE))
        if not session_data or session_data.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Admin privileges required.")

    location.name = location.name.strip()
    if not location.name:
        raise HTTPException(status_code=422, detail="Location name cannot be empty.")
    if location.sub_location is not None:
        location.sub_location = location.sub_location.strip() or None
    if location.parent_location_id is not None and not db.get(
        models.Location, location.parent_location_id
    ):
        raise HTTPException(status_code=404, detail="Parent location not found.")
    return crud.create_location(db, **location.model_dump())


@app.get("/locations/", response_model=List[LocationResponse])
def list_locations_endpoint(db: Session = Depends(get_db)):
    return crud.get_all_locations(db)


@app.patch("/locations/{location_id}", response_model=LocationResponse)
def update_location_endpoint(
    location_id: int,
    updates: LocationUpdate,
    db: Session = Depends(get_db),
    http_request: Request = None,
):
    """Updates location details (Admin only)."""
    if http_request:
        session_data = auth.decode_session_token(http_request.cookies.get(auth.SESSION_COOKIE))
        if not session_data or session_data.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Admin privileges required.")

    location = db.get(models.Location, location_id)
    if not location:
        raise HTTPException(status_code=404, detail="Location not found.")

    changed_fields = updates.model_dump(exclude_unset=True)
    if not changed_fields:
        raise HTTPException(status_code=422, detail="Provide a location name or detail to update.")
    if "name" in changed_fields:
        changed_fields["name"] = (changed_fields["name"] or "").strip()
        if not changed_fields["name"]:
            raise HTTPException(status_code=422, detail="Location name cannot be empty.")
    if "sub_location" in changed_fields and changed_fields["sub_location"] is not None:
        changed_fields["sub_location"] = changed_fields["sub_location"].strip() or None

    return crud.update_location(db, location, changed_fields)


@app.delete("/locations/{location_id}", status_code=204)
def delete_location_endpoint(
    location_id: int,
    db: Session = Depends(get_db),
    http_request: Request = None,
):
    """Deletes an empty storage location (Admin only)."""
    if http_request:
        session_data = auth.decode_session_token(http_request.cookies.get(auth.SESSION_COOKIE))
        if not session_data or session_data.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Admin privileges required.")

    location = db.get(models.Location, location_id)
    if not location:
        raise HTTPException(status_code=404, detail="Location not found.")
    if db.query(models.WineEntry.id).filter(
        models.WineEntry.location_id == location_id
    ).first():
        raise HTTPException(
            status_code=409,
            detail="Move the wine bottles out of this location before removing it.",
        )
    if db.query(models.Location.id).filter(
        models.Location.parent_location_id == location_id
    ).first():
        raise HTTPException(
            status_code=409,
            detail="Remove its child locations before removing this location.",
        )

    crud.delete_location(db, location)


# --- Sprint 4: Enrichment Budget Monitoring ---

@app.get("/enrichment/usage")
def enrichment_usage_endpoint():
    """Returns current Grapeminds API usage stats (calls this month, cache hits, etc.)."""
    return enricher.get_usage_stats()

@app.get("/grapeminds/search")
def search_grapeminds_wines(
    q: str,
    provider: Optional[str] = None,
    include_meta: bool = False,
    db: Session = Depends(get_db),
):
    """Search the wine catalog (WineAPI.io and/or Grapeminds) with automatic fallback."""
    if provider is None and not include_meta:
        return enricher.search_wines(q)
    catalog_result = enricher.search_catalog(q, provider=provider or "wineapi")
    if include_meta:
        return catalog_result
    return catalog_result["results"]

@app.get("/grapeminds/details/{grapeminds_id}", response_model=dict)
def get_grapeminds_details(
    grapeminds_id: str,
    provider: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Fetch full details for a specific catalog wine ID (WineAPI.io UUID or Grapeminds ID)."""
    metadata, status = enricher.enrich_by_id(grapeminds_id, provider=provider)
    if status == "no_match" or metadata is None:
        raise HTTPException(status_code=404, detail="Wine not found in catalog.")
    return metadata
