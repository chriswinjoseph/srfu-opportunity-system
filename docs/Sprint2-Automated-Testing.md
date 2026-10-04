# Test Execution Report: Dashboard, Add Organisation and Draft Email Flows

## 1. Test Information

- **Task:** Test dashboard, Add Organisation and draft-email flows
- **Tester:** Savio Simon
- **Testing type:** Functional testing
- **Scope:** Dashboard, organisation creation, duplicate detection, email generation and email approval
- **Overall result:** Several workflows passed, but issues were found with filtering, the Clear button, AI draft generation and editing after approval.

## 2. Test Results

| ID | Test Scenario | Expected Result | Actual Result | Status |
|---|---|---|---|---|
| T01 | Organisation-list grouping | Organisations must appear under the correct **Contacted** or **Not Yet Contacted** group. | Organisations appeared under the correct groups. | Pass |
| T02 | Search and filter controls | Organisation name, organisation type, region and contact-status controls must return the correct results. | Organisation-name and organisation-type searches worked. Region and contact-status filters did not work. | Partial Fail |
| T03 | Empty and error states | The system must display an appropriate empty or error state without crashing. | The page handled the tested condition without crashing. | Pass |
| T04 | Create an organisation with valid details | One organisation must be created and a confirmation must be displayed. | The organisation was created successfully. | Pass |
| T04A | Clear the Add Organisation form | Selecting **Clear** must remove all information entered into the form. | The Clear button did not remove the entered information. | Fail |
| T05 | Missing or invalid fields | Required-field and format errors must appear, and the organisation must not be created. | Required-field warnings appeared. The email field also displayed an **Enter a valid email address** warning when an invalid email was entered. | Pass |
| T06 | Duplicate detection | Exact duplicates must be blocked, while possible duplicates must display a warning and matching organisation. | The exact-duplicate warning was displayed. Partial matching information produced a possible-duplicate warning, showed the matching organisation and provided **Continue Anyway** and **Cancel** options. | Pass |
| T07 | Generate an AI email draft | The AI must generate and populate the expected email fields, using fallback wording when optional information is missing. | An unexpected-error warning appeared, and a hard-coded email was displayed instead of an AI-generated draft. | Fail |
| T08 | Approval workflow | A draft must move from **Pending Review** to **Approved** or **Rejected**, depending on the approver's action. | Both the Reject and Approve actions worked correctly. | Pass |
| T09 | Edit after approval | Editing an approved email must invalidate its approval and return it to **Pending Review**. | The approved email became read-only and could not be edited or returned to Pending Review. | Fail |
| T10 | Send-failure handling | A failed send must be caught and marked as **Send Failed**, while the organisation remains **Not Yet Contacted**. | This scenario was not tested. | Not Tested |
| T11 | Acceptance-criteria coverage | Each acceptance criterion in the relevant functional-requirements documents must be covered by a test. | The completed tests cover the primary dashboard, Add Organisation and draft-email workflows. | Completed |
| T12 | Full test execution and issue logging | The full set of tests must be run, and all identified issues must be recorded and passed to Dev. | Testing was completed, and the identified issues were documented for Dev. | Completed |

## 3. Contact-Status Clarification

Approving an email must not change the organisation's `contact_status` to **Contacted**.

The correct behaviour is:

- Draft generated → **Not Yet Contacted**
- Draft submitted for approval → **Not Yet Contacted**
- Draft rejected → **Not Yet Contacted**
- Draft approved → **Not Yet Contacted**
- Email successfully sent → **Contacted**
- Email sending fails → **Not Yet Contacted**

Therefore, the organisation remaining **Not Yet Contacted** after the email was approved is correct and should not be recorded as a defect.

## 4. Identified Defects

### DEF-01: Region Filter Does Not Work

- **Severity:** Medium
- **Steps to reproduce:**
  1. Open the organisation dashboard.
  2. Select a region.
  3. Apply the filter.
- **Expected result:** Only organisations from the selected region must be displayed.
- **Actual result:** The displayed organisations are not filtered by region.

### DEF-02: Contact-Status Filter Does Not Work

- **Severity:** Medium
- **Steps to reproduce:**
  1. Open the organisation dashboard.
  2. Select **Contacted** or **Not Yet Contacted**.
  3. Apply the filter.
- **Expected result:** Only organisations with the selected contact status must be displayed.
- **Actual result:** The filter does not change the displayed organisations.

### DEF-03: Clear Button Does Not Reset the Add Organisation Form

- **Severity:** Low
- **Steps to reproduce:**
  1. Open the Add Organisation form.
  2. Enter information into the form fields.
  3. Select **Clear**.
- **Expected result:** All entered information must be removed.
- **Actual result:** The information remains in the form.

### DEF-04: AI Draft Generation Fails

- **Severity:** High
- **Steps to reproduce:**
  1. Open an organisation with valid contact information.
  2. Select the option to generate an AI email draft.
- **Expected result:** The system must generate an email using the relevant organisation and contact information.
- **Actual result:** The system displays the following warning:

> An unexpected error occurred while generating the email draft. Please try again.

A hard-coded email is then displayed instead of an AI-generated draft.

### DEF-05: Approved Email Cannot Be Returned for Editing

- **Severity:** High
- **Steps to reproduce:**
  1. Generate an email draft.
  2. Submit the draft for approval.
  3. Approve the email.
  4. Attempt to edit or return the approved email to draft.
- **Expected result:** Editing must invalidate the existing approval and return the email to **Pending Review**.
- **Actual result:** The approved email becomes read-only and cannot be edited or returned to Pending Review.

## 5. Final Test Summary

The following functions worked correctly:

- Contacted and Not Yet Contacted organisation grouping
- Organisation-name search
- Organisation-type filtering
- Successful organisation creation
- Required-field validation
- Email-format validation
- Exact-duplicate detection
- Possible-duplicate detection
- Email approval
- Email rejection

The following issues require correction:

- Region filtering
- Contact-status filtering
- Add Organisation Clear button
- AI email generation
- Editing an approved email and returning it to Pending Review

The send-failure scenario was not tested and must be checked separately.

## 6. Handoff Note for Dev

Testing identified issues with the region and contact-status filters, the Add Organisation Clear button, AI draft generation and editing an approved email.

Approval correctly leaves the organisation as **Not Yet Contacted**. The organisation should change to **Contacted** only after the email has been successfully sent.

The documented defects should be reviewed and corrected by Dev. The send-failure scenario also requires testing when the sending functionality is available.