# Business Logic Test Cases for Contact Status Transitions

## Purpose

These test cases verify that an organisation’s `contact_status` changes from **Not Yet Contacted** to **Contacted** only when valid outreach has occurred.

The same tests apply independently to banks, branches and clubs.

## 1. Valid Transition Test Cases

### TC-1 Successful Email Send

| Field | Details |
| --- | --- |
| Test case ID | TC-1 |
| Scenario | Outreach email is successfully sent through the system |
| Precondition | The organisation has a status of Not Yet Contacted |
| Steps | Generate the draft, review it, approve it and successfully send the email |
| Expected result | The organisation changes to Contacted only after the system confirms that the email was sent |
| Expected stored information | Contact status, contact date and outreach method are saved |

### TC-2 External Outreach Recorded

| Field | Details |
| --- | --- |
| Test case ID | TC-2 |
| Scenario | An authorised user records contact completed outside the system |
| Precondition | The organisation has a status of Not Yet Contacted |
| Steps | Record that the organisation was contacted by phone or manually sent email |
| Expected result | The organisation changes to Contacted |
| Expected stored information | Outreach method and contact date are saved |

### TC-3 Previously Contacted Organisation Imported

| Field | Details |
| --- | --- |
| Test case ID | TC-3 |
| Scenario | An imported record contains confirmed previous outreach history |
| Precondition | The organisation does not already exist in the system |
| Steps | Import the record with evidence that previous contact occurred |
| Expected result | The organisation is created with the status Contacted |
| Expected stored information | Imported contact history is retained |

## 2. Invalid Transition and Edge-Case Tests

### TC-1 Draft Generated but Not Sent

| Field | Details |
| --- | --- |
| Test case ID | TC-1 |
| Scenario | A draft email is generated |
| Precondition | The organisation is Not Yet Contacted |
| Steps | Generate and save a draft without sending it |
| Expected result | The organisation remains Not Yet Contacted |

### TC-2 Draft Reviewed or Edited

| Field | Details |
| --- | --- |
| Test case ID | TC-2 |
| Scenario | An authorised user reviews or edits a draft |
| Precondition | The organisation is Not Yet Contacted and a draft exists |
| Steps | Open, review, edit and save the draft |
| Expected result | The organisation remains Not Yet Contacted |

### TC-3 Draft Approved but Not Sent

| Field | Details |
| --- | --- |
| Test case ID | TC-3 |
| Scenario | A draft is approved but has not been sent |
| Precondition | The organisation is Not Yet Contacted and an approved draft exists |
| Steps | Approve the draft without sending it |
| Expected result | The organisation remains Not Yet Contacted |

### TC-4 Email Send Fails

| Field | Details |
| --- | --- |
| Test case ID | TC-4 |
| Scenario | The system attempts to send an email but the send fails |
| Precondition | The organisation is Not Yet Contacted |
| Steps | Attempt to send the approved email and simulate a send failure |
| Expected result | The organisation remains Not Yet Contacted and the user is shown an error |
| Additional check | No contact date is recorded |

### TC-5 Unauthorised User Attempts a Manual Change

| Field | Details |
| --- | --- |
| Test case ID | TC-5 |
| Scenario | An unauthorised user attempts to mark an organisation as Contacted |
| Precondition | The organisation is Not Yet Contacted |
| Steps | Attempt to record external outreach without the required permission |
| Expected result | The change is rejected and the organisation remains Not Yet Contacted |

### TC-6 Related Organisations Remain Independent

| Field | Details |
| --- | --- |
| Test case ID | TC-6 |
| Scenario | A bank is contacted while its branches and supported clubs have not been contacted |
| Precondition | The bank, branches and clubs are all Not Yet Contacted |
| Steps | Successfully send outreach to the bank |
| Expected result | Only the bank changes to Contacted; its branches and clubs remain Not Yet Contacted |

### TC-7 Follow-Up Outreach to an Already Contacted Organisation

| Field | Details |
| --- | --- |
| Test case ID | TC-7 |
| Scenario | Follow-up outreach is sent to an organisation that is already Contacted |
| Precondition | The organisation is Contacted |
| Steps | Send or record another valid outreach attempt |
| Expected result | The organisation remains Contacted and the follow-up is recorded separately |

### TC-8 Organisation Responds After Being Contacted

| Field | Details |
| --- | --- |
| Test case ID | TC-8 |
| Scenario | A contacted organisation provides a positive or negative response |
| Precondition | The organisation is Contacted |
| Steps | Record the organisation’s response |
| Expected result | `contact_status` remains Contacted and only `opportunity.status` changes to Interested, Not Interested or Do Not Contact |

### TC-9 Email Bounces After a Successful Send

| Field | Details |
| --- | --- |
| Test case ID | TC-9 |
| Scenario | An email is successfully submitted for sending but later bounces |
| Precondition | The organisation changed to Contacted after the successful send |
| Steps | Record the later bounce notification |
| Expected result | The organisation remains Contacted because outreach was sent, while the delivery failure is recorded separately |

## 3. Tests for the Email Workflow States

No new intermediate `contact_status` was added. Draft, Awaiting Approval and Approved are email workflow states, not organisation contact statuses.

The following tests confirm that these states do not incorrectly change `contact_status`.

### TC-1 Draft State

| Field | Details |
| --- | --- |
| Test case ID | TC-1 |
| Email state | Draft |
| Expected contact status | Not Yet Contacted |

### TC-2 Awaiting Approval State

| Field | Details |
| --- | --- |
| Test case ID | TC-2 |
| Email state | Awaiting Approval |
| Expected contact status | Not Yet Contacted |

### TC-3 Approved State

| Field | Details |
| --- | --- |
| Test case ID | TC-3 |
| Email state | Approved but not sent |
| Expected contact status | Not Yet Contacted |

The organisation only becomes Contacted when the email moves to **Sent**.

## 4. Import Behaviour Test Cases

### TC-1 Import Without Previous Outreach

| Field | Details |
| --- | --- |
| Test case ID | TC-1 |
| Scenario | An organisation is imported without previous outreach history |
| Steps | Import a valid organisation record without a contacted value or contact date |
| Expected result | The organisation is assigned Not Yet Contacted |

### TC-2 Import With Confirmed Previous Outreach

| Field | Details |
| --- | --- |
| Test case ID | TC-2 |
| Scenario | An organisation is imported with confirmed previous contact |
| Steps | Import a valid organisation record containing previous outreach history |
| Expected result | The organisation is assigned Contacted |

### TC-3 Import Containing Conflicting Information

| Field | Details |
| --- | --- |
| Test case ID | TC-3 |
| Scenario | An imported record says Contacted but contains no supporting outreach information |
| Steps | Import the conflicting record |
| Expected result | The record is flagged for review and must not silently overwrite an existing valid contact status |

## Expected Overall Result

The organisation should only transition from **Not Yet Contacted** to **Contacted** after:

- A successful email send;
- Authorised recording of external outreach; or
- Importing confirmed previous outreach history.

Draft generation, review, editing, approval, failed sending and changes attempted by unauthorised users must not cause the transition.