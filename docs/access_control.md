# Login and Access Control

## What this feature does

Users must log in before they can view the dashboard, banks, clubs, branches or outreach information.

## After login

After a successful login, the user is taken directly to the main outreach dashboard.

## Protected pages

A logged-out user cannot open:

* The outreach dashboard
* The bank list
* Organisation details
* The positive-response feature

If a logged-out user tries to open one of these pages, the system sends them to the login page.

## Logout

The dashboard includes a Log out button. After logging out, the user cannot return to a protected page without signing in again.

## Session expiry

The user is automatically logged out after one hour without activity. The session also ends when the browser is completely closed.

## Testing completed

The feature was tested to confirm that:

* Login opens the correct dashboard
* Logged-out users cannot open protected pages
* The old dashboard redirects to the new dashboard
* Logout works correctly
* Session expiry settings are active
