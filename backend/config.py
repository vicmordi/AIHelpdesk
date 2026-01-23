"""
Configuration and Firebase initialization
"""

import os
import sys
import firebase_admin
from firebase_admin import credentials, firestore, auth
from dotenv import load_dotenv

# Load environment variables from .env file
# Try loading from parent directory (project root) first
env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')
if os.path.exists(env_path):
    load_dotenv(env_path)
else:
    # Try current directory
    load_dotenv()

# Initialize Firebase Admin SDK
SERVICE_ACCOUNT_PATH = os.getenv("FIREBASE_SERVICE_ACCOUNT_PATH")
GOOGLE_APPLICATION_CREDENTIALS = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

# Project root directory (where .env file is located)
PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))

# Helper function to resolve path relative to project root
def resolve_path(path):
    """Resolve a path relative to the project root or current directory"""
    if os.path.isabs(path):
        return os.path.expanduser(path)
    
    # Remove leading ./ or .\ if present
    clean_path = path.lstrip('./').lstrip('.\\')
    
    # Try relative to project root first (where .env file is)
    resolved = os.path.join(PROJECT_ROOT, clean_path)
    if os.path.exists(resolved):
        return os.path.abspath(resolved)
    
    # Try relative to current working directory
    cwd_resolved = os.path.abspath(os.path.expanduser(path))
    if os.path.exists(cwd_resolved):
        return cwd_resolved
    
    # Return absolute path anyway (will fail later with better error)
    return os.path.abspath(os.path.join(PROJECT_ROOT, clean_path))

if not firebase_admin._apps:
    # Try to find service account file
    if SERVICE_ACCOUNT_PATH:
        # Resolve path relative to project root or current directory
        SERVICE_ACCOUNT_PATH = resolve_path(SERVICE_ACCOUNT_PATH)
        if os.path.exists(SERVICE_ACCOUNT_PATH):
            try:
                cred = credentials.Certificate(SERVICE_ACCOUNT_PATH)
                firebase_admin.initialize_app(cred)
                print(f"✓ Firebase initialized using service account: {SERVICE_ACCOUNT_PATH}")
            except Exception as e:
                print(f"✗ Error loading service account from {SERVICE_ACCOUNT_PATH}: {e}")
                sys.exit(1)
        else:
            print(f"✗ Service account file not found: {SERVICE_ACCOUNT_PATH}")
            print("\nPlease:")
            print("1. Download your Firebase service account key from Firebase Console")
            print("2. Save it in your project directory")
            print("3. Update FIREBASE_SERVICE_ACCOUNT_PATH in your .env file")
            sys.exit(1)
    elif GOOGLE_APPLICATION_CREDENTIALS:
        # Try using GOOGLE_APPLICATION_CREDENTIALS environment variable
        try:
            firebase_admin.initialize_app()
            print(f"✓ Firebase initialized using GOOGLE_APPLICATION_CREDENTIALS")
        except Exception as e:
            print(f"✗ Error initializing Firebase with default credentials: {e}")
            sys.exit(1)
    else:
        # Try to find serviceAccountKey.json in common locations
        possible_paths = [
            os.path.join(os.path.dirname(os.path.dirname(__file__)), 'serviceAccountKey.json'),
            os.path.join(os.path.dirname(__file__), 'serviceAccountKey.json'),
            './serviceAccountKey.json',
            '../serviceAccountKey.json'
        ]
        
        found = False
        for path in possible_paths:
            expanded_path = os.path.expanduser(path)
            if os.path.exists(expanded_path):
                try:
                    cred = credentials.Certificate(expanded_path)
                    firebase_admin.initialize_app(cred)
                    print(f"✓ Firebase initialized using: {expanded_path}")
                    found = True
                    break
                except Exception as e:
                    continue
        
        if not found:
            print("✗ Firebase credentials not found!")
            print("\nPlease set up Firebase credentials using one of these methods:")
            print("\nMethod 1 (Recommended):")
            print("1. Download your Firebase service account key from Firebase Console")
            print("   (Project Settings > Service Accounts > Generate new private key)")
            print("2. Save it as 'serviceAccountKey.json' in the project root")
            print("3. Or create a .env file in the project root with:")
            print("   FIREBASE_SERVICE_ACCOUNT_PATH=./serviceAccountKey.json")
            print("\nMethod 2:")
            print("Set the GOOGLE_APPLICATION_CREDENTIALS environment variable:")
            print("export GOOGLE_APPLICATION_CREDENTIALS=/path/to/serviceAccountKey.json")
            sys.exit(1)

# Get Firestore client
try:
    db = firestore.client()
except Exception as e:
    print(f"✗ Error connecting to Firestore: {e}")
    sys.exit(1)

# OpenAI API Key
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    print("✗ OPENAI_API_KEY environment variable is required")
    print("\nPlease create a .env file in the project root with:")
    print("OPENAI_API_KEY=your_openai_api_key_here")
    sys.exit(1)
else:
    print("✓ OpenAI API key found")

# Admin Access Code - Required for admin role assignment during registration
ADMIN_ACCESS_CODE = os.getenv("ADMIN_ACCESS_CODE", "")
