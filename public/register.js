/**
 * Registration Page JavaScript
 */

// Show/hide admin code field based on role selection
document.getElementById('register-role').addEventListener('change', (e) => {
    const adminCodeGroup = document.getElementById('admin-code-group');
    const adminCodeInput = document.getElementById('admin-code');
    
    if (e.target.value === 'admin') {
        adminCodeGroup.style.display = 'block';
        adminCodeInput.required = true;
    } else {
        adminCodeGroup.style.display = 'none';
        adminCodeInput.required = false;
        adminCodeInput.value = '';
    }
});

// Register form handler
document.getElementById('register-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    
    const email = document.getElementById('register-email').value;
    const password = document.getElementById('register-password').value;
    const role = document.getElementById('register-role').value;
    const adminCode = document.getElementById('admin-code').value;
    const errorMessage = document.getElementById('error-message');
    const successMessage = document.getElementById('success-message');
    
    // Hide previous messages
    errorMessage.style.display = 'none';
    successMessage.style.display = 'none';
    
    // Validate admin code if admin role is selected
    if (role === 'admin' && !adminCode) {
        errorMessage.textContent = 'Admin access code is required for administrator accounts.';
        errorMessage.style.display = 'flex';
        return;
    }
    
    try {
        // Create user with Firebase Auth
        const userCredential = await auth.createUserWithEmailAndPassword(email, password);
        
        // Create user document in Firestore via backend
        const token = await userCredential.user.getIdToken();
        const response = await fetch(`${API_BASE_URL}/auth/register`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`
            },
            body: JSON.stringify({
                email: email,
                role: role,
                admin_code: role === 'admin' ? adminCode : null
            })
        });
        
        if (response.ok) {
            const data = await response.json();
            successMessage.textContent = `Account created successfully as ${data.role}! Redirecting...`;
            successMessage.style.display = 'flex';
            
            // Redirect based on role
            setTimeout(() => {
                if (data.role === 'admin') {
                    window.location.href = 'admin.html';
                } else {
                    window.location.href = 'submit-ticket.html';
                }
            }, 1500);
        } else {
            const error = await response.json();
            throw new Error(error.detail || 'Registration failed');
        }
        
    } catch (error) {
        errorMessage.textContent = getErrorMessage(error.code || error.message);
        errorMessage.style.display = 'flex';
    }
});

/**
 * Get user-friendly error messages
 */
function getErrorMessage(errorCode) {
    const errorMessages = {
        'auth/user-not-found': 'No account found with this email.',
        'auth/wrong-password': 'Incorrect password.',
        'auth/email-already-in-use': 'This email is already registered.',
        'auth/weak-password': 'Password should be at least 6 characters.',
        'auth/invalid-email': 'Invalid email address.',
        'auth/network-request-failed': 'Network error. Please check your connection.'
    };
    
    return errorMessages[errorCode] || `Error: ${errorCode || 'Unknown error'}`;
}
