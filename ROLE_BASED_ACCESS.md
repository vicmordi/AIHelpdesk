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

