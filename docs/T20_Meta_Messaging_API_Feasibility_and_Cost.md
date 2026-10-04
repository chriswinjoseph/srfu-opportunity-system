T20 – [Stretch-prep] Spike: Instagram/Facebook Messaging API Feasibility & Cost
Purpose
This spike looks at whether Safe Roads For Us (SRFU) could use Facebook Messenger and Instagram messaging through Meta's APIs in the future. The main focus is technical feasibility, account requirements, limitations, cost, and whether it would suit the current SRFU outreach workflow.
Short Answer
The integration is technically feasible, but it would not be a direct replacement for the current email outreach process.
Facebook Messenger and Instagram messaging are better suited to conversations where the user has already contacted the organisation or has agreed to receive messages. Because SRFU mainly performs proactive outreach to banks, branches, and clubs, these APIs would be more useful for inbound enquiries and follow-up conversations.
Recommendation: Keep Facebook/Instagram messaging as a future enhancement rather than a current priority.
Facebook Messenger API
What it can do
- Send and receive messages through a Facebook Page.
- Send text, media, and supported message templates.
- Use webhooks to detect incoming messages.
- Potentially connect Messenger conversations to an organisation or outreach record in SRFU.
What SRFU would need
- A Facebook Page.
- A Meta developer app.
- A Page access token.
- The required Messenger permissions, including pages_messaging.
- App Review / Advanced Access for production use where required.
Main limitation
Messenger is not intended to work as unrestricted cold outreach.
Meta's Messenger platform generally expects the user to have already messaged the Page within the allowed messaging window, or to have otherwise agreed to receive messages.
Because of this, SRFU would not be able to simply message every organisation in the database through Messenger.
Instagram Messaging API
What it can do
- Send and receive messages for an Instagram Professional account.
- Handle conversations with customers, followers, and potential contacts.
- Use access tokens and messaging permissions to connect the Instagram inbox to an external system.
- Potentially store Instagram conversations in SRFU's outreach history.
What SRFU would need
- An Instagram Professional account, such as Business or Creator.
- A Meta developer app.
- The required Instagram messaging permissions.
- An authorised access token.
- A linked Facebook Page where required by the Meta setup.
Main limitation
Instagram messaging is mainly designed around conversations started by the Instagram user.
This makes it useful for inbound enquiries and follow-up, but not suitable as a general first-contact channel for every organisation stored in SRFU.
Cost and Effort
I did not find a separate per-message API fee in the Meta documentation reviewed for Messenger or Instagram.
The main costs would likely come from:
- Development time.
- Hosting and webhook setup.
- App Review and configuration.
- Ongoing maintenance.
- Optional third-party messaging platforms.
Meta's pricing, policies, and access requirements can change, so these should be checked again before any production implementation.
Feasibility for SRFU
Technical feasibility: Yes.
The current Django application could connect to Meta's APIs, receive webhook events, and store message activity against organisations or opportunities.
Operational fit: Partial.
The APIs are suitable for inbound communication and follow-up, but they are not a strong fit for SRFU's main proactive outreach use case.
Implementation complexity: Moderate.
The main work would involve:
- Meta authentication.
- Access token management.
- Webhooks.
- Permissions.
- App Review.
- Message storage.
- User interface changes.
- Testing and policy compliance.
Main Risks and Considerations
- Meta permissions and policies can change.
- Messenger and Instagram should not be treated as unrestricted bulk outreach channels.
- Access tokens and webhook credentials must be stored securely.
- SRFU would need a clear process for consent, opt-out requests, and Do Not Contact status.
- Expired or revoked permissions could interrupt messaging even if the SRFU application itself is working.
Recommendation
I would not recommend building Facebook/Instagram messaging as a core outreach feature for the current project.
Email is still more suitable for SRFU because the team can contact verified public business email addresses while keeping the approval and Do Not Contact controls already built into the system.
A Meta integration could be useful later if SRFU starts receiving regular enquiries through Facebook or Instagram.
A suitable future version could:
1. Receive an inbound Facebook or Instagram message.
2. Match it to an organisation where possible.
3. Allow a staff member to reply.
4. Store the conversation in the outreach history.
Recommended outcome: Feasible as a future inbound/support channel, but not recommended as a replacement for the current email outreach workflow.
Sources
- Meta – Messenger Platform API: https://www.postman.com/meta/messenger-platform-api/documentation/iyp204x/messenger-platform-api
- Meta – Messenger Send API: https://www.postman.com/meta/messenger-platform-api/folder/vilwbh4/send-api
- Meta – Instagram API: https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api
- Meta – Instagram Send API: https://www.postman.com/meta/instagram/folder/uxudqu0/send-api
- Meta official Postman team: https://www.postman.com/meta/
Note: This is a feasibility spike, not a final production design. Meta permissions, policy rules, and pricing should be checked again before implementation.