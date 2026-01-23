# AI Helpdesk Application

An MVP AI-powered helpdesk application with automatic ticket resolution using OpenAI and Firebase.

## Features

- **Role-based Authentication**: Admin and User roles with Firebase Authentication
- **Knowledge Base Management**: Admins can create and manage knowledge base articles
- **AI-Powered Ticket Resolution**: Automatic ticket analysis and resolution using OpenAI
- **Smart Escalation**: Tickets are escalated when AI confidence is low or no solution is found
- **Real-time Ticket Tracking**: Users can view their tickets and responses

## Tech Stack

### Backend
- Python 3.8+
- FastAPI
- Firebase Admin SDK
- Firestore (database)
- OpenAI API

### Frontend
- Plain HTML, CSS, and Vanilla JavaScript
- Firebase Authentication
- No frontend frameworks

## Setup Instructions

### 1. Firebase Setup

1. **Create a Firebase Project**
   - Go to [Firebase Console](https://console.firebase.google.com/)
   - Create a new project
   - Enable Firestore Database
   - Enable Authentication (Email/Password)

2. **Get Firebase Configuration**
   - Go to Project Settings > General
   - Scroll down to "Your apps" and add a web app
   - Copy the Firebase configuration object

3. **Download Service Account Key**
   - Go to Project Settings > Service Accounts
   - Click "Generate new private key"
   - Save the JSON file securely (e.g., `serviceAccountKey.json`)

4. **Update Firestore Security Rules**
   - Go to Firestore Database > Rules
   - Copy the contents of `firestore.rules` and paste them
   - Publish the rules

5. **Update Frontend Configuration**
   - Open `frontend/firebase-config.js`
   - Replace the placeholder values with your Firebase config:
     ```javascript
     const firebaseConfig = {
         apiKey: "YOUR_API_KEY",
         authDomain: "YOUR_PROJECT_ID.firebaseapp.com",
         projectId: "YOUR_PROJECT_ID",
         // ... etc
     };
     ```

### 2. Backend Setup

1. **Install Python Dependencies**
   ```bash
   cd backend
   pip install -r requirements.txt
   ```

2. **Configure Environment Variables**
   ```bash
   # Copy the example env file
   cp ../.env.example ../.env
   
   # Edit .env and add your configuration
   # FIREBASE_SERVICE_ACCOUNT_PATH=path/to/serviceAccountKey.json
   # OPENAI_API_KEY=your_openai_api_key
   ```

3. **Get OpenAI API Key**
   - Go to [OpenAI Platform](https://platform.openai.com/)
   - Create an account and get your API key
   - Add it to your `.env` file

4. **Run the Backend**
   ```bash
   # From the backend directory
   python main.py
   
   # Or using uvicorn directly
   uvicorn main:app --reload --host 0.0.0.0 --port 8000
   ```

   The API will be available at `http://localhost:8000`

### 3. Frontend Setup

1. **Update API Base URL**
   - Open `frontend/firebase-config.js`
   - Update `API_BASE_URL` if your backend is running on a different port:
     ```javascript
     const API_BASE_URL = "http://localhost:8000";
     ```

2. **Serve the Frontend**
   - You can use any static file server
   - Using Python:
     ```bash
     cd frontend
     python -m http.server 8080
     ```
   - Using Node.js:
     ```bash
     cd frontend
     npx http-server -p 8080
     ```
   - Or simply open the HTML files in a browser (may have CORS issues with API calls)

3. **Access the Application**
   - Open `http://localhost:8080/login.html` in your browser

### 4. Create Admin User

1. **Register a User**
   - Go to the login page
   - Register a new account using the registration form

2. **Set Admin Role**
   - Go to Firebase Console > Firestore Database
   - Find the `users` collection
   - Find your user document (by email or UID)
   - Edit the document and set `role` to `"admin"`
   - Save

3. **Logout and Login Again**
   - You should now have admin access

## Project Structure

```
AIHelpdesk/
├── backend/
│   ├── main.py                 # FastAPI application entry point
│   ├── config.py               # Firebase and OpenAI configuration
│   ├── middleware.py           # Authentication middleware
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── auth.py             # Authentication routes
│   │   ├── knowledge_base.py   # Knowledge base routes (admin)
│   │   └── tickets.py          # Ticket routes with AI resolution
│   └── requirements.txt        # Python dependencies
├── frontend/
│   ├── login.html              # Login/Register page
│   ├── admin.html              # Admin dashboard
│   ├── submit-ticket.html     # User ticket submission
│   ├── styles.css              # Global styles
│   ├── firebase-config.js      # Firebase configuration
│   ├── login.js                # Login page logic
│   ├── admin.js                # Admin dashboard logic
│   └── submit-ticket.js        # Ticket submission logic
├── firestore.rules             # Firestore security rules
├── .env.example                # Environment variables template
└── README.md                   # This file
```

## API Endpoints

### Authentication
- `POST /auth/register` - Register a new user
- `GET /auth/me` - Get current user info (requires auth)

### Knowledge Base (Admin Only)
- `POST /knowledge-base` - Create article
- `GET /knowledge-base` - Get all articles
- `DELETE /knowledge-base/{id}` - Delete article

### Tickets
- `POST /tickets` - Create ticket (with AI resolution)
- `GET /tickets/my-tickets` - Get user's tickets
- `GET /tickets` - Get all tickets (admin only)
- `GET /tickets/escalated` - Get escalated tickets (admin only)

## Data Models

### Users
```json
{
  "uid": "string",
  "email": "string",
  "role": "admin" | "user"
}
```

### Knowledge Base
```json
{
  "title": "string",
  "content": "string",
  "createdAt": "ISO datetime string"
}
```

### Tickets
```json
{
  "userId": "string",
  "message": "string",
  "summary": "string",
  "status": "auto_resolved" | "needs_escalation",
  "category": "Technical" | "Billing" | "Account" | "General" | null,
  "aiReply": "string" | null,
  "confidence": 0.0-1.0,
  "knowledge_used": ["string"],
  "internal_note": "string",
  "createdAt": "ISO datetime string"
}
```

## Security

- Firebase Authentication handles user authentication
- Firestore security rules enforce access control
- Backend middleware verifies Firebase tokens
- Role-based access control for admin functions
- Users can only access their own tickets

## AI Resolution Logic

1. When a ticket is submitted, all knowledge base articles are fetched
2. Ticket message + knowledge base is sent to OpenAI (GPT-3.5-turbo)
3. AI analyzes if the issue can be resolved automatically
4. If confidence ≥ 0.7 and solution found:
   - Status: `auto_resolved`
   - AI reply generated with step-by-step solution
5. If confidence < 0.7 or no solution:
   - Status: `needs_escalation`
   - Category assigned
   - Internal note added for human support

## Troubleshooting

### Backend Issues
- **Firebase initialization error**: Check that your service account JSON path is correct
- **OpenAI API error**: Verify your API key is correct and you have credits
- **CORS errors**: Make sure CORS middleware is configured correctly

### Frontend Issues
- **Firebase not initialized**: Check `firebase-config.js` has correct values
- **API calls failing**: Verify backend is running and `API_BASE_URL` is correct
- **Authentication errors**: Check Firebase Auth is enabled in Firebase Console

### Firestore Issues
- **Permission denied**: Check security rules are deployed correctly
- **User role not working**: Verify user document has `role` field set correctly

## Development Notes

- The application uses Firebase Admin SDK for backend operations
- Frontend uses Firebase Auth SDK for user authentication
- All API requests require a Bearer token (Firebase ID token)
- The AI prompt is designed to prevent hallucination and force JSON output
- Confidence threshold is set to 0.7 for auto-resolution

## License

This is an MVP project for demonstration purposes.
