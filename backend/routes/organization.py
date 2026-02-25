"""
Organization settings. Super_admin only. organization_id is primary; code is for display/login.
"""

from datetime import datetime
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from firebase_admin import firestore

from middleware import require_super_admin, get_current_user, require_admin_or_above
from schemas import STRICT_REQUEST_CONFIG

router = APIRouter()


def get_db():
    return firestore.client()


class UpdateCodeRequest(BaseModel):
    model_config = STRICT_REQUEST_CONFIG
    organization_code: str = Field(..., min_length=2, max_length=64)


class UpdateOrganizationRequest(BaseModel):
    model_config = STRICT_REQUEST_CONFIG
    name: Optional[str] = Field(None, min_length=1, max_length=256)
    organization_code: Optional[str] = Field(None, min_length=2, max_length=64)


@router.get("")
async def get_organization(current_user: dict = Depends(get_current_user)):
    """
    Get current user's organization (if any). Super_admin gets full details + stats.
    Returns 404 if user has no organization.
    """
    organization_id = current_user.get("organization_id")
    if not organization_id:
        raise HTTPException(status_code=404, detail="No organization")
    db = get_db()
    org_ref = db.collection("organizations").document(organization_id)
    org_doc = org_ref.get()
    if not org_doc.exists:
        raise HTTPException(status_code=404, detail="Organization not found")
    org_data = org_doc.to_dict()
    # Stats: total members, total tickets (scoped by org)
    users_snap = db.collection("users").where("organization_id", "==", organization_id).stream()
    total_members = sum(1 for _ in users_snap)
    tickets_snap = db.collection("tickets").where("organization_id", "==", organization_id).stream()
    total_tickets = sum(1 for _ in tickets_snap)
    return {
        "id": organization_id,
        "name": org_data.get("name"),
        "organization_code": org_data.get("organization_code"),
        "created_at": org_data.get("created_at"),
        "super_admin_uid": org_data.get("super_admin_uid"),
        "total_members": total_members,
        "total_tickets": total_tickets,
    }


@router.put("/update-code")
async def update_organization_code(
    body: UpdateCodeRequest,
    current_user: dict = Depends(require_super_admin),
):
    """
    Update the organization's organization_code. Super_admin only. Ensures uniqueness.
    Users remain linked via organization_id.
    """
    organization_id = current_user.get("organization_id")
    if not organization_id:
        raise HTTPException(status_code=400, detail="User has no organization")

    code = (body.organization_code or "").strip()
    if not code:
        raise HTTPException(status_code=400, detail="organization_code is required")

    db = get_db()
    org_ref = db.collection("organizations").document(organization_id)
    org_doc = org_ref.get()
    if not org_doc.exists:
        raise HTTPException(status_code=404, detail="Organization not found")

    existing = db.collection("organizations").where("organization_code", "==", code).stream()
    for doc in existing:
        if doc.id != organization_id:
            raise HTTPException(status_code=400, detail="Organization code already in use")

    org_ref.update({"organization_code": code})
    return {"message": "Organization code updated successfully", "organization_code": code}


@router.put("")
async def update_organization(
    body: UpdateOrganizationRequest,
    current_user: dict = Depends(require_super_admin),
):
    """
    Update organization name and/or code. Super_admin only. Code must stay unique.
    """
    organization_id = current_user.get("organization_id")
    if not organization_id:
        raise HTTPException(status_code=400, detail="User has no organization")
    db = get_db()
    org_ref = db.collection("organizations").document(organization_id)
    org_doc = org_ref.get()
    if not org_doc.exists:
        raise HTTPException(status_code=404, detail="Organization not found")
    updates = {}
    if body.name is not None and body.name.strip():
        updates["name"] = body.name.strip()
    if body.organization_code is not None:
        code = body.organization_code.strip()
        if code:
            existing = db.collection("organizations").where("organization_code", "==", code).stream()
            for doc in existing:
                if doc.id != organization_id:
                    raise HTTPException(status_code=400, detail="Organization code already in use")
            updates["organization_code"] = code
    if not updates:
        raise HTTPException(status_code=400, detail="No valid updates")
    org_ref.update(updates)
    return {"message": "Organization updated successfully"}


@router.get("/members")
async def get_organization_members(current_user: dict = Depends(require_admin_or_above)):
    """
    List org members (uid, email, role) for assign dropdown etc. Admin only.
    Excludes disabled users.
    """
    organization_id = current_user.get("organization_id")
    if not organization_id:
        raise HTTPException(status_code=404, detail="No organization")
    db = get_db()
    users_ref = db.collection("users").where("organization_id", "==", organization_id)
    members = []
    for doc in users_ref.stream():
        d = doc.to_dict()
        if d.get("disabled"):
            continue
        members.append({
            "uid": doc.id,
            "email": d.get("email"),
            "full_name": d.get("full_name") or "",
            "role": d.get("role", "employee"),
        })
    return {"members": members}
