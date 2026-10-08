from django.core.management.base import BaseCommand

from outreach.approvals import flag_overdue_approvals


class Command(BaseCommand):
    help = (
        "Flag email drafts that have been Awaiting Approval longer "
        "than EMAIL_APPROVAL_OVERDUE_HOURS. Schedule this to run "
        "regularly (e.g. hourly). Never approves, rejects or sends."
    )

    def handle(self, *args, **options):
        flagged = flag_overdue_approvals()
        self.stdout.write(
            f"Flagged {len(flagged)} overdue draft(s)."
        )
