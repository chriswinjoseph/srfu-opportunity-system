# Requirements and Acceptance Criteria: Admin Users, Roles and Permissions

## 1. Purpose

The system must control which pages and actions each user can access. The system will support two roles:

- **Admin**
- **Staff**

In this document, **Staff** refers to a normal system user.

Permissions must be checked by the server. Hiding a button or navigation link by itself is not sufficient protection.

## 2. Role Definitions

### Admin

An Admin has full control over the system and can:

- View the dashboard and organisation information.
- Add and edit organisations.
- Archive organisations.
- Generate and edit email drafts.
- Approve or reject email drafts.
- Approve their own email drafts without another Admin’s approval.
- Send approved email drafts.
- Create and manage user accounts.
- Promote a Staff user to Admin.
- Change another Admin to Staff.
- Disable and re-enable accounts.
- View user and email activity history.

### Staff

A Staff user can:

- View the dashboard.
- View organisation information.
- Search and filter organisations.
- Generate AI email drafts.
- Edit drafts they created or were assigned.
- Submit drafts to an Admin for approval.
- View approval decisions and rejection comments.
- Send an email after an Admin has approved it.
- View whether another user has already sent an email.

A Staff user cannot:

- Add, edit or archive organisations.
- Approve or reject email drafts.
- Access User Management.
- Create or manage accounts.
- Assign or change roles.
- Disable or re-enable users.
- Send an email before an Admin approves it.

## 3. Permissions Table

| Page or Action | Staff | Admin |
|---|---:|---:|
| Sign in and sign out | Yes | Yes |
| View dashboard | Yes | Yes |
| View organisation list and details | Yes | Yes |
| Search and filter organisations | Yes | Yes |
| Add an organisation | No | Yes |
| Edit an organisation | No | Yes |
| Archive an organisation | No | Yes |
| Generate an AI email draft | Yes | Yes |
| Edit own or assigned draft | Yes | Yes |
| Edit another user’s draft | No | Yes |
| Submit a draft for approval | Yes | Yes |
| View approval feedback | Yes | Yes |
| Approve an email draft | No | Yes |
| Reject or request changes to a draft | No | Yes |
| Approve own email draft | No | Yes |
| Send an unapproved email | No | No |
| Send an Admin-approved email | Yes | Yes |
| View email status and history | Yes | Yes |
| Access User Management | No | Yes |
| Create a Staff user | No | Yes |
| Create an Admin user | No | Yes |
| Promote Staff to Admin | No | Yes |
| Change another Admin to Staff | No | Yes |
| Change own role | No | No |
| Disable or re-enable another user | No | Yes |
| View user activity history | No | Yes |
| Change system settings | No | Yes |

## 4. Organisation Permissions

- Only an Admin may add an organisation.
- Only an Admin may edit an organisation.
- Only an Admin may archive an organisation.
- Staff may view organisation information.
- Staff may search and filter organisations.
- Staff must not see **Add Organisation**, **Edit Organisation** or **Archive Organisation** controls.
- Direct requests from Staff attempting to create, edit or archive an organisation must not change any information.

## 5. Draft-Email Permissions and Workflow

### Staff Draft Workflow

1. A Staff user generates or creates an email draft.
2. The Staff user edits the draft.
3. The Staff user selects **Submit for Approval**.
4. The status changes to **Pending Review**.
5. An Admin reviews the draft.
6. The Admin either approves the draft or requests changes.
7. If approved, the status changes to **Approved**.
8. The Staff user or an Admin may send the approved email.
9. After a successful send, the draft status changes to **Sent** and the organisation becomes **Contacted**.

### Admin Draft Workflow

- An Admin may generate, create or edit a draft.
- An Admin does not require approval from another Admin.
- The Admin may approve their own draft.
- The Admin may approve and send the draft themselves.
- Once the Admin marks the draft as approved, a Staff user may also send it.
- The Admin’s approval must still be recorded so Staff can confirm that the email is authorised for sending.

### Approval and Rejection Controls

- Only an Admin must see the **Approve** and **Reject** or **Request Changes** controls.
- Staff must not see these controls.
- Staff must not be shown approval actions that they cannot use.
- If a Staff user directly submits an unauthorised approval request, the draft must remain unchanged.
- An Admin may approve a draft they created or edited.
- Another Admin’s approval is not required.
- An Admin may reject a Staff draft and provide a reason.
- A rejected draft changes to **Changes Requested**.
- The Staff user can edit and resubmit the draft.

### Sending an Approved Email

- Staff and Admin may send an email only after an Admin has approved it.
- Approving the email must not send it automatically.
- The organisation must remain **Not Yet Contacted** until the email is successfully sent.
- After a successful send, the organisation must change to **Contacted**.
- If sending fails, the organisation must remain **Not Yet Contacted**.
- The draft must display **Send Failed** and allow an authorised user to try again.

### Email Already Sent

When an Admin or Staff user sends an email:

- The draft status must change to **Sent**.
- The send action must become unavailable.
- Other users viewing the draft must see that it has already been sent.
- The message must identify who sent the email and when it was sent.

Example:

> This email was already sent by Alex Smith on 6 October 2026 at 2:30 PM.

- If an Admin has already sent the email, Staff must see the message instead of another Send button.
- The system must prevent the same approved email from being sent twice.

### Editing an Approved Email

- Editing an approved draft must remove its Approved status.
- A Staff user who edits an approved draft must submit it to an Admin again.
- An Admin who edits an approved draft may approve it again without another Admin.
- The updated draft must not be sent using the previous approval.

## 6. User Account Management

### Creating a User

- Only an Admin may create a user.
- Public registration must not be available.
- The Admin must enter the user’s name, email address and role.
- The Admin must select either **Staff** or **Admin**.
- The email address must be unique.
- The system must send an invitation or password-setup link.
- The system must not display or store passwords in plain text.
- The account creation must be recorded in the activity history.

### Promoting Staff to Admin

- An Admin must have an option to change a Staff account to Admin.
- The Admin must confirm the role change before it is saved.
- After promotion, the user receives Admin permissions.
- Active sessions must refresh or be restarted so the new permissions take effect.
- The system must record the previous role, new role, acting Admin, date and time.

### Changing Another Admin to Staff

- An Admin may change another Admin’s role to Staff.
- An Admin cannot change their own role.
- The system must show a confirmation before completing the change.
- After the change, the affected user must lose Admin-only permissions.
- At least one active Admin must remain after the change.
- The system must record who completed the role change and when.

### Disabling a User

- Only an Admin may disable or re-enable another user.
- An Admin cannot disable their own account.
- A disabled user must not be able to sign in.
- Existing sessions belonging to the disabled user must be invalidated.
- On their next request, the disabled user must be signed out.
- Disabling an account must not delete previous activity or records.
- Existing drafts must remain available and may be reassigned.
- The Admin who disabled or re-enabled the account must be recorded.

## 7. First Admin Account

- The first Admin must be created securely during system setup.
- The first Admin may be created using a protected setup command, deployment process or database seed.
- Public Admin registration must not be available.
- The system must not use publicly known default Admin credentials.
- The first Admin must use a unique email address.
- The first Admin must create or change their password before accessing protected functions.
- After setup, the first Admin may create Staff accounts or additional Admin accounts through User Management.

## 8. No-Access Behaviour

### Staff Accessing Admin-Only Pages

For Staff users:

- Admin-only navigation links must not be displayed.
- **Add Organisation**, **Edit**, **Archive**, **Approve**, **Reject** and User Management controls must not be displayed.
- Entering an Admin-only URL directly must not reveal protected information.
- The server must prevent the unauthorised action.
- If the user opens an Admin-only page directly, the system must display:

> You do not have permission to access this page.

- The page must provide an option to return to the dashboard.

## 9. Disabled-User Behaviour

When a user is disabled:

- All active sessions must be invalidated.
- The user must be signed out on their next request.
- The user must not be able to sign in again.
- The system must display:

> Your account has been disabled. Please contact an administrator.

- Existing organisations, drafts and activity records created by the user must remain available.
- An Admin must be able to reassign unfinished drafts.

## 10. Edge Cases

### Last Active Admin

- The last active Admin must not be disabled.
- Another active Admin must exist before the account can be disabled.
- This prevents the system from having no active Admin accounts.

### Changing Another Admin to Staff

- An Admin may change another Admin to Staff.
- The acting Admin must remain an active Admin after the change.
- The system must check the current roles again when saving to prevent concurrent changes from removing all Admin access.

### Changing Own Role

- An Admin cannot change their own role.
- The role control must be unavailable when an Admin views their own account.
- Another Admin must complete the role change.

### Disabling Own Account

- An Admin cannot disable their own account.
- Another Admin must complete the action.

### Concurrent Email Sending

- If two users attempt to send the same approved email, the system must allow only the first valid send.
- The second user must see that the email has already been sent.
- The second request must not send another copy.

### Disabled User With Existing Drafts

- Existing drafts must not be deleted.
- The original creator must remain recorded.
- An Admin may reassign unfinished drafts to another user.

### Role Changed During an Active Session

- Updated permissions must take effect immediately or on the user’s next request.
- A user whose Admin role was removed must not continue using Admin-only functions through an existing session.

## 11. Empty, Loading and Error States

### Empty User List

If no Staff users have been created, User Management must display:

> No staff users have been added yet.

The Admin must see an **Add User** action.

### Loading State

While users, roles or permissions are loading:

- A loading indicator must be displayed.
- Account-management actions must remain unavailable.
- The system must prevent repeated submissions.

### Save-in-Progress State

While a user is being created, promoted, demoted, disabled or re-enabled:

- The selected action must be disabled.
- A progress message must be displayed.
- Repeated clicks must not create duplicate requests.

### Validation Error

- Errors must appear beside the relevant fields.
- Valid information already entered must remain in the form.
- No account or role change must be saved until all errors are corrected.

### System Error

If an operation fails:

- No partial account, role or permission change must be saved.
- A clear error message must be displayed.
- The Admin must be able to retry.
- Technical or database details must not be shown.

### Email Send Error

If an approved email fails to send:

- The email must not be marked as Sent.
- The organisation must remain **Not Yet Contacted**.
- The system must display an error.
- The user must be allowed to try again.

## 12. Acceptance Criteria

### AC-01: Admin Access

**Given** a user has the Admin role  
**When** they sign in  
**Then** they can access the dashboard, organisations, email workflows and User Management  
**And** they can add and edit organisations.

### AC-02: Staff Access

**Given** a user has the Staff role  
**When** they sign in  
**Then** they can view the dashboard and organisations  
**And** they can use permitted draft-email functions  
**But** they cannot add or edit organisations.

### AC-03: Organisation Management Controls Are Hidden From Staff

**Given** a Staff user is viewing an organisation  
**When** the page loads  
**Then** Add, Edit and Archive organisation controls must not be displayed.

### AC-04: Staff Directly Attempts to Change an Organisation

**Given** a Staff user is signed in  
**When** they directly submit a request to add, edit or archive an organisation  
**Then** no organisation information must be created or changed.

### AC-05: Admin Creates an Organisation

**Given** an Admin enters valid required organisation information  
**When** they save the form  
**Then** one organisation must be created  
**And** its contact status must be **Not Yet Contacted**.

### AC-06: Admin Creates a Staff Account

**Given** an Admin enters a valid name and unique email address  
**And** selects the Staff role  
**When** the account is created  
**Then** one Staff account must be created  
**And** an invitation or password-setup link must be issued.

### AC-07: Admin Promotes Staff to Admin

**Given** a Staff account exists  
**When** an Admin changes the user’s role to Admin and confirms the change  
**Then** the account must receive Admin permissions  
**And** the role change must be recorded.

### AC-08: Admin Changes Another Admin to Staff

**Given** two or more active Admin accounts exist  
**When** one Admin changes another Admin’s role to Staff  
**Then** the selected account must receive Staff permissions  
**And** the acting Admin must remain an Admin  
**And** the role change must be recorded.

### AC-09: Admin Cannot Change Their Own Role

**Given** an Admin is viewing their own account  
**When** the account page loads  
**Then** the role-change control must not be available.

### AC-10: Staff Submits a Draft for Approval

**Given** a Staff user has created a valid draft  
**When** they select **Submit for Approval**  
**Then** the draft status must change to **Pending Review**  
**And** an Admin must be able to review it.

### AC-11: Approval Controls Are Hidden From Staff

**Given** a Staff user views a draft that is Pending Review  
**When** the draft page loads  
**Then** Approve and Reject controls must not be displayed.

### AC-12: Admin Approves a Staff Draft

**Given** a Staff draft is Pending Review  
**When** an Admin approves it  
**Then** the draft status must change to **Approved**  
**And** the email must not be sent automatically.

### AC-13: Admin Approves Their Own Draft

**Given** an Admin created or edited a draft  
**When** the Admin approves it  
**Then** its status must change to **Approved**  
**And** approval from another Admin must not be required.

### AC-14: Admin Rejects a Draft

**Given** a Staff draft is Pending Review  
**When** an Admin enters a reason and rejects it  
**Then** the status must change to **Changes Requested**  
**And** the Staff user must be able to view the reason.

### AC-15: Staff Sends an Approved Email

**Given** an Admin has approved a draft  
**And** the draft has not already been sent  
**When** a Staff user selects **Send**  
**Then** the email must be sent  
**And** the draft must change to **Sent**  
**And** the organisation must change to **Contacted**.

### AC-16: Staff Cannot Send an Unapproved Email

**Given** a draft has not been approved by an Admin  
**When** a Staff user views the draft  
**Then** the Send action must not be displayed.

### AC-17: Admin Sends an Approved Email

**Given** a draft has been approved  
**When** an Admin sends it  
**Then** the draft must change to **Sent**  
**And** other users must see who sent it and when.

### AC-18: Staff Views an Email Already Sent by Admin

**Given** an Admin has already sent an email  
**When** a Staff user views the draft  
**Then** the Send action must not be displayed  
**And** a message must identify the Admin who sent it and the date and time.

### AC-19: Duplicate Send Is Prevented

**Given** an approved email has already been sent  
**When** another user attempts to send it  
**Then** the system must not send another copy  
**And** it must display that the email was already sent.

### AC-20: Approved Draft Is Edited by Staff

**Given** a draft has been approved  
**When** a Staff user returns it for editing  
**Then** the previous approval must be removed  
**And** the Staff user must submit it to an Admin again.

### AC-21: Approved Draft Is Edited by Admin

**Given** a draft has been approved  
**When** an Admin edits it  
**Then** the previous approval must be removed  
**And** the Admin may approve it again without another Admin.

### AC-22: User Is Disabled

**Given** a user has an active session  
**When** an Admin disables the account  
**Then** the user’s sessions must be invalidated  
**And** the user must not be able to sign in again.

### AC-23: Last Active Admin Cannot Be Disabled

**Given** only one active Admin remains  
**When** an action attempts to disable that Admin  
**Then** the action must be rejected  
**And** the Admin account must remain active.

### AC-24: Disabled User’s Work Is Preserved

**Given** a user owns existing drafts or records  
**When** their account is disabled  
**Then** the records must remain available  
**And** an Admin must be able to reassign unfinished drafts.

### AC-25: Email Sending Fails

**Given** an approved email is ready to send  
**When** the sending service fails  
**Then** the email must not be marked as Sent  
**And** the organisation must remain **Not Yet Contacted**  
**And** the user must be shown an error and retry option.

### AC-26: Account Operation Fails

**Given** a system failure occurs while changing a user or role  
**When** the operation cannot be completed  
**Then** no partial change must be saved  
**And** a clear error message must be displayed.

## 13. Final Expected Behaviour

Admins have full control over organisations, users, roles, email approval and sending. An Admin may approve their own draft without another Admin.

Staff can view organisations, prepare email drafts and submit them for approval. Staff do not see Admin-only controls such as Add Organisation, Edit Organisation, Approve, Reject or User Management.

After an Admin approves a draft, either an Admin or Staff user may send it. Once it has been sent, all users can see who sent it and when, and the email cannot be sent again.

An Admin may promote Staff to Admin or change another Admin to Staff. Users cannot change their own role, and the system must always retain at least one active Admin.