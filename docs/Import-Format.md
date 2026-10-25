# Import workbook format

This describes what **Data > Import Data** accepts. It is derived from the parser
(`intake/workbook.py`, `intake/evidence.py`, `intake/normalise.py`); the on-page instructions and
the downloadable template are generated from the same definitions
(`intake/import_template.py`), and tests check that they agree.

## Getting a correct file

* **Data > Import Data > Download blank template (.xlsx)** gives the sheets and headers with no
  records. It cannot be previewed until at least one organisation row is added; a headers-only
  file is rejected with a message saying so.
* **Download synthetic example (.xlsx)** is a small invented workbook (names start "EXAMPLE
  ONLY", addresses are `example.test`) showing a filled file. It imports cleanly but must not be
  imported into the real system.
* Both downloads are Admin-only (Staff and signed-out users are refused). Neither holds client
  data or credentials.
* A CSV or any other file **cannot simply be renamed to .xlsx**; it is rejected as unreadable.
  Open the original in Excel, arrange it like the template and Save As > Excel Workbook (.xlsx).

## Workbook rules

* Sheets named exactly `Organisations` and `Contacts` (case-sensitive). Other sheets are ignored.
* Row 1 = headers. Header case and surrounding spaces do not matter; spelling and underscores do.
  Extra columns are ignored. Every required header must exist even if its values are not used.
* Up to 8 MB and 20,000 rows per sheet. Cell values are read as saved (formulas must have been
  calculated by Excel).
* `Contacts` may have no rows. `Organisations` needs at least one.

### Organisations: required headers
`organisation_id` (required value, unique), `bank_name` (required value; the organisation's own
name even for a Branch or Club), `state` (required value), `num_contacts`, `contact_names`,
`emails`, `contact_types` (informational only), `any_human_reply_received`,
`all_contacts_replied`, `overall_status` (stored for reference, never used to set the status),
`first_observed_date`, `last_observed_date`, `needs_verification_flag`.

### Organisations: optional headers
`organisation_type` (Bank / Branch / Club; if the column is absent everything is a Bank; if it
is present a blank or other value holds the row for review), `parent_bank_name`,
`parent_bank_state`, `region`, `suburb`, `postcode`, `address`, `website_url`, `public_phone`,
`public_email`, `club_type`. Blank cells stay blank.

### Contacts: required headers
`contact_id` (unique per contact), `organisation_id`, `bank_name`, `state` (informational),
`contact_name` (optional; blank or `(unspecified)` is stored as empty), `email` (required value
for the contact; invalid or missing skips that contact only), `contact_type`,
`name_needs_verification`, `bank_affiliation_needs_verification`, `first_observed_date`,
`last_observed_date`, `sent_to_by_srfu`, `human_reply_received`, `contact_status`.

### How contacts link to organisations
A contact row repeats its organisation's `organisation_id`. Several contacts may share one id:
the organisation is created or matched once and each valid contact attached. A contact whose id is
not on the Organisations sheet is reported and skipped. Contacts are matched on `contact_id` and
on email within the organisation, so re-importing the same file creates nothing new.

### Accepted values
* **State:** ACT, NSW, NT, QLD, SA, TAS, VIC, WA, or the full name.
* **TRUE/FALSE columns:** TRUE, FALSE, Yes, No, Y, N, 1, 0, T, F; anything else is read as blank.
* **Dates:** an Excel date, `2025-01-31` or `31/01/2025`; anything else is read as blank.
* **`contact_status`** (per contact; blank = no history):

| Value | Organisation becomes | `sent_to_by_srfu` must be | `human_reply_received` must be |
|---|---|---|---|
| `sent_and_human_reply_received` | Contacted | TRUE | TRUE |
| `sent_no_human_reply_found` | Contacted | TRUE | FALSE |
| `delivery_failure_recorded` | Not Yet Contacted | either | FALSE |
| `human_inbound_only` | Not Yet Contacted | FALSE | TRUE |
| `copied_or_automated_only` | Not Yet Contacted | FALSE | either |
| `no_outreach_history` | Not Yet Contacted | FALSE | FALSE |

One confirmed successful outgoing email makes the organisation Contacted. An unrecognised value
or contradictory flags hold the organisation for review (no guess). Replies are kept as evidence;
they never set Interested.

### Branches and clubs
Include `organisation_type`. A Branch needs `parent_bank_name` (and `parent_bank_state` if it
differs) naming a bank that already exists, otherwise it is reported incomplete. Clubs may add
`club_type`, `suburb`, `postcode`.

## What happens to the file
1. Validate: structure errors name the missing sheet or columns and stop before anything is
   created. A failed upload creates no organisations or contacts.
2. Preview: counts and row problems (row number, field, action). Nothing is saved.
3. Confirm: each organisation is processed in its own transaction; bad rows are reported and do
   not stop good ones. Possible duplicates are held for review, never merged.
