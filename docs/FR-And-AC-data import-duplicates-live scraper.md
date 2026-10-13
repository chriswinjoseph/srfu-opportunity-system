# Planning: Functional Requirements and Acceptance Criteria — Real Data Import, Duplicates and Live Scraper

## 1. Purpose

The purpose of this requirement is to define how the system imports Shane’s real organisation and contact data, detects duplicate organisations and collects new organisation information using the live scraper.

The system must:

- Import multiple organisations and contacts from Shane’s dataset.
- Preserve previous outreach information.
- Assign each imported organisation the correct contact status.
- Prevent duplicate banks, branches, clubs and contacts.
- Collect only publicly available organisation information.
- Handle missing, incomplete or changed scraped data.
- Prevent repeat imports and scraper runs from adding the same information twice.
- Clearly report failed records and processing errors.

This is separate from the **Add Organisation** form. Manual entry creates one organisation at a time, while data import and scraping process multiple records.

## 2. Functional Requirements

### 2.1 Real Data Import

#### FR-01: Restrict Data Import to Admin

The system must allow only an authenticated Admin to upload and import organisation data.

Staff users may view imported organisations but must not be able to start an import.

#### FR-02: Accept the Agreed Dataset Format

The system must accept the agreed Microsoft Excel `.xlsx` format.

The supplied dataset contains:

- 168 organisation records.
- 244 contact records.
- Organisation identifiers.
- Contact identifiers.
- Bank names.
- States.
- Contact names.
- Public email addresses.
- Previous outreach information.
- Reply information.
- Verification flags.

#### FR-03: Validate the Dataset Before Import

Before creating any records, the system must check that the file:

- Can be opened.
- Is an `.xlsx` file.
- Contains the expected worksheet or import data.
- Contains the required columns.
- Contains readable rows.

If the file structure is invalid, the import must stop before any records are created.

#### FR-04: Import Organisations and Contacts Separately

The system must create one organisation record for each unique organisation.

Where several contact rows share the same `organisation_id`, the system must:

- Create or match one organisation.
- Create the individual contacts.
- Connect each contact to that organisation.

Multiple contacts must not create multiple copies of the same organisation.

#### FR-05: Import the Organisation Type

The supplied dataset is mainly a community-bank dataset. Records from this confirmed dataset may therefore be imported as **Bank** records.

Future imports must provide or map an organisation type using one of the following values:

- Bank.
- Branch.
- Club.

An unsupported organisation type must be held for review.

#### FR-06: Preserve Source Information

Each imported record must store:

- The source organisation identifier.
- The source contact identifier, where available.
- The source filename.
- The import date and time.
- The Admin who started the import.
- Any supplied verification flag.
- Previous outreach evidence.
- Reply evidence.
- First and last observed dates.

#### FR-07: Handle Missing Optional Data

An otherwise identifiable organisation may still be imported when optional information is missing.

Missing optional values must remain empty. The system must not invent:

- Contact names.
- Email addresses.
- Phone numbers.
- Websites.
- Locations.
- Outreach history.

The value `(unspecified)` must be treated as a missing contact name rather than a real contact name.

#### FR-08: Import Contact Status Correctly

The system must convert the detailed dataset statuses into the project’s binary `contact_status` values:

- Not Yet Contacted.
- Contacted.

The system must not import **Partially Contacted** as a third contact status.

#### FR-09: Display an Import Summary

After the import finishes, the system must display:

- Total records processed.
- Organisations created.
- Contacts created.
- Existing records updated.
- Exact duplicates matched.
- Likely duplicates requiring review.
- Records that were not changed.
- Failed records.

### 2.2 Duplicate Detection

Duplicate detection is part of the import and scraper functionality. It is required whenever either process attempts to create or update an organisation.

#### FR-10: Normalise Data Before Comparison

Before comparing records, the system must:

- Ignore capitalisation.
- Remove leading and trailing spaces.
- Replace repeated spaces with one space.
- Ignore common punctuation differences.
- Treat `&` and `and` as equivalent when comparing names.
- Standardise Australian state abbreviations.
- Compare email addresses without case differences.
- Compare phone numbers without spaces or punctuation.

The original values must still be retained for display.

#### FR-11: Detect Exact Duplicates

The system must check whether the imported or scraped organisation exactly matches an existing organisation.

When an exact duplicate is found:

- A new organisation must not be created.
- New valid information may be added to the existing organisation.
- Existing contact and outreach history must be preserved.
- The result must be counted as an exact duplicate in the run summary.

#### FR-12: Detect Likely Duplicates

The system must identify records that are similar but not exact matches.

When a likely duplicate is found:

- The record must not be automatically merged.
- The possible matching organisation must be shown.
- The fields that caused the match must be shown.
- The record must be placed in a review list.
- An Admin must decide whether the records are the same or different.

#### FR-13: Detect Duplicate Contacts

A contact must be treated as an exact duplicate when the same normalised email address already exists against the same organisation.

The same email appearing against different organisations must be flagged for review because one shared mailbox may represent multiple branches.

### 2.3 Live Scraper

#### FR-14: Restrict Scraper Controls to Admin

Only an Admin must be able to start a scraper run or approve scraped changes.

Staff users may view accepted organisation information but must not control the scraper.

#### FR-15: Collect Organisation Information

Where publicly available, the scraper may collect:

- Organisation name.
- Organisation type.
- Parent bank for a branch.
- State.
- Region or suburb.
- Postcode.
- Public contact name.
- Public email.
- Public phone number.
- Public website.
- Public source URL.

#### FR-16: Store the Source

For every scraped record, the system must store:

- Source URL.
- Date and time first collected.
- Date and time last checked.
- Fields collected from that source.
- Whether the information requires verification.

#### FR-17: Check Scraped Results for Duplicates

Before creating a scraped organisation, the system must compare it with:

- Manually created organisations.
- Previously imported organisations.
- Organisations found during earlier scraper runs.

A scraped record must not bypass the standard duplicate rules.

#### FR-18: Handle New Scraped Organisations

If the scraper finds a genuinely new organisation with sufficient information, the system must:

- Create one organisation record.
- Record its source as Scraper.
- Assign the correct organisation type.
- Assign `contact_status = Not Yet Contacted`.
- Store its public source URL.

Finding public contact information does not mean that outreach has occurred.

#### FR-19: Handle Changed Scraped Information

If the scraper finds information that differs from an existing record, the system must:

- Compare the old and new values.
- Keep the current record while the change is reviewed.
- Show the source of the new information.
- Prevent a blank value from replacing an existing value.
- Prevent unverified scraped information from silently replacing manually verified information.

#### FR-20: Display a Scraper Summary

After a scraper run finishes, the system must display:

- Pages or results processed.
- New organisations created.
- Existing organisations updated.
- Existing organisations unchanged.
- Exact duplicates matched.
- Likely duplicates awaiting review.
- Incomplete results.
- Failed pages or results.

## 3. Acceptance Criteria

### Real Data Import

#### AC-01: Admin Imports a Valid Dataset

**Given** an authenticated Admin selects the supported dataset  
**When** the Admin starts the import  
**Then** the system must validate the file  
**And** process its valid organisation and contact records.

#### AC-02: Staff Cannot Start an Import

**Given** the signed-in user has the Staff role  
**When** the user views the system  
**Then** the data-import control must not be displayed.

#### AC-03: Invalid File Format

**Given** an Admin selects an unsupported file format  
**When** the Admin attempts to import it  
**Then** the import must not begin  
**And** a clear unsupported-file message must be displayed.

#### AC-04: Missing Required Column

**Given** an uploaded dataset is missing a required column  
**When** the file is validated  
**Then** no records must be imported  
**And** the missing column must be identified.

#### AC-05: Multiple Contacts for One Organisation

**Given** several contact rows contain the same `organisation_id`  
**When** the dataset is imported  
**Then** one organisation must be created or matched  
**And** each valid contact must be connected to that organisation.

#### AC-06: Missing Optional Contact Name

**Given** a contact name is blank or contains `(unspecified)`  
**When** the contact is imported  
**Then** the contact name must remain empty  
**And** the system must not store `(unspecified)` as a person’s name.

#### AC-07: Import Summary

**Given** an import finishes  
**When** the Admin views the result  
**Then** the system must show the created, updated, duplicate, review-required, unchanged and failed totals.

### Duplicate Detection

#### AC-08: Exact Bank Duplicate

**Given** an imported or scraped bank has the same normalised name and state as an existing bank  
**When** duplicate checking occurs  
**Then** a second bank must not be created  
**And** the result must be linked to the existing bank.

#### AC-09: Exact Branch Duplicate

**Given** a branch has the same parent bank, normalised branch name and location as an existing branch  
**When** duplicate checking occurs  
**Then** a second branch must not be created.

#### AC-10: Exact Club Duplicate

**Given** a club has the same normalised name, state and location as an existing club  
**When** duplicate checking occurs  
**Then** a second club must not be created.

#### AC-11: Likely Duplicate

**Given** an imported or scraped organisation is similar to an existing organisation but is not an exact match  
**When** duplicate checking occurs  
**Then** the new record must be held for review  
**And** the possible existing match must be displayed  
**And** the records must not be automatically merged.

#### AC-12: Similar Records Are Confirmed as Different

**Given** an Admin reviews a likely duplicate  
**And** confirms that the organisations are different  
**When** the decision is saved  
**Then** the new organisation may be created separately  
**And** the review decision must be recorded.

#### AC-13: Duplicate Contact

**Given** an imported contact has the same email as an existing contact for the same organisation  
**When** the contact is processed  
**Then** a second contact must not be created.

### Live Scraper

#### AC-14: Create a New Scraped Organisation

**Given** the scraper finds a valid organisation that does not exist in the database  
**When** the result is processed  
**Then** one new organisation must be created  
**And** its status must be Not Yet Contacted  
**And** its public source URL must be stored.

#### AC-15: Scraped Contact Information Does Not Change Contact Status

**Given** the scraper finds a public email or phone number  
**When** the organisation is created or updated  
**Then** its contact status must not change to Contacted.

#### AC-16: Scraper Finds an Existing Organisation

**Given** the scraper finds an organisation that already exists  
**When** duplicate checking occurs  
**Then** another organisation must not be created.

#### AC-17: Missing Optional Scraped Data

**Given** a scraped organisation is missing optional information  
**When** the result is processed  
**Then** the available information may be saved  
**And** the missing fields must remain empty  
**And** the system must not generate replacement values.

#### AC-18: Missing Required Scraped Data

**Given** a scraped result has no reliable organisation name, type or state  
**When** the result is processed  
**Then** an active organisation must not be created  
**And** the result must be reported as incomplete.

#### AC-19: Scraped Information Has Changed

**Given** the scraper finds information different from an existing value  
**When** the change is detected  
**Then** the old and new values must be recorded  
**And** a manually verified value must not be silently replaced.

#### AC-20: Scraper Page Fails

**Given** one public webpage cannot be processed  
**When** the scraper is running  
**Then** the failure must be recorded  
**And** processing must continue for the remaining valid pages.

#### AC-21: Public Information Only

**Given** a webpage requires a login or contains non-public information  
**When** the scraper encounters the page  
**Then** it must not collect that information.

#### AC-22: Scraper Summary

**Given** a scraper run finishes  
**When** the Admin views the result  
**Then** the system must show new, updated, unchanged, duplicate, incomplete and failed totals.

## 4. Workflow

### 4.1 Real Data Import Workflow

1. The Admin opens the Data Import page.
2. The Admin selects Shane’s dataset.
3. The system validates the file format and required columns.
4. The system reads each organisation and contact row.
5. The system groups contacts using `organisation_id`.
6. Each organisation is checked against the database.
7. New organisations are created.
8. Exact duplicates are linked to existing records.
9. Likely duplicates are placed in the review list.
10. Previous outreach information is converted to the correct contact status.
11. Valid contacts are connected to their organisation.
12. Failed rows are recorded without creating partial records.
13. The system displays the import summary.

### 4.2 Duplicate Review Workflow

1. An imported or scraped record is compared with existing records.
2. The system first checks the trusted source identifier.
3. The system then compares the organisation type, name and location.
4. If it is an exact duplicate, the existing record is used.
5. If it is a likely duplicate, the result is held for review.
6. The Admin views the possible matching records.
7. The Admin selects one of the following:

   - Use the existing organisation.
   - Create a separate organisation.
   - Reject the new record.

8. The system records the Admin’s decision.
9. The result is included in the import or scraper summary.

### 4.3 Live Scraper Workflow

1. The Admin opens the scraper page.
2. The Admin selects the organisation type and available location filters.
3. The Admin starts the scraper.
4. The scraper visits approved public sources.
5. Public organisation and contact information is collected.
6. The source URL and collection date are recorded.
7. Each result is validated.
8. Each result is checked for exact and likely duplicates.
9. New valid organisations are created as Not Yet Contacted.
10. Exact duplicates use the existing record.
11. Likely duplicates are held for Admin review.
12. Changed information is compared with existing information.
13. Failed or incomplete results are recorded.
14. The system displays the scraper-run summary.

## 5. Define How Already-Contacted Records Are Imported and Given a Status

The application uses only:

- `contact_status = Not Yet Contacted`
- `contact_status = Contacted`

The detailed dataset values must be mapped as follows:

| Dataset evidence | Imported status | Reason |
|---|---|---|
| `sent_and_human_reply_received` | Contacted | Outreach was successfully sent |
| `sent_no_human_reply_found` | Contacted | Outreach was sent even though no reply was received |
| `delivery_failure_recorded` only | Not Yet Contacted | Successful delivery did not occur |
| `human_inbound_only` only | Not Yet Contacted | No outgoing outreach has been confirmed |
| `copied_or_automated_only` only | Not Yet Contacted | This is not sufficient evidence of successful outreach |
| No outreach history | Not Yet Contacted | The organisation has not been contacted |
| Conflicting or unsupported value | Review Required | The system must not guess |

If one organisation has multiple contacts, one confirmed successful outgoing email is enough for the organisation to be **Contacted**.

The spreadsheet’s `overall_status` must not be copied directly because it includes **Partially Contacted** and bases some statuses on whether a reply was received.

Reply information must be preserved separately. A reply must not automatically change `opportunity.status` to Interested because the response may be positive, negative or neutral.

## 6. Define Exact and Likely-Duplicate Rules Across Banks, Branches and Clubs

### Exact Bank Duplicate

A bank is an exact duplicate when:

- The trusted source organisation ID or name matches; or
- The organisation type is Bank and the normalised bank name and state match.

### Exact Branch Duplicate

A branch is an exact duplicate when:

- The trusted source ID matches; or
- The parent bank, normalised branch name and postcode match; or
- The parent bank, normalised branch name, suburb and state match.

### Exact Club Duplicate

A club is an exact duplicate when:

- The trusted source ID matches; or
- The normalised club name, state and postcode match; or
- The normalised club name, suburb and state match.

### Likely Duplicate

A record is a likely duplicate when:

- Its name is at least 90% similar to an organisation of the same type in the same state.
- Its name is at least 80% similar and it has the same suburb or postcode.
- It has the same public email, phone number or website as a differently named organisation.
- Its name and location are similar but its organisation type is different.
- A branch appears similar to a bank but no parent-bank relationship is available.

Likely duplicates must be reviewed by an Admin and must never be merged automatically.

## 7. Define How the Scraper Handles Missing, Incomplete or Changed Data

### Missing Optional Data

If optional information such as contact name, email, phone number or website is unavailable:

- The field must remain empty.
- The scraper must not guess the value.
- The organisation may still be created when it can be identified safely.
- The record may be marked as needing verification.

### Missing Required Data

If the organisation name, type or state cannot be identified:

- An active organisation must not be created.
- The result must be placed in the incomplete or review-required list.
- The source URL and missing field must be recorded.

### Changed Data

If the scraper finds a different value:

- The current value and new value must be compared.
- A blank value must not replace an existing value.
- A manually verified value must not be replaced automatically.
- The new value and its source must be shown to an Admin.
- The previous value must remain available in the change history.

### Information Removed From a Website

If information previously collected is no longer displayed:

- The system must not automatically delete the stored value.
- The value must be marked as no longer found or requiring verification.
- The previous source history must be preserved.

## 8. Define What Happens on Repeat Runs, So Nothing Is Added Twice

Every import and scraper run must check existing records before creating new records.

On a repeat run, the system must:

1. Check the trusted source identifier.
2. Apply the exact duplicate rules.
3. Apply the likely-duplicate rules.
4. Create only genuinely new records.
5. Update permitted changed information.
6. Preserve manually verified information.
7. Update the last-imported or last-checked date.
8. Record the outcome of the run.

If the same unchanged file is imported again:

- No duplicate organisation must be created.
- No duplicate contact must be created.
- Existing records must remain unchanged.
- The summary must show that the records already existed.

If the same website is scraped again without any changes:

- No new organisation must be created.
- The existing record must remain unchanged.
- Only the last-checked date may be updated.

## 9. Define How Errors and Failed Imports Are Reported

The system must report errors using clear business language.

Each failed result must include:

- Spreadsheet row number or source URL.
- Organisation name, where available.
- A clear explanation of the problem.
- The affected field.
- The action required from the Admin.

Possible error categories include:

- Unsupported file type.
- Missing required column.
- Invalid state.
- Missing organisation name.
- Unsupported organisation type.
- Invalid email format.
- Likely duplicate requiring review.
- Unable to access the public source.
- Unable to process the webpage.
- Database or system error.

One failed row must not stop other valid rows from being imported.

A failed row must not create a partial organisation or contact.

The final run status must be:

- **Successful:** All records were processed.
- **Partially Successful:** Some records were processed, but others require review or failed.
- **Failed:** The file or scraper run could not be processed.

## 10. Confirm Only Public Data Is Collected

The live scraper may collect only information displayed publicly for organisation or business-contact purposes.

Permitted information includes:

- Organisation name.
- Organisation type.
- Public address or location.
- Public email.
- Public business phone number.
- Public website.
- Publicly listed contact person and role.
- Public parent-bank relationship.
- Publicly identified supported clubs.

The scraper must not:

- Access pages requiring a login.
- Attempt to bypass website access controls.
- Collect private or sensitive information.
- Collect personal contact details that are not publicly provided for organisation contact.
- Guess missing personal details.
- Collect information from private social-media profiles.

Shane’s supplied historical dataset may be imported because it is client-provided business data. However, new information collected by the live scraper must come only from publicly available sources.