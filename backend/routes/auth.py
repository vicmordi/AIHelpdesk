"""
Authentication routes — backend-first. Supports multi-tenant (org) and legacy flows.
"""

import logging
import httpx
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, Field
from starlette.responses import Response

from config import ADMIN_ACCESS_CODE, FIREBASE_WEB_API_KEY, ENVIRONMENT
from firebase_admin import firestore, auth as firebase_auth
from middleware import verify_token, get_current_user, require_super_admin
from rate_limit import limiter
from schemas import STRICT_REQUEST_CONFIG

router = APIRouter()
logger = logging.getLogger(__name__)
FIREBASE_AUTH_URL = "https://identitytoolkit.googleapis.com/v1/accounts"


def get_db():
    return firestore.client()


def _get_client_ip(request: Request) -> str:
    """Client IP for activity logging (X-Forwarded-For or request.client.host)."""
    from brute_force import get_client_ip as _ip
    return _ip(request)


def _log_failed_login_and_brute_force(request: Request, organization_code: Optional[str], attempted_email: str) -> None:
    """Log login_failed, then if IP exceeds threshold log brute_force_attempt. Non-blocking."""
    try:
        from brute_force import get_client_ip, record_failed_login, clear_after_brute_force_log
        from activity_logging import log_activity, ACTION_LOGIN_FAILED, ACTION_BRUTE_FORCE_ATTEMPT
        client_ip = get_client_ip(request)
        db = get_db()
        org_id = ""
        if (organization_code or "").strip():
            orgs = db.collection("organizations").where("organization_code", "==", organization_code.strip()).limit(1).stream()
            org_doc = next(orgs, None)
            if org_doc:
                org_id = org_doc.id
        meta = {"attempted_email": attempted_email or ""}
        if client_ip:
            meta["ip_address"] = client_ip
        log_activity(
            db,
            organization_id=org_id,
            user_id="",
            user_role="",
            action_type=ACTION_LOGIN_FAILED,
            action_label="Login failed",
            metadata=meta,
        )
        if record_failed_login(client_ip):
            log_activity(
                db,
                organization_id=org_id,
                user_id="",
                user_role="",
                action_type=ACTION_BRUTE_FORCE_ATTEMPT,
                action_label="Brute force attempt detected",
                metadata=meta,
            )
            clear_after_brute_force_log(client_ip)
    except Exception as e:
        logger.exception("Failed to log login_failed/brute_force: %s", e)


class LoginRequest(BaseModel):
    model_config = STRICT_REQUEST_CONFIG
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)
    organization_code: Optional[str] = Field(None, max_length=64)


class RegisterRequest(BaseModel):
    model_config = STRICT_REQUEST_CONFIG
    email: EmailStr
    password: str = Field(..., min_length=6, max_length=128)
    role: str = Field(default="employee", pattern="^(employee|admin)$")
    admin_code: Optional[str] = Field(None, max_length=128)


class RegisterOrgRequest(BaseModel):
    """Multi-tenant registration: creates organization + super_admin user."""
    model_config = STRICT_REQUEST_CONFIG
    organization_name: str = Field(..., min_length=1, max_length=256)
    organization_code: str = Field(..., min_length=2, max_length=64)
    super_admin_name: str = Field(default="", max_length=256)
    email: EmailStr
    password: str = Field(..., min_length=6, max_length=128)


def _firebase_auth_request(endpoint: str, body: dict) -> dict:
    """Call Firebase Auth REST API. Raises HTTPException on error."""
    if not FIREBASE_WEB_API_KEY:
        raise HTTPException(status_code=503, detail="Auth not configured")
    url = f"{FIREBASE_AUTH_URL}:{endpoint}?key={FIREBASE_WEB_API_KEY}"
    with httpx.Client() as client:
        resp = client.post(url, json=body, timeout=15.0)
    data = resp.json()
    if resp.status_code != 200:
        detail = data.get("error", {}).get("message", resp.text)
        if "INVALID_LOGIN_CREDENTIALS" in detail or "EMAIL_NOT_FOUND" in detail:
            raise HTTPException(status_code=401, detail="Invalid email or password")
        if "INVALID_PASSWORD" in detail:
            raise HTTPException(status_code=401, detail="Invalid email or password")
        if "EMAIL_EXISTS" in detail:
            raise HTTPException(status_code=400, detail="Email already registered")
        raise HTTPException(status_code=resp.status_code, detail=detail)
    return data


@router.post("/login")
@limiter.limit("15/minute")  # Stricter limit for auth to mitigate brute-force (OWASP)
async def login(request: Request, response: Response, body: LoginRequest):
    """
    Login requires organization_code, email, password.
    Backend finds org by code, validates user belongs to that org.
    Prevents cross-organization access.
    """
    if not (body.organization_code or "").strip():
        raise HTTPException(status_code=400, detail="Organization code is required")

    try:
        data = _firebase_auth_request("signInWithPassword", {
            "email": body.email,
            "password": body.password,
            "returnSecureToken": True,
        })
        uid = data["localId"]
        db = get_db()

        orgs_ref = db.collection("organizations")
        orgs = orgs_ref.where("organization_code", "==", body.organization_code.strip()).limit(1).stream()
        org_doc = next(orgs, None)
        if not org_doc:
            raise HTTPException(status_code=401, detail="Invalid organization code")
        org_id = org_doc.id

        user_ref = db.collection("users").document(uid)
        user_doc = user_ref.get()
        if not user_doc.exists:
            raise HTTPException(status_code=401, detail="User not found")
        user_data = user_doc.to_dict()
        if user_data.get("disabled"):
            raise HTTPException(status_code=403, detail="Account is disabled")

        user_org_id = user_data.get("organization_id")
        if user_org_id != org_id:
            raise HTTPException(status_code=401, detail="User does not belong to this organization")

        user_ref.update({"last_login": datetime.utcnow().isoformat()})

        role = user_data.get("role", "employee")
        if role == "admin":
            role = "super_admin"
        user_name = (user_data.get("full_name") or user_data.get("name") or user_data.get("email") or "").strip()
        client_ip = _get_client_ip(request)
        try:
            from activity_logging import log_activity, ACTION_LOGIN_SUCCESS
            log_activity(
                db,
                organization_id=org_id,
                user_id=uid,
                user_role=role,
                action_type=ACTION_LOGIN_SUCCESS,
                action_label="Login success",
                metadata={"ip_address": client_ip} if client_ip else None,
                user_name=user_name,
            )
        except Exception:
            pass  # Non-blocking

        return JSONResponse(content={"token": data["idToken"], "email": data.get("email")})
    except HTTPException as e:
        if e.status_code == 401:
            _log_failed_login_and_brute_force(request, body.organization_code, body.email)
        raise
    except Exception as e:
        logger.exception("Login failed: %s", e)
        detail = "Login failed"
        if ENVIRONMENT == "development":
            detail = f"Login failed: {str(e)}"
        raise HTTPException(status_code=500, detail=detail)


@router.post("/register")
@limiter.limit("15/minute")  # Stricter limit for auth (OWASP)
async def register(request: Request, response: Response, body: RegisterRequest):
    """
    Legacy register: create user in Firebase Auth, create Firestore user doc (no org).
    For new organizations use POST /auth/register-org.
    """
    try:
        requested_role = (body.role or "employee").lower()
        if requested_role not in ["employee", "admin"]:
            requested_role = "employee"

        if requested_role == "admin":
            if not ADMIN_ACCESS_CODE:
                raise HTTPException(
                    status_code=403,
                    detail="Admin registration is not configured."
                )
            if not body.admin_code or body.admin_code != ADMIN_ACCESS_CODE:
                raise HTTPException(
                    status_code=403,
                    detail="Invalid admin access code."
                )

        data = _firebase_auth_request("signUp", {
            "email": body.email,
            "password": body.password,
            "returnSecureToken": True,
        })
        uid = data["localId"]
        email = data.get("email", body.email)
        id_token = data["idToken"]

        db = get_db()
        user_ref = db.collection("users").document(uid)
        user_ref.set({
            "uid": uid,
            "email": email,
            "role": requested_role,
            "createdAt": datetime.utcnow().isoformat(),
        })

        return JSONResponse(content={
            "token": id_token,
            "uid": uid,
            "email": email,
            "role": requested_role,
        })
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Registration failed")


@router.post("/register-org")
@limiter.limit("15/minute")  # Stricter limit for auth (OWASP)
async def register_org(request: Request, response: Response, body: RegisterOrgRequest):
    """
    Multi-tenant registration: create organization and first user (super_admin).
    organization_code must be unique. Creates organization doc, Firebase user, user doc linked to org.
    """
    try:
        code = (body.organization_code or "").strip()
        if not code:
            raise HTTPException(status_code=400, detail="organization_code is required")
        name = (body.organization_name or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="organization_name is required")

        db = get_db()
        # Check organization_code is unique
        orgs_ref = db.collection("organizations")
        existing = orgs_ref.where("organization_code", "==", code).limit(1).stream()
        if next(existing, None) is not None:
            raise HTTPException(status_code=400, detail="Organization code already in use")

        # Create Firebase user
        data = _firebase_auth_request("signUp", {
            "email": body.email,
            "password": body.password,
            "returnSecureToken": True,
        })
        uid = data["localId"]
        email = data.get("email", body.email)
        id_token = data["idToken"]

        # Create organization doc
        org_data = {
            "name": name,
            "organization_code": code,
            "created_at": datetime.utcnow().isoformat(),
            "super_admin_uid": uid,
        }
        _, org_ref = orgs_ref.add(org_data)
        organization_id = org_ref.id

        # Create user doc with role super_admin and organization_id
        full_name = (body.super_admin_name or "").strip() or email
        user_ref = db.collection("users").document(uid)
        user_ref.set({
            "uid": uid,
            "email": email,
            "full_name": full_name,
            "role": "super_admin",
            "organization_id": organization_id,
            "must_change_password": False,
            "created_at": datetime.utcnow().isoformat(),
            "createdAt": datetime.utcnow().isoformat(),  # backward compat
        })

        return JSONResponse(content={
            "token": id_token,
            "uid": uid,
            "email": email,
            "role": "super_admin",
            "organization_id": organization_id,
        })
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Registration failed")


@router.get("/me")
async def me(current_user: dict = Depends(get_current_user)):
    """Get current user from Firestore (requires valid Bearer token)."""
    return {
        "uid": current_user["uid"],
        "email": current_user["email"],
        "role": current_user["role"],
        "name": current_user.get("name") or current_user.get("email"),
        "first_name": current_user.get("first_name") or "User",
        "organization_id": current_user.get("organization_id"),
        "organization": current_user.get("organization_id"),
        "must_change_password": current_user.get("must_change_password", False),
    }


class ChangePasswordRequest(BaseModel):
    model_config = STRICT_REQUEST_CONFIG
    current_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=6, max_length=128)


@router.post("/change-password")
async def change_password(
    body: ChangePasswordRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Change password for the current user. Verifies current password via Firebase, then updates.
    Sets must_change_password = False after successful change.
    """
    email = current_user.get("email")
    uid = current_user["uid"]
    if not email:
        raise HTTPException(status_code=400, detail="User email not found")
    try:
        _firebase_auth_request("signInWithPassword", {
            "email": email,
            "password": body.current_password,
            "returnSecureToken": True,
        })
    except HTTPException as e:
        if e.status_code == 401:
            raise HTTPException(status_code=400, detail="Current password is incorrect")
        raise
    if len((body.new_password or "").strip()) < 6:
        raise HTTPException(status_code=400, detail="New password must be at least 6 characters")
    try:
        firebase_auth.update_user(uid, password=body.new_password.strip())
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to update password: {str(e)}")
    db = get_db()
    db.collection("users").document(uid).update({
        "must_change_password": False,
        "updated_at": datetime.utcnow().isoformat(),
    })
    return {"message": "Password updated successfully"}


class CreateOrgForLegacyRequest(BaseModel):
    model_config = STRICT_REQUEST_CONFIG
    organization_name: str = Field(..., min_length=1, max_length=256)
    organization_code: str = Field(..., min_length=2, max_length=64)


@router.post("/create-org-for-legacy")
async def create_org_for_legacy(
    body: CreateOrgForLegacyRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    For legacy users (no organization_id): create an organization and link as super_admin.
    organization_code must be unique. Users remain linked via organization_id.
    """
    if current_user.get("organization_id"):
        raise HTTPException(status_code=400, detail="User already belongs to an organization")
    code = (body.organization_code or "").strip()
    name = (body.organization_name or "").strip()
    if not code or not name:
        raise HTTPException(status_code=400, detail="organization_name and organization_code are required")
    db = get_db()
    existing = db.collection("organizations").where("organization_code", "==", code).limit(1).stream()
    if next(existing, None) is not None:
        raise HTTPException(status_code=400, detail="Organization code already in use")
    uid = current_user["uid"]
    org_data = {
        "name": name,
        "organization_code": code,
        "created_at": datetime.utcnow().isoformat(),
        "super_admin_uid": uid,
    }
    _, org_ref = db.collection("organizations").add(org_data)
    organization_id = org_ref.id
    db.collection("users").document(uid).update({
        "organization_id": organization_id,
        "role": "super_admin",
        "updated_at": datetime.utcnow().isoformat(),
    })
    return {
        "message": "Organization created and account linked",
        "organization_id": organization_id,
        "organization_code": code,
    }
