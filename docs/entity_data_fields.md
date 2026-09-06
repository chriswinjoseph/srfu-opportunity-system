# Sprint 1 — Entity Data Fields

## Purpose

This document defines the data fields required for the main entities used by the Safe Roads for Us Community Bank Outreach & Tracking Tool.

The Phase 1 system will maintain records for:

- Banks
- Branches
- Clubs
- Contacts
- Opportunities

---

## 1. Bank

| Field | Purpose |
|---|---|
| bank_name | Bank name |
| website_url | Public website |
| region | State/region served |
| contact_status | Current outreach/contact status |
| public_email | General public email, if available |
| public_phone | Public phone number, if available |
| source_url | Source where the information was obtained |
| date_added | Date the bank record was added |
| last_updated | Date the bank record was last updated |

### Contact Status Options

The contact_status field may contain:

- Not Yet Contacted
- Contacted
- Interested
- Not Interested
- Do Not Contact

---

## 2. Branch

| Field | Purpose |
|---|---|
| branch_name | Branch name |
| address | Branch address |
| suburb | Suburb |
| state | State |
| postcode | Postcode |
| region | Geographic grouping |
| public_email | Public contact email |
| public_phone | Public contact phone |
| website_url | Branch/public webpage |
| contact_status | Current outreach/contact status |

---

## 3. Club

| Field | Purpose |
|---|---|
| club_name | Club or organisation name |
| club_type | Sporting club, youth organisation, etc. |
| suburb | Club location |
| state | State |
| region | Region |
| website_url | Public website |
| public_email | Public email |
| public_phone | Public phone |
| supported_by_bank_id | Bank supporting the club, if known |
| contact_status | Current outreach/contact status |

---

## 4. Contact

| Field | Purpose |
|---|---|
| contact_id | Unique contact identifier |
| organisation_name | Organisation the contact belongs to |
| organisation_type | Bank, Branch, or Club |
| contact_name | Public contact person's name, if available |
| role | Role/title, if publicly available |
| email | Public email |
| phone | Public phone |
| source_url | Source of the contact information |
| last_verified | Date the contact details were last checked |

---

## 5. Opportunity

| Field | Purpose |
|---|---|
| opportunity_id | Unique opportunity identifier |
| organisation_name | Related organisation |
| organisation_type | Bank, Branch, or Club |
| status | Current outreach status |
| date_created | Date the opportunity was created |
| date_contacted | Date the organisation was first contacted |
| outreach_method | Method used for outreach, e.g. email |
| draft_email | Generated draft outreach email |
| approved | Whether the draft was approved |
| approved_by | User who approved the draft |
| date_approved | Date the draft was approved |
| notes | Basic relevant notes |

---

## Data Requirements

- The system must store the above entities in a central database.
- Branches must be able to be associated with their parent bank.
- Clubs may be associated with the bank or branch supporting them where known.
- Contacts must contain only publicly available information.
- Opportunity records must support tracking outreach activity.
- Records imported from existing datasets must be validated before being stored.
- Authorised users must be able to manually create bank records when required.
