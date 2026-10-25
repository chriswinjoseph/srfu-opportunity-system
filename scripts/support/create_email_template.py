"""
Create the approved email template. EDIT THE VALUES BELOW with SRFU-approved wording first.

Run from the project folder (works in PowerShell):

    python manage.py shell -c "exec(open(r'<path>\\create_email_template.py', encoding='utf-8-sig').read())"

Refuses to run while any value still contains PLACEHOLDER, so unapproved text cannot be saved by accident.
The first line of `signature` must appear in generated emails (the draft check looks for it).
"""

from outreach.models import EmailTemplate

VALUES = dict(
    name="PLACEHOLDER template name",
    version="v1",
    purpose="PLACEHOLDER approved purpose",
    template_body="PLACEHOLDER approved structure and wording instructions",
    sender_name="PLACEHOLDER approved sender name",
    sender_role="PLACEHOLDER approved sender role",
    project_details="PLACEHOLDER approved project details",
    call_to_action="PLACEHOLDER approved call to action",
    signature="PLACEHOLDER approved sender name\nSafe Roads For Us",
)

unfinished = [key for key, value in VALUES.items() if "PLACEHOLDER" in value]

if unfinished:
    raise SystemExit("Not created. Replace PLACEHOLDER text in: " + ", ".join(unfinished))

template = EmailTemplate.objects.create(**VALUES)
print("Created email template", template.pk, template.name, template.version, "active =", template.is_active)
