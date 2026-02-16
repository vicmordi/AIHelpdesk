"""
Authentication middleware for verifying Firebase tokens
"""

from fastapi import HTTPException, Header, Depends
from firebase_admin import auth as firebase_auth
from typing import Optional

async def verify_token(authorization: Optional[str] = Header(None)) -> dict:
    """
    Verify Firebase ID token from Authorization header
    Returns the decoded token with user information
    """
    if not authorization:
        raise HTTPException(
            status_code=401,
            detail="Authorization header missing"
        )
    
    try:
        # Extract token from "Bearer <token>"
        scheme, token = authorization.split()
        if scheme.lower() != "bearer":
            raise HTTPException(
                status_code=401,
                detail="Invalid authentication scheme"
            )
    except ValueError:
        raise HTTPException(
            status_code=401,
            detail="Invalid authorization header format"
        )
    
    try:
        decoded_token = firebase_auth.verify_id_token(token)
        return decoded_token
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


async def verify_admin(decoded_token: dict = Depends(verify_token)) -> dict:
    """
    Verify that the user is an admin
    """
    uid = decoded_token.get("uid")
    
    # Get user role from Firestore (lazy initialization)
    from firebase_admin import firestore
    db = firestore.client()
    user_ref = db.collection("users").document(uid)
    user_doc = user_ref.get()
    
    if not user_doc.exists:
        raise HTTPException(
            status_code=403,
            detail="User not found in database"
        )
    
    user_data = user_doc.to_dict()
    user_role = user_data.get("role", "employee")
    if user_role != "admin":
        raise HTTPException(
            status_code=403,
            detail="Admin access required. Current role: " + user_role
        )
    
    return decoded_token
