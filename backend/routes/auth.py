"""
Authentication routes
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime
from firebase_admin import auth as firebase_auth, firestore
from config import ADMIN_ACCESS_CODE
from middleware import verify_token

router = APIRouter()


def get_db():
    """Lazy initialization of Firestore client"""
    return firestore.client()


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RegisterRequest(BaseModel):
    email: Optional[EmailStr] = None  # Optional, will use token email if not provided
    password: Optional[str] = None  # Not used, user already created by Firebase Auth
    role: str = "employee"  # Default to employee, admin requires access code
    admin_code: Optional[str] = None  # Required if role is "admin"


@router.post("/login")
async def login(request: LoginRequest):
    """
    Login endpoint - validates credentials
    Note: Actual authentication is handled by Firebase Auth on the frontend
    This endpoint can be used to verify token and get user info
    """
    try:
        # In a real implementation, you'd verify the password here
        # For Firebase Auth, the frontend handles login and sends the token
        # This endpoint is mainly for documentation/verification purposes
        return {
            "message": "Login should be handled by Firebase Auth on the frontend",
            "note": "Use Firebase Auth SDK to sign in, then send the ID token to protected endpoints"
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/register")
async def register(request: RegisterRequest, decoded_token: dict = Depends(verify_token)):
    """
    Register endpoint - creates user document in Firestore
    Note: User should already be created in Firebase Auth by the frontend
    This endpoint just creates the Firestore document with role information
    """
    try:
        uid = decoded_token.get("uid")
        email = decoded_token.get("email") or request.email
        
        # Get Firestore client (lazy initialization)
        db = get_db()
        
        # Check if user document already exists
        user_ref = db.collection("users").document(uid)
        user_doc = user_ref.get()
        
        if user_doc.exists:
            # User already exists, return existing data
            user_data = user_doc.to_dict()
            return {
                "message": "User already registered",
                "uid": uid,
                "email": email,
                "role": user_data.get("role", "employee")
            }
        
        # Validate and assign role
        requested_role = request.role.lower() if request.role else "employee"
        
        # Security: Only allow "employee" or "admin" roles
        if requested_role not in ["employee", "admin"]:
            requested_role = "employee"
        
        # Security: Admin role requires valid access code
        if requested_role == "admin":
            if not ADMIN_ACCESS_CODE:
                raise HTTPException(
                    status_code=403,
                    detail="Admin registration is not configured. Please contact system administrator."
                )
            if not request.admin_code or request.admin_code != ADMIN_ACCESS_CODE:
                raise HTTPException(
                    status_code=403,
                    detail="Invalid admin access code. Admin role assignment denied."
                )
        
        # Create user document in Firestore with role and timestamp
        user_ref.set({
            "uid": uid,
            "email": email,
            "role": requested_role,
            "createdAt": datetime.utcnow().isoformat()
        })
        
        return {
            "message": "User registered successfully",
            "uid": uid,
            "email": email,
            "role": requested_role
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/me")
async def get_current_user(decoded_token: dict = Depends(verify_token)):
    """
    Get current user information
    """
    uid = decoded_token.get("uid")
    
    # Get Firestore client (lazy initialization)
    db = get_db()
    
    # Get user from Firestore
    user_ref = db.collection("users").document(uid)
    user_doc = user_ref.get()
    
    if not user_doc.exists:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )
    
    user_data = user_doc.to_dict()
    return {
        "uid": uid,
        "email": decoded_token.get("email"),
        "role": user_data.get("role", "employee")
    }
