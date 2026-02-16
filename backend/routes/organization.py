"""
Organization settings. update-code is super_admin only.
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from firebase_admin import firestore

from middleware import require_super_admin

router = APIRouter()


def get_db():
    return firestore.client()


class UpdateCodeRequest(BaseModel):
    organization_code: str


@router.put("/update-code")
async def update_organization_code(
    body: UpdateCodeRequest,
    current_user: dict = Depends(require_super_admin),
):
    """
    Update the organization's organization_code. Super_admin only. Ensures uniqueness.
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

    # Check uniqueness (excluding current org)
    existing = db.collection("organizations").where("organization_code", "==", code).stream()
    for doc in existing:
        if doc.id != organization_id:
            raise HTTPException(status_code=400, detail="Organization code already in use")

    org_ref.update({"organization_code": code})
    return {"message": "Organization code updated successfully", "organization_code": code}
