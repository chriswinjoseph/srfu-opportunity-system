# Requirements for Sprint 1 Week 1

## Functional Requirements

### User Sign Up

The system shall allow a new user to create an account by entering their first name, last name, email address and password.

The Sign-Up page shall also display an **“Already have an account? Log in”** option. Selecting **“Log in”** shall take the user to the Login page.

### User Login

The system shall allow an existing registered user to log in using their email address and password.

The Login page shall also display a **“Don’t have an account? Sign up”** option. Selecting **“Sign up”** shall take the user to the Sign-Up page.

### Password Visibility

The user shall be able to show or hide the entered password using a visibility icon.

### Login Validation

The system shall display a clear error message when the user enters invalid login credentials or leaves required fields empty.

### Forgot Password

The Login page shall provide a **Forgot Password** option that allows the user to request a password reset.

### Successful Login Redirect

After successful authentication, the user shall be redirected to the main authenticated area of the system, such as the dashboard.

### Logout

An authenticated user shall be able to log out, ending their current session and returning them to the Login page.

---

## Non-Functional Requirements

### Usability

The Login page should be simple and require minimal steps to access the system.

### Responsive Design

The Login page shall remain usable and readable on desktop and mobile screen sizes.

### Accessibility

Input fields and buttons shall have clear labels, readable error messages and keyboard-accessible controls.

### Security

Passwords shall be hidden by default, and unauthenticated users shall not be able to access protected pages.

---

# User Stories and Acceptance Criteria

## Sign Up

### User Story

As a new user, I want to create an account using my personal details so that I can log in and access the system.

### Acceptance Criteria

- First Name, Last Name, Email and Password fields are displayed.
- The password must be at least 8 characters and contain:
  - At least one uppercase letter, e.g. A, B, C.
  - At least one lowercase letter, e.g. a, b, c.
  - At least one number, e.g. 1, 2, 3.
  - At least one special character, e.g. !, @, #.
- All fields are required.
- The email must be entered in a valid email format.
- The user can submit the form to create a new account.
- The Sign-Up page displays an **“Already have an account? Log in”** option.
- Selecting **“Log in”** takes the user to the Login page.

---

## Login

### User Story

As an authorised SRFU user, I want to log in using my email and password so that I can access the system.

### Acceptance Criteria

- Email and Password fields are displayed.
- Both fields are required.
- Valid credentials successfully log the user in.
- Successful login redirects the user to the authenticated system or dashboard.
- Invalid credentials display an appropriate error message.
- The Login page displays a **“Don’t have an account? Sign up”** option.
- Selecting **“Sign up”** takes the user to the Sign-Up page.

---

## Password Visibility

### User Story

As a user, I want to show or hide my password so that I can check what I have entered before logging in.

### Acceptance Criteria

- Password is hidden by default.
- A visibility icon is displayed beside the password field.
- Selecting the icon shows the password.
- Selecting it again hides the password.

---

## Forgot Password

### User Story

As a user who has forgotten my password, I want to request a password reset so that I can regain access to my account.

### Acceptance Criteria

- A **Forgot Password** option is available from the Login page.
- The user can enter their email address to request a reset.
- The system displays confirmation that the request has been processed.

---

## Logout

### User Story

As an authenticated user, I want to log out of the system so that my account is no longer accessible from the current session.

### Acceptance Criteria

- A Logout option is available to authenticated users.
- Selecting Logout ends the user's session.
- The user is redirected to the Login page.
- Protected pages cannot be accessed without logging in again.

---

## Login/Signup Error Handling

### User Story

As a user, I want clear feedback when login or sign-up fails so that I know what information I need to correct.

### Acceptance Criteria

- Empty required fields display validation feedback.
- Incorrect login credentials display a clear error message.
- Invalid sign-up information displays appropriate validation feedback.
- Error messages do not remove the user's ability to try again.
- The page layout remains unchanged when an error is displayed.