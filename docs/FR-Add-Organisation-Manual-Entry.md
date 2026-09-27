# Functional Requirements: Add Organisation (Manual Entry)

## 1. Purpose

The Add Organisation function allows an authorised user to manually create a bank, branch or club record when the organisation is not already available in the system.

## 2. Functional Requirements

### FR-01: Access the Add Organisation Form

The system must provide an **Add Organisation** form to authorised users.

Users without organisation-management permission must not be able to access or submit the form.

### FR-02: Select the Organisation Type

The user must select one of the following organisation types:

- Bank
- Branch
- Club

If **Branch** is selected, the user must also select the associated parent bank.

### FR-03: Enter Required Information

The following fields must be required:

- Organisation name
- Organisation type
- State or territory
- Region or suburb
- Postcode

The system must not save the organisation until all required fields are valid.

### FR-04: Enter Optional Information

The user may add:

- Public contact email
- Contact person’s name
- Contact person’s role
- Phone number
- Street address
- Website
- Notes
- Other relevant public information

An organisation may be created without contact information. However, a valid recipient email must be added before an outreach email can be sent.

### FR-05: Validate Required Fields

The system must:

- Treat empty fields and fields containing only spaces as incomplete.
- Remove unnecessary leading and trailing spaces.
- Display an inline error beside each missing required field.
- Preserve valid information already entered when validation fails.

### FR-06: Validate Organisation Type

The system must accept only:

- Bank
- Branch
- Club

Unsupported organisation types must not be saved.

### FR-07: Validate Location Information

The system must:

- Accept only supported Australian states and territories.
- Reject invalid state or region values.
- Require a four-digit postcode.
- Check that the postcode is appropriate for the selected state where validation data is available.

Supported state and territory values are:

- ACT
- NSW
- NT
- QLD
- SA
- TAS
- VIC
- WA

### FR-08: Validate Contact Information

When contact information is provided, the system must:

- Validate the email address format.
- Validate the Australian phone-number format.
- Validate the website URL format.
- Prevent invalid contact information from being saved.

### FR-09: Check for Exact Duplicates

Before saving, the system must search for an existing organisation with the same normalised:

- Organisation name
- Organisation type
- State or region
- Suburb or postcode

The comparison must ignore:

- Capitalisation differences
- Leading or trailing spaces
- Repeated spaces
- Common punctuation differences

If an exact duplicate is found:

- The new record must not be created.
- The existing matching organisation must be displayed.
- The user must be directed to review or update the existing record.

### FR-10: Check for Likely Duplicates

The system must display a possible-duplicate warning when an existing organisation has:

- A very similar name.
- The same public email.
- The same phone number.
- The same website.
- A similar name and location.

The warning must display the possible matching record so the user can review it.

An authorised user may continue only after confirming that the organisations are different. The system should record the user, date, time and reason for overriding the warning.

### FR-11: Apply the Default Status

When a new organisation is created, the system must set:

- `contact_status = Not Yet Contacted`
- `opportunity.status = empty/no response outcome`
- `record_source = Manual Entry`

Adding an email address or contact person must not change the organisation to **Contacted**.

### FR-12: Record Creation Information

The system must record:

- The organisation identifier
- The user who created the organisation
- The creation date and time
- The initial contact status
- The record source as **Manual Entry**

### FR-13: Save the Organisation

When all required information is valid and no exact duplicate exists, the system must:

- Create one organisation record.
- Assign a unique organisation identifier.
- Place the record in the correct Bank, Branch or Club category.
- Display the new organisation’s details.
- Display its status as **Not Yet Contacted**.

### FR-14: Provide Success Feedback

After a successful save, the system must:

- Display a confirmation message.
- Include the organisation’s name in the message.
- Take the user to the organisation’s detail page or provide a link to it.

Example:

> “Community Bank Ballarat has been added successfully.”

### FR-15: Provide Validation Feedback

If the submitted information is invalid, the system must:

- Prevent the organisation from being created.
- Display an inline error beside each affected field.
- Explain how the error can be corrected.
- Preserve the valid information already entered.

### FR-16: Handle a System Failure

If a database, network or server failure occurs, the system must:

- Prevent partial or incomplete records from being created.
- Display a general failure message.
- Preserve the entered information where possible.
- Allow the user to try again.
- Avoid displaying technical system or database details.

### FR-17: Prevent Duplicate Submissions

If the user selects **Save** more than once while the request is processing, the system must create only one organisation record.

### FR-18: Protect User-Entered Information

The system must safely process user-entered information.

HTML, JavaScript or other executable content entered into the form must not run when the organisation details are displayed.

## 3. Permission Requirements

The Add Organisation function must be restricted to authenticated users with organisation-management permission.

Expected authorised users include:

- Shane
- Administrator
- Authorised data-management users

The team must confirm the final system role names before sign-off.

## 4. Key Edge Cases

### Organisation With No Contact Information

The organisation may be created as **Not Yet Contacted**, but email drafting and sending must remain unavailable until a valid recipient email is added.

### Concurrent Duplicate Entry

If two users attempt to create the same organisation simultaneously, the system must check for duplicates again during saving. Only one record must be created.

### Similar Names for Different Organisations

If two legitimate organisations have similar names, the system must show a warning rather than automatically blocking the new record. An authorised user must confirm that they are different before continuing.

## 5. Plain-Language Acceptance Criteria

### AC-1: Successfully Add an Organisation

**Given** an authorised user has entered valid required information  
**And** no exact duplicate exists  
**When** the user selects **Save**  
**Then** one organisation record must be created  
**And** its contact status must be **Not Yet Contacted**  
**And** a success message must be displayed.

### AC-2: Missing Required Information

**Given** a required field is empty  
**When** the user selects **Save**  
**Then** the organisation must not be created  
**And** an inline error must identify the missing information.

### AC-3: Exact Duplicate Found

**Given** the same organisation already exists  
**When** the user attempts to save it again  
**Then** the new record must not be created  
**And** the existing organisation must be shown.

### AC-4: Likely Duplicate Found

**Given** the entered information is similar to an existing organisation  
**When** the user attempts to save it  
**Then** the system must display a duplicate warning  
**And** require the user to review the possible match.

### AC-5: Organisation Has No Contact Details

**Given** all required organisation information is valid  
**And** no contact email is available  
**When** the user saves the organisation  
**Then** the organisation may be created as **Not Yet Contacted**  
**And** email sending must remain unavailable until a valid email is added.

### AC-6: Unauthorised User

**Given** a user does not have organisation-management permission  
**When** the user attempts to access or submit the form  
**Then** access must be denied  
**And** no organisation must be created.

## 7. Final Expected Behaviour

An authorised user can manually create a valid bank, branch or club. The system validates the information, checks for duplicates and prevents incomplete, invalid or unauthorised submissions.

A successfully created organisation appears in the correct category with `contact_status = Not Yet Contacted`, no response outcome and **Manual Entry** recorded as its source. Adding contact details does not mean the organisation has been contacted. The status changes to **Contacted** only after successful outreach or authorised external contact is recorded.