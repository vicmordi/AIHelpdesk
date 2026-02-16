"""
Admin-only routes. create-support-admin is super_admin only.
"""

from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, EmailStr
from firebase_admin import auth as firebase_auth, firestore

from middleware import require_super_admin

router = APIRouter()


def get_db():
    return firestore.client()


class CreateSupportAdminRequest(BaseModel):
    email: EmailStr
    temporary_password: str


@router.post("/create-support-admin")
async def create_support_admin(
    body: CreateSupportAdminRequest,
    current_user: dict = Depends(require_super_admin),
):
    """
    Create a support admin user in the same organization. Super_admin only.
    Creates Firebase Auth user and Firestore user doc with role=support_admin, must_change_password=True.
    """
    organization_id = current_user.get("organization_id")
    if not organization_id:
        raise HTTPException(status_code=400, detail="Organization required to create support admins")

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
