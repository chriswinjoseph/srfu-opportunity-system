# Sprint 1 — Functional and Non-Functional Requirements

## Purpose

This document defines the Phase 1 functional requirements for the Safe Roads for Us Community Bank Outreach & Tracking Tool.

The system is intended to reduce the current manual workload involved in identifying community banks, tracking previous outreach, preparing outreach emails, and identifying relevant clubs after a bank shows interest.

---

##  Functional Requirements

### 1 — Central Database

The system shall maintain a central database containing records for:

- Banks
- Branches
- Clubs
- Contacts
- Opportunities

### 2 — Bank Records

The system shall allow bank records to be stored and retrieved.

Each bank record shall contain sufficient information to identify the bank, its region, public contact information, and its outreach status.

### 3 — Branch Records

The system shall allow individual branches to be associated with a parent bank.

Each branch shall contain its own location and publicly available contact details where available.

### 4 — Club Records

The system shall allow sporting clubs and youth organisations to be stored.

Where known, a club shall be able to be associated with a bank or branch that currently supports it.

### 5 — Contact Records

The system shall store publicly available contact information associated with banks, branches, and clubs.

### 6 — Opportunity Records

The system shall allow an opportunity record to represent an outreach or potential partnership opportunity associated with an organisation.

The opportunity record shall allow the system to track whether outreach has occurred and the current outreach status.

### 7 — Import Existing Dataset

The system shall support importing Shane’s existing exported list of banks and clubs into the central database.

The imported data shall be validated before being stored to reduce duplicates, missing values and incorrectly formatted records.

### 8 — Public Data Collection

The system shall support importing or collecting publicly available bank and club information.

The system shall not require private or sensitive information.

### 9 — Access Control

The system shall restrict access to the dashboard and organisation records to authorised users only.

Unauthenticated users shall not be able to access protected dashboard functionality.

Authorised users shall be able to view and manage organisation records according to the permissions available to them.

### 10 — Manual Bank Record Creation

The system shall allow an authorised user to manually create a bank record when a bank is not available through the imported or collected dataset.

The user shall be able to enter the required bank information and save the new record to the central database.

The manually created record should support:

- Bank name
- Region
- Website URL, if available
- Public email, if available
- Public phone, if available
- Outreach status

---

## 3. Dashboard Functional Requirements

### 11 — Organisation Dashboard

The system shall provide a dashboard that displays organisations stored in the database.

At minimum, the dashboard should allow the user to distinguish between:

- Already Contacted
- Not Yet Contacted

### 12 — Contact Status Display

Every organisation displayed on the dashboard shall have a contact status.

The status shall clearly indicate whether the organisation has already been contacted.

### 13 — Organisation Details

The user shall be able to view relevant information for an organisation, including:

- organisation name,
- organisation type,
- location/region,
- public contact information,
- contacted/not-yet-contacted status.

### 14 — Search and Filter

The dashboard should allow the user to locate organisations by relevant information such as:

- organisation name,
- region,
- organisation type,
- contact status.

### 15 — Generate Draft Outreach Email

For an organisation that has not yet been contacted, the system shall allow an authorised user to generate a draft outreach email.

### 16 — Human Approval Before Sending

Generated outreach emails shall not be sent automatically.

The authorised user must be able to review and approve the draft before sending.

---

##  Non-Functional Requirements

### 1 — Usability

The dashboard shall provide a simple and low-click interface.

Functionality shall take priority over visual complexity.

### 2 — Data Privacy

Only publicly available organisational and contact information shall be used during Phase 1.

### 3 — Cost Control

AI/API usage shall remain low and predictable.

The system shall avoid unnecessary external-platform integrations.

### 4 — Maintainability

The system and data structure shall be documented sufficiently for future developers and maintainers.

### 5 — Access Security

Protected application data shall only be accessible after successful authentication.