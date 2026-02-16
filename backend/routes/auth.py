"""
Authentication routes — backend-first. Supports multi-tenant (org) and legacy flows.
"""

import httpx
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, EmailStr

from config import ADMIN_ACCESS_CODE, FIREBASE_WEB_API_KEY
from firebase_admin import firestore, auth as firebase_auth
from middleware import verify_token, get_current_user, require_super_admin

router = APIRouter()

FIREBASE_AUTH_URL = "https://identitytoolkit.googleapis.com/v1/accounts"


def get_db():
    return firestore.client()


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    organization_code: Optional[str] = None  # Required for org users; optional for legacy


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    role: str = "employee"
    admin_code: Optional[str] = None


class RegisterOrgRequest(BaseModel):
    """Multi-tenant registration: creates organization + super_admin user."""
    organization_name: str
    organization_code: str
    email: EmailStr
    password: str


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
async def login(request: LoginRequest):
    """
    Login with email/password. For org users, organization_code is required;
    backend verifies user belongs to that organization.
    Legacy users (no org) can omit organization_code.
    """
    try:
        data = _firebase_auth_request("signInWithPassword", {
            "email": request.email,
            "password": request.password,
            "returnSecureToken": True,
        })
        uid = data["localId"]
        db = get_db()

        user_ref = db.collection("users").document(uid)
        user_doc = user_ref.get()
        if not user_doc.exists:
            raise HTTPException(status_code=401, detail="User not found")
        user_data = user_doc.to_dict()
        if user_data.get("disabled"):
            raise HTTPException(status_code=403, detail="Account is disabled")

        # If organization_code provided: validate and optionally link legacy user
        if request.organization_code:
            orgs_ref = db.collection("organizations")
            orgs = orgs_ref.where("organization_code", "==", request.organization_code.strip()).limit(1).stream()
            org_doc = next(orgs, None)
            if not org_doc:
                raise HTTPException(status_code=401, detail="Invalid organization code")
            org_id = org_doc.id
            user_org_id = user_data.get("organization_id")
            if user_org_id is None:
                # Legacy account: link user to this organization (organization_id is primary, not code)
                user_ref.update({
                    "organization_id": org_id,
                    "last_login": datetime.utcnow().isoformat(),
                })
            elif user_org_id != org_id:
                raise HTTPException(status_code=401, detail="User does not belong to this organization")
            else:
                # Already linked; update last_login
                user_ref.update({"last_login": datetime.utcnow().isoformat()})
        else:
            # No org code: update last_login for users that have no org (legacy)
            if user_data.get("organization_id") is None:
                user_ref.update({"last_login": datetime.utcnow().isoformat()})

        return {"token": data["idToken"], "email": data.get("email")}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Login failed")


@router.post("/register")
async def register(request: RegisterRequest):
    """
    Legacy register: create user in Firebase Auth, create Firestore user doc (no org).
    For new organizations use POST /auth/register-org.
    """
    try:
        requested_role = (request.role or "employee").lower()
        if requested_role not in ["employee", "admin"]:
            requested_role = "employee"

        if requested_role == "admin":
            if not ADMIN_ACCESS_CODE:
                raise HTTPException(
                    status_code=403,
                    detail="Admin registration is not configured."
                )
            if not request.admin_code or request.admin_code != ADMIN_ACCESS_CODE:
                raise HTTPException(
                    status_code=403,
                    detail="Invalid admin access code."
                )

        data = _firebase_auth_request("signUp", {
            "email": request.email,
            "password": request.password,
            "returnSecureToken": True,
        })
        uid = data["localId"]
        email = data.get("email", request.email)
        id_token = data["idToken"]

        db = get_db()
        user_ref = db.collection("users").document(uid)
        user_ref.set({
            "uid": uid,
            "email": email,
            "role": requested_role,
            "createdAt": datetime.utcnow().isoformat(),
        })

        return {
            "token": id_token,
            "uid": uid,
            "email": email,
            "role": requested_role,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Registration failed")


@router.post("/register-org")
async def register_org(request: RegisterOrgRequest):
    """
    Multi-tenant registration: create organization and first user (super_admin).
    organization_code must be unique. Creates organization doc, Firebase user, user doc linked to org.
    """
    try:
        code = (request.organization_code or "").strip()
        if not code:
            raise HTTPException(status_code=400, detail="organization_code is required")
        name = (request.organization_name or "").strip()
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
            "email": request.email,
            "password": request.password,
            "returnSecureToken": True,
        })
        uid = data["localId"]
        email = data.get("email", request.email)
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
        user_ref = db.collection("users").document(uid)
        user_ref.set({
            "uid": uid,
            "email": email,
            "role": "super_admin",
            "organization_id": organization_id,
            "must_change_password": False,
            "created_at": datetime.utcnow().isoformat(),
            "createdAt": datetime.utcnow().isoformat(),  # backward compat
        })

        return {
            "token": id_token,
            "uid": uid,
            "email": email,
            "role": "super_admin",
            "organization_id": organization_id,
        }
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
        "organization_id": current_user.get("organization_id"),
        "must_change_password": current_user.get("must_change_password", False),
    }


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


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
    organization_name: str
    organization_code: str


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
