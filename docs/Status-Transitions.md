# Allowed Not Yet Contacted to Contacted Status Transitions

## 1. Confirmed Transition Trigger

An organisation shall change from **Not Yet Contacted** to **Contacted** only when one of the following occurs:

1. An outreach email is successfully sent through the system.
2. An authorised user records that outreach was completed outside the system, such as a manually sent email or phone call.
3. An imported record contains confirmed evidence that the organisation was previously contacted.

The following actions shall not change the contact status:

- Generating a draft email.
- Reviewing a draft email.
- Editing a draft email.
- Approving a draft email.
- Attempting to send an email that fails.
- Saving an email without sending it.

Approval of a draft does not mean the organisation has been contacted. The status only changes after the outreach is successfully sent or manually recorded as completed.

## 2. Decision on an Intermediate State

An intermediate `contact_status`, such as **Draft Created**, **Awaiting Approval** or **Approved**, is not required.

The purpose of `contact_status` is only to answer:

> Has this organisation been contacted?

Therefore, `contact_status` should remain binary:

- **Not Yet Contacted**
- **Contacted**

The progress of an outreach email should be tracked separately through the email or opportunity record. For example, the draft-email workflow may contain:

- Draft
- Awaiting Approval
- Approved
- Sent
- Failed

These are email workflow states and should not be added to the organisation’s `contact_status`.

## 3. Intermediate-State Entry and Exit Transitions

Because no intermediate state is being added to `contact_status`, no additional entry or exit transitions are required.

While an email is being drafted, reviewed or approved, the organisation remains **Not Yet Contacted**. It only exits this status when the email is successfully sent or an authorised user records external outreach.

## 4. Who or What Can Trigger the Transition

The transition can be triggered by:

### System-triggered transition

The system automatically changes the organisation from **Not Yet Contacted** to **Contacted** after receiving confirmation that an outreach email was successfully sent.

### User-triggered transition

An authorised user can manually record that contact occurred outside the system. The user must select the outreach method and record the contact date.

### Import-triggered status

During data import, the system can assign **Contacted** as the initial status when Shane’s existing data confirms that previous outreach occurred.

The following cannot trigger the transition:

- Draft-email generation.
- AI-generated email content.
- Draft editing.
- Draft review.
- Draft approval by itself.
- An unsuccessful send attempt.
- An unauthorised user.

## 5. Application Across Organisation Types

The same transition rules apply to:

- Banks
- Branches
- Clubs

However, each organisation record must be treated independently.

For example:

- Contacting a bank changes only that bank to **Contacted**.
- It does not automatically change the bank’s branches to **Contacted**.
- It does not automatically change supported clubs to **Contacted**.
- A branch or club only becomes **Contacted** when outreach is sent or recorded directly against that organisation.

This prevents the system from incorrectly showing related organisations as contacted when they have not received outreach.

## 6. Finalised Transition Table

| Current status | Event | Triggered by | Resulting status | Allowed |
| --- | --- | --- | --- | --- |
| Not Yet Contacted | Draft email generated | System or authorised user | Not Yet Contacted | Yes |
| Not Yet Contacted | Draft email reviewed or edited | Authorised user | Not Yet Contacted | Yes |
| Not Yet Contacted | Draft email approved | Authorised user | Not Yet Contacted | Yes |
| Not Yet Contacted | Email successfully sent | System | Contacted | Yes |
| Not Yet Contacted | Email send fails | System | Not Yet Contacted | Yes |
| Not Yet Contacted | External email or phone call is recorded | Authorised user | Contacted | Yes |
| No existing status | Imported record confirms previous outreach | Import process | Contacted | Yes |
| No existing status | Imported record has no outreach history | Import process | Not Yet Contacted | Yes |
| Contacted | Organisation responds positively | Authorised user | Contacted | Yes - update `opportunity.status` to Interested |
| Contacted | Organisation responds negatively | Authorised user | Contacted | Yes - update `opportunity.status` to Not Interested |
| Contacted | Organisation requests no further contact | Authorised user | Contacted | Yes - update `opportunity.status` to Do Not Contact |
| Contacted | Follow-up outreach is sent | System or authorised user | Contacted | Yes |
| Not Yet Contacted | Email generation, review or approval only | System or authorised user | Contacted | No |
| Not Yet Contacted | Unsuccessful email send | System | Contacted | No |

## 7. Final Business Rules

1. Every new organisation defaults to **Not Yet Contacted** unless confirmed previous outreach history is imported.

2. Creating, reviewing, editing or approving a draft email does not change `contact_status`.

3. A successful system email send changes the selected organisation to **Contacted**.

4. A failed email send leaves the organisation as **Not Yet Contacted**.

5. An authorised user may change the organisation to **Contacted** by recording outreach completed outside the system.

6. Contacting one organisation does not automatically change the status of its related bank, branches or clubs.

7. Responses such as Interested, Not Interested and Do Not Contact do not replace the Contacted status. They are recorded through `opportunity.status`.

8. Once an organisation is Contacted, follow-up outreach does not reset or change its `contact_status`.