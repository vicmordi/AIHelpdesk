# Environment Variables Template

Create a `.env` file in the project root with the following variables:

```env
# Firebase Configuration
# Path to your Firebase service account JSON file
FIREBASE_SERVICE_ACCOUNT_PATH=path/to/your/serviceAccountKey.json

# OpenAI API Key
OPENAI_API_KEY=your_openai_api_key_here

# Admin Access Code (Required for admin role assignment during registration)
# Set a secure code that users must provide to register as admin
ADMIN_ACCESS_CODE=your_secure_admin_code_here

# Optional: If using default credentials, set this instead
# GOOGLE_APPLICATION_CREDENTIALS=path/to/your/serviceAccountKey.json
```

## Instructions

1. Copy this template to create your `.env` file:
   ```bash
   cp ENV_TEMPLATE.md .env
   ```

2. Edit `.env` and replace the placeholder values:
   - `FIREBASE_SERVICE_ACCOUNT_PATH`: Path to your Firebase service account JSON file
   - `OPENAI_API_KEY`: Your OpenAI API key from https://platform.openai.com/

3. Make sure `.env` is in `.gitignore` (it should be by default)
