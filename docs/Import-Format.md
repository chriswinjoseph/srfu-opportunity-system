# Import workbook format

This describes what **Data > Import Data** accepts. It is derived from the parser
(`intake/workbook.py`, `intake/evidence.py`, `intake/normalise.py`); the downloadable templates are
generated from the same definitions (`intake/import_template.py`), and tests check that they agree.

Two formats are accepted. The page chooses by the sheets it finds:

| Sheets in the file | Format |
|---|---|
| `Organisations` **and** `Contacts` | **Two-sheet client workbook** (original format, with outreach evidence) |
| `Organisations` only (other sheets, including `Instructions`, are ignored) | **Single-sheet workbook** |
| One sheet of any other name (plus an optional `Instructions` sheet) | **Single-sheet workbook** |
| `Contacts` without `Organisations`, or several sheets and none named `Organisations` | Rejected with a message naming the sheets found |

## Getting a correct file

* **Data > Import Data > Download template (.xlsx)** is the single-sheet template: the six minimum
  headers and an `Instructions` sheet, no records. It cannot be previewed until a row is added.
* **Download synthetic example (.xlsx)** is a small invented single-sheet file (names start
  "EXAMPLE ONLY", addresses are `example.test`). It includes an unsupported column and a
  name/email combination that is flagged for review, to show the preview. It must not be imported
  into the real system.
* The two-sheet template and example are under "Using the two-sheet client workbook" on the page.
* All downloads are Admin-only (Staff and signed-out users are refused) and hold no client data.
* A CSV or any other file **cannot simply be renamed to .xlsx**; it is rejected as unreadable.
  Open the original in Excel, arrange it like the template and Save As > Excel Workbook (.xlsx).

## Single-sheet workbook

One row per organisation. Minimum headers (row 1; case and surrounding spaces do not matter):

| Header | Value |
|---|---|
| `organisation_id` | **Required**, unique. Kept as the source identifier |
| `bank_name` | **Required**. The organisation's own name |
| `state` | **Required**. ACT, NSW, NT, QLD, SA, TAS, VIC, WA or the full name |
| `contact_names` | May be blank |
| `emails` | May be blank |
| `overall_status` | May be blank. Kept for reference only (see "Status" below) |

A row missing an ID, a name or a recognised state is reported (row, field, action) and skipped;
other rows continue. A header that appears twice is refused (it is unclear which values to use).

**Additional supported columns** (any order; blank cells stay blank): `organisation_type` (Bank,
Branch, Club; absent = Bank; present but blank/other = held for review), `parent_bank_name`,
`parent_bank_state`, `region`, `suburb`, `postcode`, `address`, `website_url`, `public_phone`,
`public_email`, `club_type`, `any_human_reply_received`, `all_contacts_replied`,
`first_observed_date`, `last_observed_date`, `needs_verification_flag`. `num_contacts` and
`contact_types` are recognised but not stored. Any other column is **unsupported**: it is ignored and
named in a warning on the preview, so nothing in it is silently lost or silently used.

**Several contacts in one row.** Separate names with a semicolon, `|` or a new line, and emails with
a semicolon, comma, space or new line. A comma is never a name separator ("Smith, Jo" is one name).

| Row has | Result |
|---|---|
| one name and one email | contact created with that name |
| emails only | one contact per email, no names |
| several emails and any names, or several names and any emails | one contact per email **without names**; the combination is flagged **for review** and the names are kept in the result message and on the organisation's source record. Names are never paired with emails by their order |
| names but no email | no contact (a contact needs an email); reported as a problem |
| an invalid email | that contact is skipped and reported; the others continue |

`(unspecified)` and similar placeholders count as blank. The preview counts these ("Name / email
combinations to review", "Contacts that cannot be created") and lists them before anything is saved.

**Status.** The file has no per-contact outreach evidence, so `overall_status` never marks an
organisation Contacted. Blank or "Not Yet Contacted" imports as Not Yet Contacted. "Contacted",
"Partially Contacted" or any value that is not recognised is an unsupported claim: the organisation is
**held for review** (an Admin may confirm Contacted or Not Yet Contacted, or reject it) and the reason
is shown. An existing Contacted organisation is never downgraded. Replies are evidence only and never
set Interested. For Contacted with evidence, use the two-sheet workbook.

## Two-sheet client workbook

### Workbook rules

* Sheets named exactly `Organisations` and `Contacts` (case-sensitive). Other sheets are ignored.
* Row 1 = headers. Header case and surrounding spaces do not matter; spelling and underscores do.
  Extra columns are ignored but named as unsupported on the preview. Every required header must exist even if its values are not used.
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

## What happens to the file (both formats)
1. Validate: structure errors name the missing sheet or columns and stop before anything is
   created. A failed upload creates no organisations or contacts.
2. Preview: counts and row problems (row number, field, action). Nothing is saved.
3. Confirm: each organisation is processed in its own transaction; bad rows are reported and do
   not stop good ones. Possible duplicates are held for review, never merged.
4. Repeat imports are safe: the same file creates no duplicates (organisations are matched by source
   ID, then name and state; contacts by source contact ID and by email within the organisation), the
   preview warns that the exact file was imported before, and a preview can be confirmed only once.
   A later file never erases values an earlier import recorded (source identifiers, verification flags,
   observed dates, outreach evidence); blank cells and missing columns are not treated as changes.
5. Admin-only throughout: upload, preview, confirmation and downloads.
