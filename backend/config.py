"""
Configuration - Environment variables only
Firebase Admin SDK is initialized in main.py using environment variables.
"""

import os

# OpenAI API Key
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    # Don't exit - let the app start and fail gracefully if needed
    # This allows Render to start the app even if env vars aren't set yet
    pass

# Admin Access Code - Required for admin role assignment during registration
ADMIN_ACCESS_CODE = os.getenv("ADMIN_ACCESS_CODE", "")
