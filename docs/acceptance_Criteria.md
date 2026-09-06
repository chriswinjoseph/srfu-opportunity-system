# Sprint 1 — Acceptance Criteria for Contact Status Logic

## Purpose

This document defines the business rules and acceptance criteria used to determine and manage an organisation's outreach/contact status.

The purpose of this logic is to prevent duplicate outreach and provide a clear view of the current outreach stage for each organisation.

---

# 1. Contact Statuses

The system shall support the following contact statuses:

- Not Yet Contacted
- Contacted
- Interested
- Not Interested
- Do Not Contact

Contact status is therefore not treated as a simple binary contacted/not-contacted value.

---

# 2. Business Rules

## BR-01 — Not Yet Contacted

An organisation shall be considered **Not Yet Contacted** when there is no recorded successful outreach attempt against that organisation.

Example:
A bank has been imported into the database but no outreach has been sent.
**Status: Not Yet Contacted**

---

## BR-02 — Contacted

An organisation shall be considered **Contacted** once an authorised user records that outreach has been sent to the organisation.

Example:
An outreach email has been reviewed, approved and sent to the bank.
**Status: Contacted**

---

## BR-03 — Interested

An organisation shall be considered **Interested** when the organisation responds positively or otherwise indicates interest.

Example:
A bank responds to the outreach and indicates that it would like to discuss the opportunity.
**Status: Interested**

---

## BR-04 — Not Interested

An organisation shall be considered **Not Interested** when the organisation responds and declines further engagement.

Example:
A bank replies stating that it is not interested in participating.
**Status: Not Interested**

---

## BR-05 — Do Not Contact

An organisation shall be considered **Do Not Contact** when it has requested not to be contacted again.

Example:
A bank asks to be removed from future outreach.
**Status: Do Not Contact**

---

# 3. Status Flow

The expected general outreach flow is:

Not Yet Contacted
       ↓
Outreach Sent
       ↓
Contacted
       ↓
Response Received
       ↓
Interested / Not Interested / Do Not Contact

An organisation may remain **Contacted** while awaiting a response.

---

# 4. Acceptance Criteria

## AC-01 — New Organisation

**Given** a new organisation is imported without previous outreach history  
**When** the organisation is saved to the database  
**Then** its status shall default to **Not Yet Contacted**.

---

## AC-02 — Draft Generation

**Given** an organisation is Not Yet Contacted  
**When** an outreach email draft is generated  
**Then** its status shall remain **Not Yet Contacted**.

Generating a draft does not mean outreach has occurred.

---

## AC-03 — Draft Review

**Given** an outreach draft exists  
**When** an authorised user reviews or edits the draft  
**Then** the organisation's status shall not change to Contacted.

---

## AC-04 — Outreach Sent

**Given** an organisation has not previously been contacted  
**When** outreach is recorded as sent  
**Then** the organisation's status shall change to **Contacted**.

---

## AC-05 — Already Contacted Dashboard View

**Given** an organisation has a status of Contacted  
**When** the dashboard is viewed or filtered by Already Contacted  
**Then** the organisation shall appear in the **Already Contacted** view.

---

## AC-06 — Not Yet Contacted Dashboard View

**Given** an organisation has a status of Not Yet Contacted  
**When** the dashboard is viewed or filtered by Not Yet Contacted  
**Then** the organisation shall appear in the **Not Yet Contacted** view.

---

## AC-07 — Existing Outreach History

**Given** Shane's existing dataset identifies an organisation as previously contacted  
**When** that organisation is imported  
**Then** its status shall be imported as **Contacted**.

---

## AC-08 — Prevent Conflicting Status

**Given** an organisation exists in the database  
**When** its contact status is displayed  
**Then** it shall not simultaneously appear as both Contacted and Not Yet Contacted.

---

## AC-09 — Status Persistence

**Given** an organisation's contact status has been saved  
**When** the application is refreshed or reopened  
**Then** the stored contact status shall remain unchanged.

---

## AC-10 — Positive Response

**Given** an organisation has been contacted  
**When** the organisation responds positively or shows interest  
**Then** its status shall be updated to **Interested**.

---

## AC-11 — Negative Response

**Given** an organisation has been contacted  
**When** the organisation responds and declines further engagement  
**Then** its status shall be updated to **Not Interested**.

---

## AC-12 — Do Not Contact Request

**Given** an organisation has been contacted  
**When** the organisation requests not to receive further outreach  
**Then** its status shall be updated to **Do Not Contact**.

The organisation must remain identifiable as Do Not Contact to prevent future unwanted outreach.

---

# 5. Contact Logic Summary

| Situation | Expected Status |
|---|---|
| New organisation with no outreach history | Not Yet Contacted |
| Draft email generated | Not Yet Contacted |
| Draft reviewed or edited | Not Yet Contacted |
| Outreach sent | Contacted |
| Outreach sent, waiting for response | Contacted |
| Positive response received | Interested |
| Organisation declines | Not Interested |
| Organisation requests no further contact | Do Not Contact |

---

# 6. Expected Outcome

The contact-status logic must ensure that:

- Users can clearly identify organisations that have not yet been contacted.
- Sending outreach changes the organisation to Contacted.
- Creating or editing a draft does not incorrectly mark an organisation as contacted.
- Responses can be represented using more detailed statuses.
- Previously contacted organisations are preserved during data import.
- Contact statuses persist after the application is refreshed.
- Organisations are not simultaneously classified as both Contacted and Not Yet Contacted.
- Do Not Contact organisations can be clearly identified to prevent further unwanted outreach.
