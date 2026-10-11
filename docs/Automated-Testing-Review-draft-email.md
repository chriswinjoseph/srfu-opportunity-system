# Draft-Email Build Validation Report

## 1. Purpose

This document records the functional testing completed on the draft-email generation, approval, rejection, editing and sending workflows.

The feature was compared against the draft-email requirements, approval test cases and role-permission rules.

## 2. Test Results

### Test 1: Generate a Draft for a Not Yet Contacted Organisation

**Expected result:**

The system generates an email draft for a Not Yet Contacted organisation using its organisation and contact information. Generating the draft must not send the email or change the organisation to Contacted.

**Actual result:**

The draft was generated successfully with the expected recipient, subject and email body. The email was not automatically sent, and the organisation remained Not Yet Contacted.

**Result:** Pass

---

### Test 2: Generate a Draft Without a Contact Name

**Expected result:**

If a contact name is unavailable, the system should generate the email using a suitable general greeting without inventing a name.

**Actual result:**

All available organisation records contained a name, and the system would not allow a required organisation name to be omitted. Therefore, a suitable test record was not available for this scenario.

**Result:** Not Tested

---

### Test 3: Organisation Without a Recipient Email

**Expected result:**

An organisation may exist without an email address, but the user must not be able to generate or send an email until a valid recipient email is added.

**Actual result:**

The system allowed the organisation to exist without an email address. However, the email-generation and sending features were unavailable for that organisation.

**Result:** Pass

---

### Test 4: Do Not Contact Organisation

**Expected result:**

An organisation marked Do Not Contact must not allow users to generate, approve or send an email.

**Actual result:**

The Do Not Contact functionality has not been implemented. Therefore, this restriction could not be applied or tested.

**Result:** Fail

**Issue:** DE-01 — Do Not Contact functionality is missing  
**Severity:** High

---

### Test 5: Regenerate an AI Draft

**Expected result:**

The user can request another AI-generated version of the email without automatically sending or approving it.

**Actual result:**

The Regenerate function worked correctly. Each time Regenerate was selected, the AI produced a different email draft.

**Result:** Pass

---

### Test 6: Staff Submits a Draft for Approval

**Expected result:**

A Staff user can submit a completed draft for approval. The status must change to Pending Review, and the email must remain unsent.

**Actual result:**

The Staff user successfully submitted the draft. The draft changed to Pending Review and waited for Admin approval.

**Result:** Pass

---

### Test 7: Staff Cannot Approve or Reject a Draft

**Expected result:**

Staff users must not see the Approve or Reject controls.

**Actual result:**

The Staff account did not display any Approve or Reject options.

**Result:** Pass

---

### Test 8: Admin Approves a Staff Draft

**Expected result:**

An Admin can approve a Staff draft. Approval must change the draft to Approved without automatically sending it.

**Actual result:**

The Admin successfully approved the Staff draft. The draft changed to Approved and was not sent automatically.

**Result:** Pass

---

### Test 9: Admin Self-Approval

**Expected result:**

An Admin can approve a draft they created or edited without requiring approval from another Admin.

**Actual result:**

The Admin successfully approved their own draft without another Admin.

**Result:** Pass

---

### Test 10: Admin Rejects a Draft

**Expected result:**

An Admin can reject a Staff draft and provide a reason. The draft must become available for correction.

**Actual result:**

The Admin successfully rejected the draft, and the rejection workflow operated correctly.

**Result:** Pass

---

### Test 11: Staff Edits and Resubmits a Rejected Draft

**Expected result:**

The Staff user can view the rejection feedback, edit the draft and submit it for approval again.

**Actual result:**

The Staff user successfully edited the rejected draft and resubmitted it to the Admin.

**Result:** Pass

---

### Test 12: Staff Edits an Approved Draft

**Expected result:**

Editing an approved draft must remove its existing approval. The Staff user must submit the updated draft for Admin approval again.

**Actual result:**

The Staff user was able to return the approved draft for editing, update it and send it through the approval workflow again.

**Result:** Pass

---

### Test 13: Admin Edits an Approved Draft

**Expected result:**

An Admin can edit an approved draft. The previous approval must be removed, and the Admin may approve the changed draft again without another Admin.

**Actual result:**

The Admin successfully edited the approved draft and completed the approval process again.

**Result:** Pass

---

### Test 14: Staff Attempts to Send an Unapproved Draft

**Expected result:**

A Staff user must not see the Send option while the draft is unapproved.

**Actual result:**

The Send option was not displayed to Staff until an Admin approved the draft.

**Result:** Pass

---

### Test 15: Staff Sends an Admin-Approved Email

**Expected result:**

After an Admin approves the draft, the Staff user can send it. The draft must change to Sent, and the organisation must change to Contacted.

**Actual result:**

The Staff user successfully sent the Admin-approved email. The sending workflow and contact-status update operated correctly.

**Result:** Pass

---

### Test 16: Admin Sends an Approved Email

**Expected result:**

An Admin can send an approved email. The system must record the email as Sent and prevent Staff from sending it again.

**Actual result:**

The Admin successfully sent the approved email, and the workflow operated correctly.

**Result:** Pass

---

### Test 17: Duplicate Send Prevention

**Expected result:**

Once an email has been sent, another user must not be able to send it again.

**Actual result:**

When a second send was attempted, the system prevented it and displayed:

> This organisation has already been contacted.

**Result:** Pass

---

### Test 18: AI Generation Error

**Expected result:**

If AI generation fails, the system must display an error and allow the user to retry or write the email manually.

**Actual result:**

No AI-generation error occurred during testing. A manual email-writing option is available, but the actual behaviour following an AI failure could not be tested.

**Result:** Not Tested

---

### Test 19: Email Sending Failure

**Expected result:**

If sending fails, the email must not be marked as Sent, the organisation must remain Not Yet Contacted, and the user must receive an error and retry option.

**Actual result:**

Several email sends were attempted, but none produced a sending failure. Therefore, the send-failure behaviour could not be tested.

**Result:** Not Tested

## 3. Contact-Status Validation

| Draft-Email Action | Expected Status | Test Result |
|---|---|---|
| Generate draft | Not Yet Contacted | Pass |
| Edit draft | Not Yet Contacted | Pass |
| Submit for approval | Not Yet Contacted | Pass |
| Reject draft | Not Yet Contacted | Pass |
| Resubmit rejected draft | Not Yet Contacted | Pass |
| Approve draft | Not Yet Contacted | Pass |
| Edit approved draft | Not Yet Contacted | Pass |
| Successfully send email | Contacted | Pass |
| Attempt duplicate sending | Remains Contacted; second send blocked | Pass |
| Email sending fails | Remains Not Yet Contacted | Not Tested |

Approval did not change the organisation to Contacted. The status changed only after the email was successfully sent, which matches the requirements.

## 4. Permission Validation

| Permission Rule | Result |
|---|---|
| Staff can generate and edit drafts | Pass |
| Staff can submit drafts for approval | Pass |
| Staff cannot see Approve or Reject controls | Pass |
| Staff cannot send an unapproved draft | Pass |
| Admin can approve or reject Staff drafts | Pass |
| Admin can approve their own draft | Pass |
| Staff can send an Admin-approved draft | Pass |
| Admin can send an approved draft | Pass |
| The same email cannot be sent twice | Pass |

## 5. Identified Issue

### DE-01: Do Not Contact Functionality Is Not Implemented

**Severity:** High

**Expected behaviour:**

An organisation marked Do Not Contact must not allow email generation, approval or sending.

**Actual behaviour:**

The system does not currently provide the Do Not Contact status or its required email restrictions.

**Required correction:**

Dev must implement the Do Not Contact status and ensure that:

- Draft generation is unavailable.
- Existing drafts cannot be approved or sent.
- Regeneration is unavailable.
- The user receives a clear explanation.
- Direct requests cannot bypass the restriction.

## 6. Final Validation Outcome

The core draft-email workflow is functioning correctly. Staff can generate, edit and submit drafts, while Admin can approve, reject and self-approve drafts. Approved emails can be sent by either Staff or Admin, and duplicate sending is prevented.

The contact status remains Not Yet Contacted throughout drafting and approval and changes to Contacted only after a successful send.

The build cannot be considered fully compliant with all requirements because the Do Not Contact functionality is still missing. The AI-generation and send-failure paths also remain unverified because no failures occurred during testing.