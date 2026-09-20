# Functional Requirements: Draft-Email Generation and Approval Workflow

## 1. Purpose and Scope

The draft-email workflow allows an authorised user to generate an outreach email for an organisation, review and edit its contents, submit it for human approval and send it only after approval.

The workflow must remain separate from the organisation’s `contact_status`.

Generating, editing, submitting or approving a draft must not change the organisation from **Not Yet Contacted** to **Contacted**. The status changes only after the approved email is successfully sent.

## 2. Triggers for Generating a Draft Email

A draft email may be generated when:

- An authorised user selects an organisation with the status **Not Yet Contacted**.
- The organisation has a valid public email address.
- The organisation is not marked **Do Not Contact**.
- The user selects the Generate Draft Email action.

Draft generation must be a deliberate user action. Importing or creating an organisation must not automatically generate an email.

Before generating the draft, the system must check:

- The organisation still exists.
- Its current status is Not Yet Contacted.
- A recipient email address is available.
- There is no Do Not Contact restriction.
- Another active draft does not already exist for the same initial outreach.

If an active draft already exists, the system should direct the user to the existing draft instead of creating a duplicate.

## 3. Information Used to Populate the Draft

### Required Information

The draft must use:

- Organisation name
- Organisation type, such as bank, branch or club
- Public recipient email address
- Selected outreach template
- Outreach purpose
- Sender name and authorised SRFU contact details

### Optional Information

Where available, the draft may also use:

- Public contact person’s name
- Public role or position
- Organisation location or region
- Branch name
- Other approved public organisation information

If optional information is unavailable, the system must omit it rather than display blank placeholders or invent information.

### Information Stored With the Draft

The system must record:

- Draft ID
- Related organisation ID
- Related opportunity ID, where applicable
- Recipient email address
- Email subject
- Email body
- Template and template version used
- User who generated the draft
- Date and time generated
- Current workflow state
- Most recent editor
- Date and time last edited

Only publicly available organisation and contact information may be used.

## 4. Approval States

| State | Meaning |
| --- | --- |
| Draft | The email has been generated and may still be edited. |
| Awaiting Approval | The draft has been submitted and is waiting for an authorised approver. |
| Changes Requested | The approver has rejected the current version and requested changes. |
| Approved | The exact draft version has been approved but has not yet been sent. |
| Sending | The system is currently attempting to send the approved email. |
| Sent | The system has confirmed that the email was successfully sent. |
| Send Failed | The sending attempt failed and the organisation was not changed to Contacted. |
| Cancelled | The draft was cancelled and cannot be sent unless a new draft is created. |

These states belong to the email workflow. They must not be stored as values of `contact_status`.

## 5. Permission Rules

### Authorised User

An authorised user may:

- Generate a draft.
- View the draft.
- Edit a draft while it is in Draft or Changes Requested.
- Submit the draft for approval.
- Cancel a draft before it is sent.

### Authorised Approver

Only a user with approval permission may:

- Approve a draft.
- Reject the draft and request changes.
- Record an approval or rejection decision.

An approver must be able to review:

- The organisation receiving the email
- Recipient email address
- Subject
- Complete email body
- Information used to populate the draft
- Most recent changes

A user without approval permission must not be able to approve or reject a draft.

A person who generated the draft may approve it only if that person also has approval permission. The system must still record them separately as the draft creator and approver.

### Authorised Sender

Only a user with sending permission may send an approved draft.

Approval must not automatically send the email.

## 6. Behaviour When a Draft Is Rejected

When an approver rejectss a draft:

- The workflow state changes to **Changes Requested**.
- A rejection reason or requested change must be recorded.
- The draft must not be sent.
- The organisation remains **Not Yet Contacted**.
- The draft creator or another authorised user may edit the draft.
- The edited draft must be resubmitted for approval.
- The previous rejection decision must remain in the workflow history.

Rejecting a draft does not permanently cancel the outreach unless the approver specifically selects Cancel Draft.

## 7. Behaviour When a Draft Is Approved

When an approver approves a draft:

- The workflow state changes to **Approved**.
- The system records the approver, approval time and approved draft version.
- The organisation remains **Not Yet Contacted**.
- The email must not be sent automatically.
- Only the approved version may be sent.
- An authorised sender may select Send.

Immediately before sending, the system must confirm that:

- The draft is still Approved.
- The draft has not been edited since approval.
- The organisation is not marked Do Not Contact.
- The recipient email is still valid.
- The organisation has not already received the same initial outreach.
- The organisation and opportunity records have not changed in a way that prevents sending.

If the email is successfully sent:

- The workflow state changes to **Sent**.
- The outreach event is recorded.
- The organisation’s `contact_status` changes to **Contacted**.
- The contact date, sending user and outreach method are recorded.

If sending fails:

- The workflow state changes to **Send Failed**.
- The organisation remains **Not Yet Contacted**.
- The failure reason is recorded.
- The user is informed that the email was not sent.
- An authorised user may retry after reviewing the failure.

## 8. Editing After Submission or Approval

A draft in **Awaiting Approval** cannot be silently edited.

If an authorised user chooses to edit it:

- The pending approval request is withdrawn.
- The state returns to Draft.
- The changes are recorded.
- The draft must be submitted again.

If an approved draft is edited:

- The previous approval becomes invalid.
- The state returns to Draft.
- The approved version must not be overwritten without retaining its history.
- The updated draft must go through approval again.

This ensures that the sent email is exactly the version reviewed by the approver.

## 9. Edge Cases

| Edge case | Expected system behaviour |
| --- | --- |
| Organisation has no public email address | Block draft generation and ask the user to add or verify an email address. |
| Email address is incorrectly formatted | Block generation or submission until it is corrected. |
| Organisation is marked Do Not Contact | Block draft generation, approval and sending. |
| Organisation becomes Do Not Contact while approval is pending | Prevent approval or sending and flag the draft for review. |
| No approver is available | Keep the draft in Awaiting Approval and notify the PM or administrator that an approver must be assigned. |
| Approval is not completed within the expected period | Keep the draft in Awaiting Approval, mark it as overdue and notify the relevant user. Do not approve, reject or send it automatically. |
| Draft is edited after approval | Invalidate the approval, return the draft to Draft and require reapproval. |
| Recipient email changes after approval | Invalidate the approval and require the updated recipient details to be reviewed. |
| User double-clicks Generate Draft | Create only one active draft. |
| User double-clicks Send | Process one sending request and prevent duplicate emails. |
| Two users edit the same draft simultaneously | Prevent the older version from overwriting the newer version and ask the second user to refresh. |
| Draft generation service fails | Do not create an incomplete draft. Display an error and allow the user to retry. |
| Generated draft contains missing placeholders | Block submission for approval until the placeholders are corrected. |
| Organisation is already Contacted | Block generation of a new initial-outreach draft. Any follow-up must use a separate follow-up workflow. |
| Send result is unknown because of a timeout | Do not immediately resend or mark the organisation Contacted. Confirm the sending result first. |
| Email sends successfully but saving the new contact status fails | Preserve the sending evidence and flag the organisation for reconciliation. Do not resend the email. |

## 10. Final Workflow

1. An authorised user selects a Not Yet Contacted organisation.
2. The system validates the organisation, recipient email and contact restrictions.
3. The user generates the draft.
4. The system populates the draft using the selected template and approved organisation data.
5. The authorised user reviews and edits the draft.
6. The draft is submitted for approval.
7. An authorised approver reviews the exact recipient, subject and email body.
8. The approver either requests changes or approves the draft.
9. A rejected draft returns for editing and must be submitted again.
10. An approved draft remains unsent until an authorised sender selects Send.
11. The system rechecks the latest organisation information and restrictions.
12. A successful send changes the organisation to Contacted.
13. A failed send leaves the organisation as Not Yet Contacted.