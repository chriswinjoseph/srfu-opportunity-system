# Acceptance Criteria: Add Organisation 

## 1. Purpose

The purpose of the Add Organisation function is to allow authorised users to manually add banks, branches and clubs that are not already recorded in the system.

The function must ensure that:

- Complete and valid organisation information is captured.
- Duplicate organisation records are prevented.
- New organisations receive the correct default contact status.
- Only authorised users can create organisation records.
- Successful and unsuccessful save attempts provide clear feedback.
- Record creation and duplicate overrides are auditable.

## 2. Required and Optional Fields

### Required Fields

The user must provide:

- Organisation name
- Organisation type: Bank, Branch or Club
- State or territory
- Suburb
- Postcode
- Public contact email

If the organisation type is **Branch**, the associated parent bank must also be selected.

### Optional Fields

The user may provide:

- Contact person’s name
- Contact person’s role
- Phone number
- Street address
- Website URL
- Notes
- Region
- Parent organisation, where relevant

## 3. Duplicate-Detection Rules

The system must perform exact-match and possible-match duplicate checks before creating an organisation.

### Exact Match

An exact duplicate exists when an existing record has the same normalised:

- Organisation name
- Organisation type
- Suburb or postcode

Capitalisation, leading or trailing spaces and minor formatting differences must be ignored.

If an exact duplicate is found:

- The new record must not be saved.
- The existing organisation must be shown to the user.
- The user must be directed to review or update the existing record.

### Possible or Fuzzy Match

A possible duplicate exists when an organisation has:

- A very similar name in the same location.
- The same email address.
- The same website address.
- The same phone number.
- A similar name containing a minor spelling or formatting difference.

If a possible duplicate is found:

- The system must display a warning.
- The possible matching records must be shown.
- The user must be able to review the existing record.
- An authorised user may continue only after confirming that the organisation is genuinely different.
- The duplicate warning and override must be recorded in the audit log.

## 4. Default Status

Every organisation created manually must receive:

- `contact_status = Not Yet Contacted`
- No response outcome in `opportunity.status`

Creating an organisation must not automatically mark it as:

- Contacted
- Interested
- Not Interested
- Do Not Contact

The organisation becomes **Contacted** only after outreach is successfully sent or authorised external outreach is recorded.

## 5. Validation Rules

The system must apply the following validation before saving:

- Required fields must not be empty.
- Organisation name must not contain only spaces.
- Organisation type must be Bank, Branch or Club.
- Email must follow a valid email format.
- Postcode must contain four digits.
- State or territory must be one of: ACT, NSW, NT, QLD, SA, TAS, VIC or WA.
- Website URL, when provided, must follow a valid URL format.
- Phone number, when provided, must use an accepted Australian phone-number format.
- A branch must be connected to an existing parent bank.
- Input values must be trimmed to remove unnecessary spaces.
- Unsupported values must not be saved.
- User-entered text must be handled safely and must not execute HTML or scripts.

Validation messages must identify the relevant field and clearly explain how the user can correct it.

## 6. Permission Rules

Only an authenticated user with permission to manage organisation records may manually add an organisation.

The expected authorised roles are:

- Administrator
- Shane or another authorised project user
- An authorised data-management user

A user without permission:

- Must not see or use the **Add Organisation** function.
- Must not be able to create an organisation through a direct URL or API request.
- Must receive an appropriate access-denied response if access is attempted.

The PM and Shane must confirm the final role names used by the system.

## 7. Save and Error Feedback

### Successful Save

After an organisation is successfully saved:

- One organisation record must be created.
- A confirmation message must be displayed.
- The confirmation message should include the organisation’s name.
- The user should be taken to the new organisation’s detail page.
- The organisation must appear in the correct dashboard or organisation list.
- Its contact status must display as **Not Yet Contacted**.

### Failed Save

If the organisation cannot be saved:

- The system must display a clear error message.
- Invalid fields must be identified.
- Correct values already entered must remain in the form.
- No incomplete organisation record must be created.
- The user must be able to correct the problem and submit the form again.
- Technical database or server details must not be exposed to the user.

If the user submits the form more than once while it is saving, the system must prevent multiple records from being created.

## 8. Audit-Logging Requirements

For every successfully created organisation, the system must record:

- Organisation identifier
- Organisation name
- Organisation type
- User who created the record
- Creation date and time
- Initial `contact_status`
- Source as **Manual Entry**

When a possible duplicate warning is overridden, the system must also record:

- The possible duplicate that was identified
- The user who approved the override
- The date and time of the override
- The reason provided for continuing

The audit history must not be editable by ordinary users.

## 9. Edge Cases

| Edge case | Expected system behaviour |
|---|---|
| A required field is empty | Prevent saving and identify the missing field |
| Organisation name contains only spaces | Treat the field as empty and prevent saving |
| Email format is invalid | Prevent saving and display an email validation message |
| State value is unsupported | Prevent saving and require a supported value |
| Postcode is not four digits | Prevent saving and display a postcode validation message |
| An exact duplicate exists | Block creation and display the existing organisation |
| A possible duplicate exists | Display a warning and require review before continuing |
| The email is used by another organisation | Display the matching organisation as a possible duplicate |
| A branch has no parent bank | Prevent saving until a parent bank is selected |
| An optional field is empty | Allow the organisation to be saved |
| The user selects Save more than once | Create only one organisation |
| The user loses permission before saving | Reject the request and do not create the organisation |
| A database or network error occurs | Do not create a partial record and display a safe error message |
| Another user creates the same organisation concurrently | Allow only one record and report the duplicate to the other user |
| Entered text contains HTML or script content | Store or display the content safely without executing it |
| The organisation has previous contact history | Direct the user to review the existing record instead of creating a new one |

## 10. Acceptance Criteria

### AC-1: Display the Add Organisation Form

**Given** the user is authenticated and has organisation-management permission  
**When** the user opens **Add Organisation**  
**Then** the system must display the required and optional organisation fields.

### AC-2: Prevent Unauthorised Access

**Given** the user does not have permission to manage organisations  
**When** the user attempts to access or submit the Add Organisation form  
**Then** the system must deny the request  
**And** no organisation must be created.

### AC-3: Validate Required Fields

**Given** one or more required fields are empty  
**When** the user selects **Save**  
**Then** the system must not create the organisation  
**And** must identify every required field that needs to be completed.

### AC-4: Validate Field Formats

**Given** an email, postcode, phone number, website or state value is provided incorrectly  
**When** the user selects **Save**  
**Then** the system must prevent saving  
**And** display a clear validation message beside the affected field.

### AC-5: Require a Parent Bank for a Branch

**Given** the selected organisation type is **Branch**  
**When** no parent bank has been selected  
**Then** the system must prevent saving  
**And** request that the user select the associated bank.

### AC-6: Block an Exact Duplicate

**Given** an organisation with the same normalised name, type and location already exists  
**When** the user attempts to save the new organisation  
**Then** the system must block the creation  
**And** display a link or reference to the existing record.

### AC-7: Warn About a Possible Duplicate

**Given** the entered details are similar to an existing organisation  
**When** the duplicate check is performed  
**Then** the system must display the possible matching record  
**And** require the authorised user to review it before continuing.

### AC-8: Allow an Authorised Duplicate Override

**Given** a possible duplicate warning has been displayed  
**And** the user confirms that the records represent different organisations  
**When** the user provides a reason and continues  
**Then** the system may create the organisation  
**And** must record the override in the audit log.

An exact duplicate must not be overridden through this process.

### AC-9: Apply the Default Contact Status

**Given** a valid new organisation is being created  
**When** the organisation is saved  
**Then** its `contact_status` must be **Not Yet Contacted**  
**And** `opportunity.status` must not contain a response outcome.

### AC-10: Save a Valid Organisation

**Given** all required fields are valid  
**And** no exact duplicate exists  
**When** the authorised user selects **Save**  
**Then** the system must create one organisation record  
**And** display a success message  
**And** show the new organisation’s detail page.

### AC-11: Preserve Form Data After a Validation Error

**Given** the submitted form contains an error  
**When** validation fails  
**Then** the system must preserve the valid information already entered  
**And** allow the user to correct and resubmit the form.

### AC-12: Handle a Save Failure

**Given** a database, server or network error prevents saving  
**When** the user submits the form  
**Then** the system must not create a partial record  
**And** must display a safe error message  
**And** must not expose technical system details.

### AC-13: Prevent Duplicate Submissions

**Given** the user submits the form more than once while the first request is processing  
**When** the system receives the repeated request  
**Then** only one organisation record must be created.

### AC-14: Record Creation in the Audit Log

**Given** an organisation is successfully created  
**When** the save process finishes  
**Then** the system must record who created it, when it was created, its initial status and that its source was manual entry.

### AC-15: Display the New Organisation Correctly

**Given** an organisation has been successfully created  
**When** the user opens the organisation list or dashboard  
**Then** the organisation must appear in the correct Bank, Branch or Club category  
**And** must appear under **Not Yet Contacted**.

## 11. Final Expected Behaviour

An authorised user can manually create a valid bank, branch or club record through the Add Organisation form. The system validates all required information, identifies exact and possible duplicates, prevents unauthorised or incomplete submissions and provides clear feedback about the result.

After a successful save, only one organisation record is created. The organisation appears in the correct list with `contact_status = Not Yet Contacted` and no response outcome in `opportunity.status`. The system also records who created the organisation and when it was created.

Creating an organisation does not generate an email, send outreach or mark the organisation as **Contacted**.