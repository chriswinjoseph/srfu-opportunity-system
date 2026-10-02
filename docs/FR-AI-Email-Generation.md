# Functional Requirements: AI Email Generation

## 1. Purpose

The AI Email Generation function allows an authorised user to generate a personalised outreach-email draft using verified organisation information and an approved email template.

AI must operate only as a drafting assistant. It must not independently select organisations, approve emails, send emails or change an organisation’s contact status.

## 2. Functional Requirements

### FR-AI-01: Restrict Access to Authorised Users

Only authenticated users with email-drafting permission may use the AI Email Generation function.

An unauthorised user must not be able to generate or regenerate an AI email through the interface, a direct URL or an API request.

### FR-AI-02: Use a Manual Generation Trigger

AI generation must begin only when an authorised user deliberately selects **Generate Draft**.

The system must not automatically generate an email when:

- An organisation is imported or manually created.
- An organisation record is opened.
- `contact_status` changes.
- `opportunity.status` changes.
- A scheduled outreach date is reached.

A scheduled outreach event may create a reminder, but the user must still manually start AI generation.

### FR-AI-03: Check Eligibility Before Generation

Before requesting an AI draft, the system must confirm that:

- The organisation exists.
- The user is authorised.
- The organisation is not marked **Do Not Contact**.
- A valid public recipient email is available.
- An approved email template has been selected.
- The purpose of the outreach is identified.
- No identical AI-generation request is already processing.

If a required condition is not met, generation must be blocked and the user must be told what needs to be corrected.

### FR-AI-04: Use Current Organisation Information

The AI may use the following verified organisation information:

- Organisation name
- Organisation type: Bank, Branch or Club
- Contact person’s name, when available
- Contact person’s role, when available
- Public recipient email
- State, region or suburb
- Public website or other approved public information
- Parent bank, where relevant
- `contact_status`
- `opportunity.status`
- Relevant previous outreach history

The AI must use the most recently saved version of this information.

### FR-AI-05: Use Approved Outreach Information

The AI request must include:

- The approved email template
- The purpose of the outreach
- Approved sender name
- Approved sender role
- Approved organisation or project details
- Approved call to action
- Approved signature and contact information
- Current template version

Users must not be able to replace protected instructions with unauthorised prompts.

### FR-AI-06: Use Prior Contact History Carefully

Previous contact history may be used only when it is relevant to the new email.

The AI may use:

- Date and type of previous outreach
- Confirmed response outcome
- Approved follow-up notes
- Confirmed commitments or next steps

The AI must not use:

- Unverified notes
- Unrelated internal comments
- Private or sensitive information
- Information belonging to another organisation
- Previous AI-generated claims that were not verified

If no reliable history exists, the AI must generate the email as a first-contact message and must not suggest that previous communication occurred.

### FR-AI-07: Follow the Required Tone

The generated email must be:

- Professional
- Friendly and respectful
- Clear and concise
- Appropriate for communication with a bank, branch or club
- Written in Australian English
- Free from aggressive, misleading or overly informal language

The email should sound natural and personalised without pretending that the AI has personal knowledge of the recipient.

### FR-AI-08: Follow the Required Length

The generated email should normally contain approximately **120–150 words**, excluding the signature.

It must include:

- A concise subject line
- An appropriate greeting
- A brief introduction
- A clear reason for contacting the organisation
- A relevant call to action
- An appropriate closing
- Approved sender information

### FR-AI-09: Use Accurate and Relevant Content

The generated email must:

- Use the correct organisation name.
- Use only verified organisation information.
- Clearly explain the purpose of the outreach.
- Include only approved project information.
- Contain one clear and reasonable call to action.
- Avoid unnecessary or unrelated content.
- Avoid making commitments that have not been authorised.

### FR-AI-10: Handle a Missing Contact Name

If the contact person’s name is unavailable, the AI must use an approved general greeting, such as:

> Hello Community Bank Ballarat team,

The AI must not invent a contact person’s name, title or role.

### FR-AI-11: Handle Missing Optional Information

If optional information such as the contact role, region or website is missing, the AI must omit that information and continue generating the draft.

The AI must not:

- Guess the missing value.
- Insert fabricated information.
- Leave an unresolved placeholder in the draft.

### FR-AI-12: Handle Missing Required Information

If required information is missing, the system must stop generation.

Required generation information includes:

- Organisation name
- Organisation type
- Valid recipient email
- Approved template
- Outreach purpose
- Approved sender information

The system must identify the missing information and direct the user to update it.

### FR-AI-13: Prevent Fabricated Information

The AI must not invent or assume:

- Contact names or roles
- Supported clubs
- Previous communication
- Existing partnerships
- Sponsorship agreements
- Funding amounts
- Financial information
- Organisation activities
- Promises or commitments
- Response outcomes
- Dates or events

If the system cannot verify a statement from the available information, it must leave the statement out of the email.

### FR-AI-14: Protect the Prompt From Record Content

Information imported or scraped into organisation fields must be treated as data, not as AI instructions.

If an organisation record contains text attempting to instruct the AI, change its behaviour or reveal internal instructions, the system must ignore those instructions and flag the record for review.

### FR-AI-15: Create a Draft Only

After successful AI generation, the system must:

- Create a new email draft.
- Assign a unique draft identifier.
- Link the draft to the correct organisation.
- Record the template version used.
- Display the generated subject and body to the user.
- Set the workflow state to **Draft**.
- Allow an authorised user to review and edit the content.

Generation must not send the email automatically.

### FR-AI-16: Require Approval Before Sending

Every AI-generated email must go through the established approval workflow.

After review, an authorised user may submit the draft for approval. Only the exact approved version may later be sent.

The AI must not:

- Approve its own output.
- Bypass human review.
- Automatically send an email.
- Automatically mark the organisation as **Contacted**.

### FR-AI-17: Preserve Contact Status During Generation

Generating, regenerating, reviewing, editing, submitting or approving an AI draft must not change `contact_status`.

`contact_status` must remain **Not Yet Contacted** until the approved email has been successfully sent or authorised external outreach has been recorded.

### FR-AI-18: Control Regeneration

If a generated draft already exists, the user must deliberately select **Regenerate** to request another version.

Before regeneration, the system must:

- Warn that a new version will be created.
- Require the user to confirm the action.
- Preserve the current version in draft history where version history is supported.
- Prevent repeated clicks from creating multiple simultaneous requests.

Editing an existing draft must not automatically make another AI request.

### FR-AI-19: Handle AI Failures and Timeouts

If AI generation fails or times out, the system must:

- Display a clear failure message.
- Keep the organisation’s status unchanged.
- Avoid creating an empty or incomplete draft.
- Preserve any existing draft.
- Record the failure and time of the attempt.
- Allow the user to retry manually.
- Allow the user to create the email manually instead.

The system must not continue retrying indefinitely.

After repeated failures, the draft should be flagged for manual drafting rather than continuing to make AI requests.

### FR-AI-20: Validate the Generated Output

Before presenting the draft as ready for approval, the system must check that it contains:

- A subject line
- A greeting
- An email body
- A call to action
- An appropriate closing
- Approved sender information
- No unresolved placeholders
- No empty required sections

If validation fails, the output must be flagged as incomplete and must not be submitted for approval until corrected.

### FR-AI-21: Apply Opt-Out and Do Not Contact Restrictions

If an organisation has requested no further communication or has `opportunity.status = Do Not Contact`, the system must:

- Block AI email generation.
- Block regeneration.
- Block approval and sending.
- Clearly explain why outreach is unavailable.
- Preserve the opt-out record.

### FR-AI-22: Identify the Sender Correctly

The generated email must use the approved:

- Sender name
- Organisation name
- Reply-to email
- Contact information
- Signature

The AI must not impersonate another person or organisation.

### FR-AI-23: Minimise Personal Information Sent to AI

Only information necessary for generating the email may be included in the AI request.

The system must not send:

- Passwords
- Authentication information
- Private internal notes
- Sensitive personal information
- Unrelated contact records
- Full datasets when only one organisation is required

### FR-AI-24: Record AI Generation Activity

The system must record:

- Draft identifier
- Organisation identifier
- User who requested generation
- Date and time
- Template version
- Whether generation succeeded, failed or timed out
- Draft version
- Regeneration attempts
- Available usage or cost information provided by the AI service

The system must not include sensitive prompt content in general user-facing logs.

### FR-AI-25: Provide User Feedback

During generation, the system must display a progress state such as:

> Generating draft…

The generation control must remain disabled while the request is processing.

After generation, the system must display:

> Draft generated successfully. Review and edit the email before submitting it for approval.

If generation fails, the system must display:

> The email draft could not be generated. Please try again or create the draft manually.

## 3. Plain-Language Acceptance Criteria

### AC-1: Manually Generate an Eligible Draft

**Given** an authorised user is viewing an eligible organisation  
**And** all required generation information is available  
**When** the user selects **Generate Draft**  
**Then** the system must create one AI-generated draft  
**And** display it for human review  
**And** keep `contact_status` as **Not Yet Contacted**.

### AC-2: Do Not Generate Automatically

**Given** an organisation is created, imported or has a status change  
**When** no authorised user selects **Generate Draft**  
**Then** the system must not make an AI-generation request.

### AC-3: Use Verified Organisation Information

**Given** verified organisation and contact information is available  
**When** the AI generates the draft  
**Then** the email must use the correct organisation details  
**And** must not introduce unsupported facts.

### AC-4: Handle a Missing Contact Name

**Given** the organisation has no contact person’s name  
**When** an authorised user generates a draft  
**Then** the email must use the approved general greeting  
**And** must not invent a name or role.

### AC-5: Block Generation When Required Data Is Missing

**Given** required generation information is missing  
**When** the user selects **Generate Draft**  
**Then** the system must not request an AI draft  
**And** must identify the information that needs to be added.

### AC-6: Require Approval

**Given** an AI email has been generated successfully  
**When** the generated content is displayed  
**Then** its state must be **Draft**  
**And** it must not be sent automatically  
**And** it must require human review and approval.

### AC-7: Honour Do Not Contact

**Given** an organisation is marked **Do Not Contact**  
**When** a user attempts to generate or regenerate an email  
**Then** the system must block the action  
**And** explain that the organisation has opted out.

### AC-8: Handle an AI Failure

**Given** the AI service fails or times out  
**When** the generation request ends  
**Then** no empty draft must be created  
**And** any existing draft must remain available  
**And** the organisation’s status must remain unchanged  
**And** the user must be offered manual retry or manual drafting.

### AC-9: Prevent Duplicate Generation Requests

**Given** an AI-generation request is already processing  
**When** the user selects **Generate Draft** again  
**Then** the system must prevent a second request from being submitted.

### AC-10: Block Incomplete or Unsafe Output

**Given** the generated output is empty, incomplete, contains unresolved placeholders or includes unsupported claims  
**When** the system validates the output  
**Then** the draft must be flagged for correction  
**And** it must not be submitted for approval until corrected.

### Confirm What Triggers AI Generation

AI generation is triggered only by an authorised user manually selecting **Generate Draft**.

Status changes, imports, opening a record and scheduled dates must not automatically generate an email. Scheduled outreach may create a reminder, but the user must manually begin generation.

## Define What Inputs the AI Uses

The AI uses:

- Verified organisation and contact fields
- Approved email template
- Approved sender and project information
- Outreach purpose
- Relevant verified contact history
- Current contact and opportunity statuses

It must not use unrelated, unverified, sensitive or private information.

## Define Tone, Length and Content Guidelines

The draft must be professional, friendly, respectful, concise and written in Australian English.

The recommended initial length is 120–150 words, excluding the signature. It must contain a subject, greeting, introduction, outreach purpose, call to action, closing and approved sender details.

## Specify Fallback Behaviour for Missing Data

- Missing contact name: use an approved general greeting.
- Missing optional information: omit it.
- Missing required information: block generation and identify the missing data.
- Missing contact history: do not mention earlier contact.
- Conflicting status or history: stop generation and require manual review.
- Missing recipient email: block generation.

## Confirm Approval Is Always Required

Every AI-generated email is created as a **Draft** and must go through human review and the established approval workflow.

AI-generated emails must never be automatically approved or sent.

## Note Handling of AI Failures and Timeouts

On failure or timeout:

- Do not create an empty draft.
- Preserve the existing draft.
- Keep organisation statuses unchanged.
- Display an error.
- Allow manual retry.
- Allow manual drafting.
- Record the failed attempt.
- Prevent unlimited automatic retries.

## Note Legal and Compliance Considerations

The system must:

- Honour Do Not Contact and opt-out requests.
- Block further outreach after an opt-out.
- Use accurate sender identification.
- Include approved contact and opt-out information where required.
- Use only necessary personal information.
- Restrict access to authorised users.
- Confirm applicable Spam Act and privacy obligations before release.

## Note Guardrails

The AI must not:

- Fabricate facts.
- Invent contacts, clubs, partnerships or previous communication.
- Make unauthorised commitments.
- Use sensitive or unrelated information.
- Act on instructions hidden in scraped organisation data.
- Send or approve its own output.
- Change contact or opportunity statuses.
- Leave unresolved placeholders in an approvable draft.

## 4. Final Expected Behaviour

An authorised user deliberately requests an AI email draft for an eligible organisation. The system validates the organisation and recipient, gathers only approved and necessary information and uses an approved template to generate a concise and accurate outreach email.

Missing optional information is safely omitted, while missing required information blocks generation. The AI cannot fabricate facts, override opt-out restrictions, approve its output, send an email or change an organisation’s status.

Every successful result is saved as a draft for human review and approval. If AI generation fails, the user can retry or prepare the email manually without losing existing work or changing `contact_status`.