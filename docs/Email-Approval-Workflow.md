# Business-Logic Test Cases: Email Approval Workflow

## 1. Purpose

The purpose of these test cases is to confirm that draft outreach emails follow the required review and approval process before they can be sent.

The test cases validate:

- Approval and rejection behaviour.
- Editing and resubmitting rejected drafts.
- Changes made before and after approval.
- Approver and sender permissions.
- Self-approval behaviour.
- Situations where no approver is available.
- Protection against sending unapproved or outdated drafts.
- The effect of the workflow on `contact_status`.

## 2. Approval Workflow Being Tested

The expected workflow is:

1. An authorised user creates or generates a draft.
2. The user reviews and edits the draft.
3. The draft is submitted for approval.
4. An authorised approver reviews the submitted version.
5. The approver either approves it or requests changes.
6. A rejected draft is updated and submitted again.
7. An approved draft becomes available for sending.
8. Only successful sending changes `contact_status` to **Contacted**.

The approval states used in these tests are:

- Draft
- Awaiting Approval
- Changes Requested
- Approved
- Sending
- Sent
- Send Failed
- Cancelled

## 3. Permission Rules to Validate

The following permission rules should apply:

- An authorised user may create, generate, edit and submit a draft.
- An authorised approver may approve or reject a submitted draft.
- An authorised sender may send an approved draft.
- A user without approver permission must not approve or reject a draft.
- A user without sender permission must not send an approved draft.
- Approval must never send the email automatically.
- A draft must not be sent while it is in Draft, Awaiting Approval or Changes Requested.
- Editing an approved draft must invalidate its approval.
- A rejected draft must be submitted again after it is corrected.

Self-approval is not clearly confirmed in the functional requirements. From a business-control perspective, the recommended rule is that the person who creates or edits a draft should not approve the same draft.

If Shane is expected to operate the system alone, the team may need to permit self-approval for authorised users. This decision must be confirmed by the PM and Shane.

## 4. Business-Logic Test Cases

### TC-01: Submit a Valid Draft for Approval

**Given** an authorised user has created a complete draft  
**And** the draft contains a valid recipient, subject and email body  
**When** the user submits the draft for approval  
**Then** the draft state must change from **Draft** to **Awaiting Approval**  
**And** the submitted version must be recorded  
**And** the appropriate approver must be notified or shown the pending approval  
**And** `contact_status` must remain **Not Yet Contacted**.

### TC-02: Approve a Valid Draft

**Given** a valid draft is in **Awaiting Approval**  
**And** the current user has approver permission  
**When** the approver selects **Approve**  
**Then** the draft state must change to **Approved**  
**And** the system must record the approver, approval date, approval time and approved version  
**And** the draft must become available to an authorised sender  
**And** the email must not be sent automatically  
**And** `contact_status` must remain **Not Yet Contacted**.

### TC-03: Reject a Draft

**Given** a draft is in **Awaiting Approval**  
**And** the current user has approver permission  
**When** the approver selects **Reject** or **Request Changes**  
**Then** the approver must provide a rejection reason or requested changes  
**And** the draft state must change to **Changes Requested**  
**And** the draft must not be available for sending  
**And** the rejection details must be recorded  
**And** `contact_status` must remain **Not Yet Contacted**.

### TC-04: Reject a Draft Without a Reason

**Given** a draft is in **Awaiting Approval**  
**When** the approver selects **Reject** without entering a reason  
**Then** the system must prevent the rejection from being completed  
**And** request a reason or explanation  
**And** the draft must remain in **Awaiting Approval**.

This ensures that the draft creator understands what must be corrected.

### TC-05: Edit and Resubmit a Rejected Draft

**Given** a draft is in **Changes Requested**  
**And** the rejection reason is available to the draft creator  
**When** an authorised user edits the draft and submits it again  
**Then** a new draft version must be recorded  
**And** the state must change to **Awaiting Approval**  
**And** the previous rejection and draft versions must remain in the history  
**And** the draft must require a new approval.

### TC-06: Approve a Corrected Draft

**Given** a rejected draft has been edited and resubmitted  
**And** its state is **Awaiting Approval**  
**When** an authorised approver approves the corrected version  
**Then** only the latest submitted version must be approved  
**And** the state must change to **Approved**  
**And** the earlier rejected version must not become sendable.

### TC-07: Edit a Draft Before Approval

**Given** a draft is in **Awaiting Approval**  
**When** an authorised user edits its subject, recipient or email body  
**Then** the existing approval request must be withdrawn or invalidated  
**And** the draft must return to **Draft**  
**And** the edited version must be submitted again for approval  
**And** an approver must not be able to approve the previous version.

### TC-08: Edit a Draft After Approval

**Given** a draft is in **Approved**  
**When** an authorised user changes its recipient, subject or email body  
**Then** the existing approval must be invalidated  
**And** the draft must return to **Draft**  
**And** the edited version must require a new approval  
**And** the previously approved version must not be sent.

### TC-09: Attempt to Send a Draft Without Approval

**Given** a draft is in Draft, Awaiting Approval or Changes Requested  
**When** a user attempts to send it  
**Then** the system must prevent the email from being sent  
**And** explain that approval is required  
**And** `contact_status` must remain **Not Yet Contacted**.

### TC-10: Approve a Draft Without Approver Permission

**Given** a draft is in **Awaiting Approval**  
**And** the current user does not have approver permission  
**When** the user attempts to approve or reject the draft  
**Then** the system must deny the action  
**And** the draft must remain in **Awaiting Approval**  
**And** no approval or rejection record must be created.

### TC-11: Attempt Self-Approval

**Given** a user created or last edited the draft  
**And** the draft is in **Awaiting Approval**  
**When** the same user attempts to approve it  
**Then** the system must apply the team’s confirmed self-approval rule.

If self-approval is prohibited:

- The action must be blocked.
- The draft must remain in **Awaiting Approval**.
- Another authorised approver must review it.

If self-approval is permitted:

- The user must also hold approver permission.
- The approval must be recorded as self-approved in the audit history.

### TC-12: No Approver Is Available

**Given** a draft is ready to be submitted  
**And** no active authorised approver is available  
**When** the user submits the draft for approval  
**Then** the system must not approve or send it automatically  
**And** the draft must remain in **Awaiting Approval**  
**And** the user must be informed that no approver is currently available  
**And** the approval request must be capable of being assigned or escalated to another authorised approver.

The escalation and reassignment process requires confirmation from the team.

### TC-13: Approval Request Remains Unanswered

**Given** a draft has remained in **Awaiting Approval** beyond the expected review period  
**When** the approval deadline is reached  
**Then** the draft must remain unsent  
**And** approval must not be granted automatically  
**And** the system should notify or remind the appropriate authorised user.

The team must confirm the approval time limit and reminder process.

### TC-14: Approve a Draft With Missing Required Content

**Given** a draft is missing its recipient, subject or email body, or contains unresolved placeholders  
**When** an approver attempts to approve it  
**Then** the system must prevent approval  
**And** identify the missing or invalid content  
**And** keep the draft in **Awaiting Approval** or return it for changes.

### TC-15: Organisation Becomes Do Not Contact During Approval

**Given** a draft is in **Awaiting Approval** or **Approved**  
**And** the organisation’s `opportunity.status` changes to **Do Not Contact**  
**When** an approver or sender attempts to continue the workflow  
**Then** the approval or sending action must be blocked  
**And** the draft must not be sent  
**And** the reason must be displayed and recorded.

### TC-16: Recipient Email Changes After Approval

**Given** a draft has been approved  
**When** the organisation’s recipient email address changes  
**Then** the approval must be invalidated  
**And** the draft must return to **Draft**  
**And** the new recipient must be verified  
**And** the draft must be submitted for approval again.

### TC-17: Two Approvers Act at the Same Time

**Given** two authorised approvers are viewing the same pending draft  
**When** one approver approves it while the other attempts to reject it  
**Then** the first successfully completed decision must be saved  
**And** the second approver must be informed that the draft state has already changed  
**And** contradictory decisions must not be recorded for the same version.

### TC-18: Cancel a Draft Awaiting Approval

**Given** a draft is in **Awaiting Approval**  
**When** an authorised user cancels the draft  
**Then** the draft state must change to **Cancelled**  
**And** any pending approval request must be withdrawn  
**And** the draft must not be approved or sent  
**And** `contact_status` must remain **Not Yet Contacted**.

### TC-19: Send an Approved Draft Successfully

**Given** a draft is in **Approved**  
**And** its approved version has not been edited  
**And** the organisation is not marked **Do Not Contact**  
**And** the current user has sender permission  
**When** the email is successfully sent  
**Then** the draft state must change to **Sent**  
**And** the outreach event must be recorded  
**And** `contact_status` must change from **Not Yet Contacted** to **Contacted**.

### TC-20: Approved Draft Fails to Send

**Given** a draft is in **Approved**  
**When** an authorised sender attempts to send it  
**And** the email service reports a failure  
**Then** the draft state must change to **Send Failed**  
**And** the failure reason must be recorded  
**And** `contact_status` must remain **Not Yet Contacted**  
**And** the user must be informed that the email was not sent.

## 5. Rejection-Flow Business Review

The rejection flow makes business sense if rejection is treated as a request for correction rather than permanent deletion.

The expected rejection process is:

1. The approver reviews the submitted draft.
2. The approver selects **Reject** or **Request Changes**.
3. A reason must be entered.
4. The draft changes to **Changes Requested**.
5. The draft creator can view the feedback.
6. The creator edits the draft.
7. The corrected version is submitted again.
8. A new approval is required.

The rejected version, rejection reason and approver details should remain in the history for accountability.

Rejection must not:

- Delete the draft.
- Send the email.
- Change `contact_status`.
- Permanently prevent the draft from being corrected and resubmitted.

## 6. Functional-Requirement Coverage

| Scenario | Expected outcome confirmed against the functional requirements |
|---|---|
| Approve draft | State becomes Approved, approval is recorded and the email remains unsent |
| Reject draft | State becomes Changes Requested and a reason is required |
| Edit rejected draft | A new version is created and approval is required again |
| Edit before approval | The pending approval becomes invalid |
| Edit after approval | The existing approval becomes invalid |
| No approver available | The draft remains pending and cannot be sent |
| Unauthorised approval | The approval or rejection action is blocked |
| Send without approval | Sending is blocked |
| Successful send | State becomes Sent and contact status becomes Contacted |
| Failed send | State becomes Send Failed and contact status remains Not Yet Contacted |
| Do Not Contact organisation | Approval and sending are blocked |
| Concurrent approval decisions | Only one valid decision is recorded for a draft version |

## 7. Items Requiring Team Confirmation

The functional requirements do not clearly answer the following scenarios:

1. Whether the draft creator may approve their own draft.
2. Whether an approver may directly edit a draft or must reject it for the creator to edit.
3. How long a draft may remain in **Awaiting Approval** before a reminder is sent.
4. Who receives an approval request when the usual approver is unavailable.
5. Whether approval requests can be reassigned or escalated.
6. Whether more than one approver is required for particular emails.
7. Whether an approved draft expires if it is not sent within a set period.
8. Whether a rejected draft should use the label **Rejected** or **Changes Requested**.
9. Who may cancel a draft that is awaiting approval or already approved.
10. Whether the sender and approver may be the same person.
11. Whether approval history must be visible to all authorised users or only administrators.
12. Whether an approved draft may be retried after a temporary sending failure or must be approved again.

## 8. Final Expected Behaviour

A draft email cannot be sent until an authorised approver has reviewed and approved the exact version being sent. Rejected drafts return for correction with a clear reason and must be submitted again. Any material change to a submitted or approved draft invalidates its previous approval.

Unauthorised users cannot approve, reject or send drafts. If no approver is available, the draft remains pending and unsent. Approval alone does not change the organisation’s contact status.

The organisation changes from **Not Yet Contacted** to **Contacted** only after the approved email has been successfully sent.