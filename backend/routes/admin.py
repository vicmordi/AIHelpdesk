"""
Admin-only routes. Super_admin only for user management and support admin CRUD.
"""

from datetime import datetime
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, EmailStr
from firebase_admin import auth as firebase_auth, firestore

from middleware import require_super_admin

router = APIRouter()


def get_db():
    return firestore.client()


def _ensure_org_and_same_org(current_user: dict, target_uid: Optional[str] = None) -> str:
    """Return organization_id; raise if no org or target user not in same org."""
    organization_id = current_user.get("organization_id")
    if not organization_id:
        raise HTTPException(status_code=400, detail="Organization required")
    if target_uid:
        db = get_db()
        target_doc = db.collection("users").document(target_uid).get()
        if not target_doc.exists or target_doc.to_dict().get("organization_id") != organization_id:
            raise HTTPException(status_code=404, detail="User not found in your organization")
    return organization_id


class CreateSupportAdminRequest(BaseModel):
    email: EmailStr
    temporary_password: str


class ResetSupportAdminPasswordRequest(BaseModel):
    uid: str
    new_password: str


@router.get("/users")
async def list_organization_users(current_user: dict = Depends(require_super_admin)):
    """
    List all users in the organization. Super_admin only.
    Returns name (from email), email, role, status (active/disabled), created_at, last_login.
    """
    organization_id = _ensure_org_and_same_org(current_user)
    db = get_db()
    users_ref = db.collection("users").where("organization_id", "==", organization_id)
    users = list(users_ref.stream())
    result = []
    for doc in users:
        d = doc.to_dict()
        result.append({
            "uid": doc.id,
            "email": d.get("email"),
            "name": (d.get("email") or "").split("@")[0],
            "role": d.get("role", "employee"),
            "status": "disabled" if d.get("disabled") else "active",
            "created_at": d.get("created_at") or d.get("createdAt"),
            "last_login": d.get("last_login"),
            "must_change_password": d.get("must_change_password", False),
        })
    result.sort(key=lambda x: (x.get("created_at") or ""), reverse=True)
    return {"users": result}


@router.post("/create-support-admin")
async def create_support_admin(
    body: CreateSupportAdminRequest,
    current_user: dict = Depends(require_super_admin),
):
    """
    Create a support admin user in the same organization. Super_admin only.
    """
    organization_id = _ensure_org_and_same_org(current_user)

    email = body.email.strip().lower()
    password = (body.temporary_password or "").strip()
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    try:
        user_record = firebase_auth.create_user(
            email=email,
            password=password,
            email_verified=False,
        )
        uid = user_record.uid
    except firebase_auth.EmailAlreadyExistsError:
        raise HTTPException(status_code=400, detail="Email already registered")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not create user: {str(e)}")

    db = get_db()
    db.collection("users").document(uid).set({
        "uid": uid,
        "email": email,
        "role": "support_admin",
        "organization_id": organization_id,
        "must_change_password": True,
        "created_at": datetime.utcnow().isoformat(),
        "createdAt": datetime.utcnow().isoformat(),
    })

    return {
        "message": "Support admin created successfully",
        "uid": uid,
        "email": email,
        "role": "support_admin",
        "must_change_password": True,
    }


@router.post("/reset-support-admin-password")
async def reset_support_admin_password(
    body: ResetSupportAdminPasswordRequest,
    current_user: dict = Depends(require_super_admin),
):
    """
    Reset a support admin's password. Super_admin only. Forces must_change_password = True.
    """
    _ensure_org_and_same_org(current_user, body.uid)
    new_password = (body.new_password or "").strip()
    if len(new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    try:
        firebase_auth.update_user(body.uid, password=new_password)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to update password: {str(e)}")
    db = get_db()
    db.collection("users").document(body.uid).update({
        "must_change_password": True,
        "updated_at": datetime.utcnow().isoformat(),
    })
    return {"message": "Password reset successfully"}


@router.put("/disable-support-admin/{uid}")
async def disable_support_admin(
    uid: str,
    current_user: dict = Depends(require_super_admin),
):
    """
    Disable a support admin (or any non-super_admin user in org). Super_admin cannot be disabled.
    """
    organization_id = _ensure_org_and_same_org(current_user, uid)
    db = get_db()
    user_doc = db.collection("users").document(uid).get()
    if not user_doc.exists:
        raise HTTPException(status_code=404, detail="User not found")
    user_data = user_doc.to_dict()
    if user_data.get("role") == "super_admin" or (user_data.get("role") == "admin" and not user_data.get("organization_id")):
        raise HTTPException(status_code=403, detail="Cannot disable super admin")
    if user_data.get("organization_id") != organization_id:
        raise HTTPException(status_code=404, detail="User not in your organization")
    db.collection("users").document(uid).update({
        "disabled": True,
        "updated_at": datetime.utcnow().isoformat(),
    })
    return {"message": "User disabled"}


@router.put("/enable-support-admin/{uid}")
async def enable_support_admin(
    uid: str,
    current_user: dict = Depends(require_super_admin),
):
    """Re-enable a disabled user. Super_admin only."""
    _ensure_org_and_same_org(current_user, uid)
    db = get_db()
    user_doc = db.collection("users").document(uid).get()
    if not user_doc.exists or user_doc.to_dict().get("organization_id") != current_user.get("organization_id"):
        raise HTTPException(status_code=404, detail="User not found")
    db.collection("users").document(uid).update({
        "disabled": False,
        "updated_at": datetime.utcnow().isoformat(),
    })
    return {"message": "User enabled"}


@router.delete("/support-admin/{uid}")
async def delete_support_admin(
    uid: str,
    current_user: dict = Depends(require_super_admin),
):
    """
    Delete a support admin from Firebase Auth and Firestore. Super_admin only.
    Cannot delete super_admin or self.
    """
    if uid == current_user["uid"]:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")
    organization_id = _ensure_org_and_same_org(current_user, uid)
    db = get_db()
    user_doc = db.collection("users").document(uid).get()
    if not user_doc.exists:
        raise HTTPException(status_code=404, detail="User not found")
    user_data = user_doc.to_dict()
    if user_data.get("role") == "super_admin":
        raise HTTPException(status_code=403, detail="Cannot delete super admin")
    if user_data.get("organization_id") != organization_id:
        raise HTTPException(status_code=404, detail="User not in your organization")
    try:
        firebase_auth.delete_user(uid)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to delete user: {str(e)}")
    db.collection("users").document(uid).delete()
    return {"message": "User deleted"}
