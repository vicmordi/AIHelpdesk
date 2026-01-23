# Role-Based Access Control Implementation

This document describes the role-based access control (RBAC) system implemented in the AI Helpdesk application.

## Overview

The system supports two user roles:
- **Employee** (default): Can submit tickets and view their own tickets
- **Admin**: Can manage knowledge base, view all tickets, and access escalated tickets

## Role Assignment

### During Registration

1. **Default Role**: All new users are assigned the "employee" role by default
2. **Admin Role**: Requires a valid admin access code during registration
3. **Security**: Admin access code is stored in environment variable `ADMIN_ACCESS_CODE`

### Registration Flow

1. User selects account type (Employee or Administrator)
2. If "Administrator" is selected, admin code input field appears
3. User must provide valid admin access code
4. Backend validates the code before assigning admin role
5. If code is invalid, registration fails with error message

## Backend Implementation

### Environment Variable

Add to `.env` file:
```env
ADMIN_ACCESS_CODE=your_secure_admin_code_here
```

### Registration Endpoint (`/auth/register`)

- Validates admin code if admin role is requested
- Defaults to "employee" role if role is invalid
- Returns 403 error if admin code is missing or incorrect
- Stores role in Firestore user document

### Role Checks

- `verify_admin()` middleware: Blocks non-admin users from admin endpoints
- Admin-only endpoints:
  - `GET /knowledge-base` - View all articles
  - `POST /knowledge-base` - Create articles
  - `DELETE /knowledge-base/{id}` - Delete articles
  - `GET /tickets` - View all tickets
  - `GET /tickets/escalated` - View escalated tickets

### Employee Endpoints

- `POST /tickets` - Submit ticket (all authenticated users)
- `GET /tickets/my-tickets` - View own tickets (all authenticated users)

## Frontend Implementation

### Registration Page (`login.html`)

- Added role selector dropdown (Employee/Administrator)
- Admin code input field (shown only when Administrator is selected)
- Client-side validation for admin code requirement

### Role-Based Redirects

- **Admin users**: Redirected to `admin.html` after login/registration
- **Employee users**: Redirected to `submit-ticket.html` after login/registration
- **Access control**: 
  - Admins accessing employee page → redirected to admin dashboard
  - Employees accessing admin page → redirected to employee page with error

### UI Features

- Admin dashboard shows knowledge base management and escalated tickets
- Employee page shows ticket submission and personal ticket history
- Role is displayed in user profile area

## Firestore Security Rules

### User Collection
- Users can read their own user document
- Users can create their own document during registration
- Admins can modify any user document

### Knowledge Base Collection
- **Read/Write**: Admin only

### Tickets Collection
- **Create**: All authenticated users (for their own tickets)
- **Read**: Users can read their own tickets, admins can read all tickets
- **Update/Delete**: Admin only

## Data Model

### User Document Structure
```json
{
  "uid": "firebase-user-id",
  "email": "user@example.com",
  "role": "employee" | "admin",
  "createdAt": "2024-01-01T00:00:00.000Z"
}
```

## Security Considerations

1. **Admin Code**: Store in environment variable, never commit to version control
2. **Role Validation**: Always validated on backend, frontend validation is for UX only
3. **Token Verification**: All endpoints verify Firebase ID tokens
4. **Firestore Rules**: Enforce access control at database level

## Testing

### Test Admin Registration
1. Go to registration page
2. Select "Administrator" role
3. Enter valid admin code (from `.env` file)
4. Complete registration
5. Should redirect to admin dashboard

### Test Employee Registration
1. Go to registration page
2. Select "Employee" role (or leave default)
3. Complete registration (no admin code needed)
4. Should redirect to ticket submission page

### Test Access Control
1. As employee, try to access `/admin.html` → should redirect with error
2. As admin, try to access `/submit-ticket.html` → should redirect to admin dashboard
3. As employee, try to access admin API endpoints → should return 403 error

## Migration Notes

- Existing users with role "user" will continue to work (treated as "employee")
- To convert existing user to admin:
  1. Update Firestore document: `users/{uid}` → set `role: "admin"`
  2. Or re-register with admin code

## Troubleshooting

### Admin registration fails
- Check `ADMIN_ACCESS_CODE` is set in `.env` file
- Verify admin code matches exactly (case-sensitive)
- Check backend logs for validation errors

### Role not working after registration
- Verify user document in Firestore has correct role field
- Check Firestore security rules are deployed
- Verify backend middleware is checking roles correctly
