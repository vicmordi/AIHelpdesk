# Quick Start Guide

This guide will help you get the AI Helpdesk application running quickly.

## Prerequisites

- Python 3.8 or higher
- Node.js (optional, for serving frontend)
- Firebase account
- OpenAI API key

## Step-by-Step Setup

### 1. Clone and Navigate
```bash
cd AIHelpdesk
```

### 2. Firebase Setup (5 minutes)

1. Go to [Firebase Console](https://console.firebase.google.com/)
2. Create a new project
3. Enable **Firestore Database** (start in test mode, we'll add rules later)
4. Enable **Authentication** → Sign-in method → Email/Password → Enable
5. Go to Project Settings → Service Accounts → Generate new private key
6. Save the JSON file as `serviceAccountKey.json` in the project root
7. Go to Project Settings → General → Your apps → Add web app
8. Copy the Firebase config values

### 3. Backend Setup (3 minutes)

```bash
# Create virtual environment (recommended)
cd backend
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Create .env file in project root
cd ..
# Create .env file with:
# FIREBASE_SERVICE_ACCOUNT_PATH=./serviceAccountKey.json
# OPENAI_API_KEY=your_key_here
```

Edit `.env`:
```env
FIREBASE_SERVICE_ACCOUNT_PATH=./serviceAccountKey.json
OPENAI_API_KEY=sk-your-openai-key-here
```

### 4. Frontend Setup (2 minutes)

Edit `frontend/firebase-config.js`:
```javascript
const firebaseConfig = {
    apiKey: "YOUR_API_KEY",
    authDomain: "YOUR_PROJECT_ID.firebaseapp.com",
    projectId: "YOUR_PROJECT_ID",
    storageBucket: "YOUR_PROJECT_ID.appspot.com",
    messagingSenderId: "YOUR_MESSAGING_SENDER_ID",
    appId: "YOUR_APP_ID"
};
```

### 5. Deploy Firestore Rules (1 minute)

1. Go to Firebase Console → Firestore Database → Rules
2. Copy contents of `firestore.rules`
3. Paste and Publish

### 6. Run the Application

**Terminal 1 - Backend:**
```bash
cd backend
source venv/bin/activate  # On Windows: venv\Scripts\activate
python main.py
```
Backend runs on `http://localhost:8000`

**Terminal 2 - Frontend:**
```bash
cd frontend
python -m http.server 8080
# OR
npx http-server -p 8080
```
Frontend runs on `http://localhost:8080`

### 7. Create Admin User

1. Open `http://localhost:8080/login.html`
2. Register a new account
3. Go to Firebase Console → Firestore → `users` collection
4. Find your user document
5. Edit and change `role` from `"user"` to `"admin"`
6. Logout and login again

### 8. Test the Application

1. **As Admin:**
   - Login → You'll see Admin Dashboard
   - Add a knowledge base article (e.g., "How to reset password: Go to settings...")
   - Check "Escalated Tickets" tab

2. **As User:**
   - Register a new account (or use existing with user role)
   - Submit a ticket related to your knowledge base article
   - See AI auto-resolve it!
   - Submit a ticket about something not in knowledge base
   - See it get escalated

## Troubleshooting

**Backend won't start:**
- Check `.env` file exists and has correct paths
- Verify `serviceAccountKey.json` is in the right location
- Check Python version: `python --version` (need 3.8+)

**Frontend can't connect to backend:**
- Verify backend is running on port 8000
- Check `API_BASE_URL` in `firebase-config.js`
- Check browser console for CORS errors

**Firebase errors:**
- Verify Firebase config in `firebase-config.js`
- Check Firestore rules are deployed
- Verify Authentication is enabled

**OpenAI errors:**
- Check API key is correct
- Verify you have credits in your OpenAI account
- Check API key has proper permissions

## Next Steps

- Add more knowledge base articles
- Test different ticket scenarios
- Customize the AI prompt in `backend/routes/tickets.py`
- Adjust confidence threshold (currently 0.7)

## API Documentation

Once backend is running, visit:
- `http://localhost:8000/docs` - Interactive API documentation
- `http://localhost:8000/redoc` - Alternative API docs
