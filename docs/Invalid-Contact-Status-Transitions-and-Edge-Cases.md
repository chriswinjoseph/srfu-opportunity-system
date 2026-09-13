# Invalid Contact Status Transitions and Edge Cases

## Purpose

This document defines the status changes that must be prevented and the expected system behaviour when unusual situations occur.

It follows the previously defined model:

- `contact_status` records **Not Yet Contacted** or **Contacted**.
- `opportunity.status` records the outreach outcome, such as **Interested**, **Not Interested** or **Do Not Contact**.

## 1. Transitions That Must Not Occur

| Invalid transition or action | Expected system behaviour |
| --- | --- |
| Not Yet Contacted → Contacted when a draft is generated, reviewed or edited | Keep the organisation as Not Yet Contacted. |
| Not Yet Contacted → Contacted when a draft is approved but not sent | Keep the organisation as Not Yet Contacted until sending succeeds. |
| Not Yet Contacted → Contacted after a failed send | Keep the original status and display the sending error. |
| Contacted → Not Yet Contacted because an email receives no response | Keep the organisation as Contacted. No response does not erase previous outreach. |
| Contacted → Not Yet Contacted because a draft is deleted or cancelled | Keep the organisation as Contacted and retain its outreach history. |
| `contact_status` → Interested, Not Interested or Do Not Contact | Reject these values for `contact_status`; record the outcome through `opportunity.status`. |
| A status change attempted by an unauthorised user | Reject the update and retain the stored status. |
| Contacting a bank automatically marks its branches or supported clubs as Contacted | Update only the organisation directly contacted. |
| Sending outreach when the organisation has an applicable Do Not Contact restriction | Block sending, including sending a previously approved draft. |

A change from **Contacted** back to **Not Yet Contacted** should not be part of the normal workflow. If contact was recorded by mistake, an authorised correction should require a reason and preserve a record of the correction.

## 2. Draft Generated but Never Approved or Sent

If a draft is generated but never approved, the organisation remains **Not Yet Contacted**. The draft may remain saved for later review or be cancelled or deleted.

If the draft is approved but never sent, the organisation also remains **Not Yet Contacted**.

The system must not:

- Send the draft automatically.
- Record a contact date merely because a draft exists.
- Change the contact status because the draft has been waiting for a long time.

Draft progress and contact status must remain separate.

## 3. Duplicate Detection

### Duplicate Organisation During Import or Manual Creation

When a possible duplicate is detected, the system should flag the record for review rather than automatically create another organisation.

Matching must use organisation-identifying information, not the name alone. Two branches may have similar names but different locations.

The system should preserve existing contact history. An incoming record marked **Not Yet Contacted** must not overwrite an existing **Contacted** record.

If the records contain conflicting contact information, the conflict should be shown for review rather than silently resolved.

### Duplicate Sending Action

If a user double-clicks Send or the same sending request is submitted twice, the system should process the outreach once.

It should:

- Prevent a second email from being sent for the same request.
- Record one outreach event.
- Change the status to Contacted once.

An intentional follow-up is a separate outreach action and must not be mistaken for a duplicate request.

## 4. Disagreement Between Contact Status and Opportunity Status

Different values do not automatically mean the fields disagree. For example:

- `contact_status = Contacted`
- `opportunity.status = Interested`

This is valid because one field records whether contact occurred and the other records the outcome.

A potential conflict occurs when an organisation is **Not Yet Contacted**, but its opportunity records a response to outreach that supposedly occurred.

The system should check the recorded outreach history:

- If confirmed outreach exists, correct `contact_status` to Contacted and record why the correction occurred.
- If no supporting history exists, flag the record for review.
- Do not invent a contact date or erase the response to make the fields match.
- Prevent new initial outreach until the conflict is resolved.

A Do Not Contact restriction must still block outreach, even if the contact-status information is incomplete or inconsistent.

## 5. Concurrent-Edit Edge Case

A concurrent edit occurs when two authorised users work on the same organisation at the same time.

For example, one user sends an email while another user still has an older version of the organisation record open.

The system should check that the record has not changed before accepting an update. If it has changed, the second user should receive a message asking them to refresh and review the latest information.

The system must not allow an older update to:

- Reset Contacted to Not Yet Contacted.
- Overwrite a newly recorded response.
- Remove a Do Not Contact restriction.
- Trigger duplicate outreach.

If one user applies Do Not Contact while another prepares to send, the system must check the latest restriction immediately before sending and block the email if the restriction is present.

## 6. Additional Edge Cases and Expected Behaviour

| Edge case | Expected system behaviour |
| --- | --- |
| Email successfully sent but later bounces | Keep Contacted and record the delivery failure separately. Inform the user that delivery was unsuccessful. |
| Sending result is unknown because of a timeout | Do not assume success or immediately resend. Check the sending result before updating the status or retrying. |
| Email sent successfully but the status update fails to save | Preserve evidence of the send and flag the record for reconciliation. Do not send the email again solely to update the status. |
| External outreach entered without the required method or contact date | Ask the user to complete the required information before changing the status. |
| Follow-up sent to an already contacted organisation | Keep Contacted and record the follow-up as a separate outreach event. |
| Organisation does not reply | Keep Contacted; do not automatically reset the status. |
| Imported record states Contacted but supporting history is incomplete | Flag it for review. Missing a contact date alone does not prove that no contact occurred. |