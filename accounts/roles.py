"""
Application roles and the permissions each role grants.

The role stored on ``User.role`` is the single source of truth for what a
user may do in the outreach application. Django groups, individually
assigned permissions and the superuser flag are deliberately ignored for
``outreach.*`` permissions (see ``User.has_perm``), so demoting a user
always removes Admin capabilities.
"""

ROLE_ADMIN = "admin"
ROLE_STAFF = "staff"

ROLE_CHOICES = [
    (ROLE_ADMIN, "Admin"),
    (ROLE_STAFF, "Staff"),
]

OUTREACH_APP_LABEL = "outreach"

# Staff: view organisations, prepare drafts, submit them, send approved
# drafts and record outreach outcomes. No organisation management and no
# approval.
STAFF_OUTREACH_PERMISSIONS = frozenset(
    {
        "outreach.view_bank",
        "outreach.view_branch",
        "outreach.view_club",
        "outreach.view_contact",
        "outreach.view_opportunity",
        "outreach.view_emaildraft",
        "outreach.change_opportunity",
        "outreach.generate_emaildraft",
        "outreach.send_emaildraft",
    }
)


def role_has_outreach_permission(role, perm):
    """Whether ``role`` grants the ``outreach.<codename>`` permission."""
    if role == ROLE_ADMIN:
        return perm.startswith(OUTREACH_APP_LABEL + ".")

    if role == ROLE_STAFF:
        return perm in STAFF_OUTREACH_PERMISSIONS

    return False
