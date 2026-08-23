Test Report — Login → Dashboard → Logout Flow
Tester: Savio Simon (Dev 2)
Date: 23 August 2026
Environment: Production (web-production-74dc0.up.railway.app)

Scope
Manual verification of the login flow after the password reset email fix and login page restyle were deployed.

Steps tested
Navigated to /accounts/login/ on the deployed production URL (not localhost).
Attempted sign-in with a valid email and an incorrect password.
Confirmed a clear error message displayed ("Please enter a correct email or password.") and the user remained on the login page.
Signed in with valid, correct credentials.
Confirmed automatic redirect to /accounts/dashboard/ on successful login, with the user's first name displayed.
Attempted to submit the login form with both fields left empty.
Confirmed the form blocked submission and the user remained on the login page.
Signed out via the Log out button.
Confirmed redirect back to /accounts/login/.
Attempted to navigate directly to /accounts/dashboard/ without an active session.
Confirmed the app redirected back to the login page instead of rendering the dashboard.
Result
Pass. No issues found across invalid credentials, valid login, empty-field validation, logout, and the logged-out redirect guard on the deployed build.

Notes
An automated Playwright test script (flow.spec.ts) covering this same flow has been written, but has not yet been run against the deployed environment — it has not been verified to pass. Treat it as a draft until executed. This manual pass is the only confirmed result at this time.
Password reset email delivery was separately broken and fixed earlier in this sprint (unverified sender address); this report does not re-cover that flow — see Task 6.
Next steps
Edge cases (duplicate email on signup, password complexity rejection messaging, forgot-password with a non-existent email, session expiry timing) to be tested and documented separately.

