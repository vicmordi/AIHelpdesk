"""
Authentication routes — backend-first. All auth via Firebase REST API (no client SDK).
"""

import httpx
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, EmailStr

from config import ADMIN_ACCESS_CODE, FIREBASE_WEB_API_KEY
from firebase_admin import firestore
from middleware import verify_token

router = APIRouter()

FIREBASE_AUTH_URL = "https://identitytoolkit.googleapis.com/v1/accounts"


def get_db():
    """Lazy initialization of Firestore client"""
    return firestore.client()


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    role: str = "employee"
    admin_code: Optional[str] = None


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
    Login with email/password. Backend calls Firebase Auth REST API, returns ID token.
    Frontend stores token and sends it in Authorization header for protected endpoints.
    """
    try:
        data = _firebase_auth_request("signInWithPassword", {
            "email": request.email,
            "password": request.password,
            "returnSecureToken": True,
        })
        return {"token": data["idToken"], "email": data.get("email")}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Login failed")


@router.post("/register")
async def register(request: RegisterRequest):
    """
    Register: create user in Firebase Auth via REST API, create Firestore user doc, return token.
    No Firebase client SDK required.
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


@router.get("/me")
async def get_current_user(decoded_token: dict = Depends(verify_token)):
    """Get current user from Firestore (requires valid Bearer token)."""
    uid = decoded_token.get("uid")
    db = get_db()
    user_ref = db.collection("users").document(uid)
    user_doc = user_ref.get()

    if not user_doc.exists:
        raise HTTPException(status_code=404, detail="User not found")

    user_data = user_doc.to_dict()
    return {
        "uid": uid,
        "email": decoded_token.get("email"),
        "role": user_data.get("role", "employee"),
    }
