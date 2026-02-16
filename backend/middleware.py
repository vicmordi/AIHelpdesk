"""
Authentication and role middleware. All endpoints validate JWT and use backend user/org data.
"""

from fastapi import HTTPException, Header, Depends
from firebase_admin import auth as firebase_auth, firestore
from typing import Optional

# Role hierarchy: super_admin > support_admin > employee
VALID_ROLES = ("super_admin", "support_admin", "employee")
# Legacy role "admin" is treated as super_admin for backward compatibility
ADMIN_ROLES = ("super_admin", "support_admin", "admin")


def get_db():
    return firestore.client()


async def verify_token(authorization: Optional[str] = Header(None)) -> dict:
    """
    Verify Firebase ID token from Authorization header.
    Returns the decoded token (uid, email, etc.). Does not load user doc.
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header missing")
    try:
        scheme, token = authorization.split()
        if scheme.lower() != "bearer":
            raise HTTPException(status_code=401, detail="Invalid authentication scheme")
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid authorization header format")
    try:
        decoded = firebase_auth.verify_id_token(token)
        return decoded
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


async def get_current_user(decoded_token: dict = Depends(verify_token)) -> dict:
    """
    Load current user document from Firestore. Returns user dict with uid, email, role,
    organization_id, must_change_password. Used by all protected routes.
    """
    uid = decoded_token.get("uid")
    if not uid:
        raise HTTPException(status_code=401, detail="Invalid token")
    db = get_db()
    user_ref = db.collection("users").document(uid)
    user_doc = user_ref.get()
    if not user_doc.exists:
        raise HTTPException(status_code=404, detail="User not found")
    user_data = user_doc.to_dict()
    if user_data.get("disabled"):
        raise HTTPException(status_code=403, detail="Account is disabled")
    # Normalize role: legacy "admin" -> super_admin for RBAC
    role = user_data.get("role", "employee")
    if role == "admin":
        role = "super_admin"
    return {
        "uid": uid,
        "email": decoded_token.get("email") or user_data.get("email"),
        "role": role,
        "organization_id": user_data.get("organization_id"),
        "must_change_password": user_data.get("must_change_password", False),
        "created_at": user_data.get("created_at"),
        "last_login": user_data.get("last_login"),
    }


def require_super_admin(current_user: dict = Depends(get_current_user)) -> dict:
    """Only super_admin (or legacy admin) can access."""
    if current_user.get("role") != "super_admin":
        raise HTTPException(
            status_code=403,
            detail="Super admin access required",
        )
    return current_user


def require_support_admin_or_above(current_user: dict = Depends(get_current_user)) -> dict:
    """support_admin or super_admin can access (e.g. view tickets, update status)."""
    role = current_user.get("role")
    if role not in ("super_admin", "support_admin"):
        raise HTTPException(
            status_code=403,
            detail="Support admin or super admin access required",
        )
    return current_user


def require_admin_or_above(current_user: dict = Depends(get_current_user)) -> dict:
    """
    Admin-level access: super_admin or support_admin (or legacy admin).
    Used for knowledge base, viewing all org tickets, etc.
    """
    role = current_user.get("role")
    if role not in ("super_admin", "support_admin"):
        raise HTTPException(
            status_code=403,
            detail="Admin access required",
        )
    return current_user


# Alias for backward compatibility: verify_admin = require_admin_or_above
async def verify_admin(decoded_token: dict = Depends(verify_token)) -> dict:
    """
    Verify user is admin (support_admin or super_admin). Returns decoded token.
    For routes that only need token + admin check without full user doc.
    """
    uid = decoded_token.get("uid")
    db = get_db()
    user_ref = db.collection("users").document(uid)
    user_doc = user_ref.get()
    if not user_doc.exists:
        raise HTTPException(status_code=403, detail="User not found")
    user_data = user_doc.to_dict()
    role = user_data.get("role", "employee")
    if role == "admin":
        role = "super_admin"
    if role not in ("super_admin", "support_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    # Return decoded token augmented with role and organization_id for convenience
    decoded_token["_role"] = role
    decoded_token["_organization_id"] = user_data.get("organization_id")
    decoded_token["_user_doc"] = user_data
    return decoded_token
