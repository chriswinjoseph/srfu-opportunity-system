from google import genai
from google.genai import types
from pydantic import BaseModel


class GeneratedEmail(BaseModel):
    subject: str
    body: str


def generate_outreach_email(
    organisation_name,
    organisation_type,
    recipient_email,
    outreach_purpose,
    contact_name="",
    contact_role="",
    region="",
    website="",
):
    client = genai.Client()

    if contact_name:
        greeting = f"Hello {contact_name},"
    else:
        greeting = f"Hello {organisation_name} team,"

    safe_draft = f"""
{greeting}

I am reaching out from Safe Roads For Us regarding {outreach_purpose}.

We would like to explore whether there may be an appropriate
opportunity for community collaboration with {organisation_name}.

If this is something your team would be open to discussing,
please reply to this email or suggest a suitable time for a
short conversation. We would be happy to provide further
information and discuss possible next steps.

Thank you for your time and consideration.

Kind regards,
Safe Roads For Us
"""

    system_instruction = """
You are an email editing assistant for Safe Roads For Us.

You are NOT allowed to add new factual claims.

Your job is only to lightly improve the wording of the supplied
safe draft.

Rules:
- Use Australian English.
- Keep the email professional, friendly and concise.
- Aim for approximately 120 to 150 words excluding the signature.
- Preserve the meaning of the supplied draft.
- Do not add facts that are not already in the supplied draft.
- Do not infer information from organisation name, type,
  location, email address or website.
- Do not invent organisation activities, reputation,
  community involvement, partnerships or commitments.
- Do not invent Safe Roads For Us activities or locations.
- Do not claim previous communication occurred.
- Do not invent funding, sponsorships, dates or events.
- Do not change names.
- Do not add unresolved placeholders.
- Include one simple call to action.
- Do not send or approve the email.
"""

    prompt = f"""
Lightly edit the SAFE DRAFT below.

You may improve grammar, clarity and natural wording.

You MUST NOT add any new factual claims.

SAFE DRAFT:

{safe_draft}

Return only:
1. A concise subject line.
2. The edited email body.
"""

    response = client.models.generate_content(
        model="gemini-3.5-flash-lite",
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            response_schema=GeneratedEmail,
        ),
    )

    result = response.parsed

    if (
        result is None
        or not result.subject.strip()
        or not result.body.strip()
    ):
        raise ValueError(
            "Gemini returned an incomplete email draft."
        )

    return (
        result.subject.strip(),
        result.body.strip(),
    )