# Contact Status Requirements Review

## 1. Review of Sections 6 and 7 Against the Project Brief

Sections 6 and 7 were reviewed against the project brief and Shane’s intended outreach workflow.

The requirements correctly establish that every organisation begins as **Not Yet Contacted** when there is no previous outreach history. Generating, reviewing or editing a draft email does not change the organisation’s status. The status only changes to **Contacted** after outreach has been recorded as sent.

This supports the brief’s aim of helping Shane distinguish between organisations that have and have not already received outreach, reducing the risk of contacting the same organisation twice.

However, the brief also states that when a bank responds positively, Shane must identify the clubs supported by that bank. Sections 6 and 7 define **Interested**, **Not Interested** and **Do Not Contact**, but do not contain acceptance criteria explaining how these responses are recorded or what workflow should occur afterwards.

## 2. Review of the Binary Status Model

The binary model of **Not Yet Contacted** and **Contacted** is sufficient for showing whether outreach has been sent.

It does not fully cover what happens after a bank responds because a response can have different outcomes:

- The bank may be interested.
- The bank may not be interested.
- The bank may request no further contact.

Therefore, the binary model should remain responsible only for identifying whether outreach has occurred. The response and outcome of the outreach should be tracked separately.

For example, after a bank responds positively:

- `contact_status` remains **Contacted**, because outreach has occurred.
- `opportunity.status` changes to **Interested**, because that is the outcome of the outreach.
- The identify-supported-clubs workflow begins.

## 3. Review of Contact Status and Opportunity Status

The requirements currently include `contact_status` on Bank, Branch and Club records. The Opportunity entity also contains `opportunity.status`.

Both fields appear to track part of the outreach process, but their separate responsibilities are not clearly defined. This could result in conflicting information, such as an organisation having `contact_status = Interested` while its opportunity has another status.

The fields should be separated as follows:

- `contact_status` tracks whether outreach has occurred:
  - Not Yet Contacted
  - Contacted

- `opportunity.status` tracks the response or outcome:
  - Interested
  - Not Interested
  - Do Not Contact

This means `contact_status` answers **“Has this organisation been contacted?”**, while `opportunity.status` answers **“What was the result of the contact?”**

The PM and Shane must confirm this separation before Dev implements the complete status workflow.

## 4. Numbered Issues for New or Updated Acceptance Criteria

1. Define that `contact_status` only contains **Not Yet Contacted** or **Contacted**.

2. Define that `opportunity.status` records **Interested**, **Not Interested** or **Do Not Contact**.

3. Define how the system keeps `contact_status` and `opportunity.status` consistent.

4. Define that an organisation changes to Contacted only after the system confirms that outreach was successfully sent.

5. Define that a failed email does not change the organisation to Contacted.

6. Define how a bounced email is recorded after the original send was successful.

7. Define how Shane records contact completed outside the system, such as a phone call or manually sent email.

8. Define that a positive bank response changes `opportunity.status` to Interested.

9. Define that an Interested bank triggers the identify-supported-clubs workflow.

10. Define that a negative response changes `opportunity.status` to Not Interested.

11. Define that a request for no further communication changes `opportunity.status` to Do Not Contact.

12. Define that an organisation marked Do Not Contact cannot have another outreach draft generated or sent.

13. Define where Interested, Not Interested and Do Not Contact organisations appear on the dashboard.

14. Define how an authorised user corrects a status selected by mistake.

15. Define whether the system records who changed the status and when it was changed.

16. Define how missing, invalid or conflicting statuses in imported records are handled.

## 5. Impact on Dev’s Sprint 2 Build

### Blocking Dev’s Sprint 2 Build

The following decisions must be resolved before Dev implements the complete contact workflow:

- The separation between `contact_status` and `opportunity.status`.
- The event that changes an organisation from Not Yet Contacted to Contacted.
- The behaviour when an email fails to send.
- The status changes caused by positive and negative responses.
- The trigger for identifying supported clubs after a positive response.
- The restriction applied to organisations marked Do Not Contact.
- The dashboard location of Interested, Not Interested and Do Not Contact records.

### Can Be Resolved in Parallel

The following issues can be refined while development continues:

- How manually completed phone calls or emails are recorded.
- How bounced emails are displayed after a successful send.
- How an incorrectly selected status is corrected.
- Whether status-change history records the user, date and time.
- How unusual or conflicting imported statuses are reviewed.