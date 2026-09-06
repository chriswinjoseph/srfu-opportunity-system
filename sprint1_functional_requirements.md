# Sprint 1 — Functional Requirements

## Purpose

This document defines the Phase 1 functional requirements for the Safe Roads for Us Community Bank Outreach & Tracking Tool.

The system is intended to reduce the current manual workload involved in identifying community banks, tracking previous outreach, preparing outreach emails, and identifying relevant clubs after a bank shows interest.

---

## FR-01 — Central Database

The system shall maintain a central database containing records for:

- Banks
- Branches
- Clubs
- Contacts
- Opportunities

---

## FR-02 — Bank Records

The system shall allow bank records to be stored and retrieved.

Each bank record shall contain sufficient information to identify:

- Bank name
- Region
- Public contact information
- Current outreach/contact status

---

## FR-03 — Branch Records

The system shall allow individual branches to be associated with a parent bank.

Each branch shall contain its own location and publicly available contact details where available.

---

## FR-04 — Club Records

The system shall allow sporting clubs and youth organisations to be stored.

Where known, a club shall be able to be associated with a bank or branch that currently supports it.

---

## FR-05 — Contact Records

The system shall store publicly available contact information associated with:

- Banks
- Branches
- Clubs

---

## FR-06 — Opportunity Records

The system shall allow an opportunity record to represent an outreach or potential partnership opportunity associated with an organisation.

The opportunity record shall allow the system to track:

- Whether outreach has occurred
- Current outreach status
- Outreach method
- Draft email
- Approval information
- Relevant notes

---

## FR-07 — Import Existing Dataset

The system shall support importing Shane's existing exported list of banks and clubs into the central database.

Before records are stored, imported data shall be validated to identify:

- Duplicate records
- Missing values
- Incorrectly formatted records

Previously contacted organisations must retain their existing outreach status where that information is available.

---

## FR-08 — Public Data Collection

The system shall support importing or collecting publicly available bank and club information.

The system shall not require private or sensitive information.

---

## FR-09 — Access Control

The system shall restrict access to the dashboard and organisation records to authorised users only.

Unauthenticated users shall not be able to access protected dashboard functionality.

Authorised users shall be able to view and manage organisation records according to their available permissions.

---

## FR-10 — Manual Bank Record Creation

The system shall allow an authorised user to manually create a bank record when the bank is not available through imported or collected data.

The user shall be able to enter:

- Bank name
- Region
- Website URL, if available
- Public email, if available
- Public phone, if available
- Outreach status

The bank name and region shall be required.

The new bank record shall be saved to the central database and displayed on the dashboard.

---

## FR-11 — Organisation Dashboard

The system shall provide a dashboard displaying organisations stored in the database.

The dashboard shall allow users to distinguish organisations based on their contact status.

At minimum, users shall be able to identify organisations that are:

- Already Contacted
- Not Yet Contacted

---

## FR-12 — Contact Status Display

Every organisation displayed on the dashboard shall have a contact status.

Supported statuses are:

- Not Yet Contacted
- Contacted
- Interested
- Not Interested
- Do Not Contact

The status shall allow the user to understand the current stage of outreach for each organisation.

---

## FR-13 — Organisation Details

The user shall be able to view relevant information for an organisation, including:

- Organisation name
- Organisation type
- Location/region
- Public contact information
- Contact/outreach status

---

## FR-14 — Search and Filter

The dashboard shall allow the user to locate organisations using relevant information such as:

- Organisation name
- Region
- Organisation type
- Contact status

---

## FR-15 — Generate Draft Outreach Email

For an organisation that has not yet been contacted, the system shall allow an authorised user to generate a draft outreach email.

Generating a draft shall not automatically mark the organisation as contacted.

---

## FR-16 — Human Approval Before Sending

Generated outreach emails shall not be sent automatically.

An authorised user must be able to:

1. Generate the draft
2. Review the draft
3. Edit the draft if required
4. Approve the draft
5. Send the outreach

The organisation shall only be considered contacted once outreach has been recorded as sent.

---

## Phase 1 Functional Summary

The Phase 1 system must therefore support:

- Centralised organisation records
- Banks, branches, clubs, contacts and opportunities
- Existing dataset import
- Public data collection/import
- Manual bank creation
- User access control
- Organisation dashboard
- Contact status tracking
- Organisation search and filtering
- Draft outreach generation
- Human review and approval before sending
- Preservation of existing outreach history