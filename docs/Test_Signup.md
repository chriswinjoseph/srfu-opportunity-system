# Sprint 1 - Dev 2 Testing Results

**Role:** Dev 2 - Savio Simon  
**Sprint:** Sprint 1  
**Test Date:** 23/08/2026  

---

## Sign-up and Login Testing

### Purpose

The purpose of this testing was to verify that the sign-up and login functionality implemented by Dev 1 works correctly and meets the documented requirements.

### Test Results

| Test | Expected Result | Actual Result | Status |
|---|---|---|---|
| Sign up with valid details | User account should be created successfully | Account was created successfully | PASS |
| Sign-up required fields | User should not be able to submit the form when required fields are empty | Form prevented submission when required fields were empty | PASS |
| Navigate from Sign-up to Login | User should be able to navigate to the Login page | Login page opened correctly | PASS |
| Login with valid credentials | User should successfully log in and be redirected to the appropriate page | Login was successful and user was redirected correctly | PASS |
| Login with invalid credentials | User should not be logged in and an appropriate error should be displayed | Invalid login was rejected and an error message was displayed | PASS |
| Login required fields | User should not be able to submit the login form with required fields empty | Form prevented submission when required fields were empty | PASS |
| Logout | Logged-in user should be able to log out successfully | User was logged out successfully | PASS |
| Access after logout | Protected pages should not be accessible after logout | User was redirected away from the protected page | PASS |

### Testing Outcome

The sign-up and login functionality was tested successfully. All tested functions worked as expected and no functional issues or defects were identified during testing.

---