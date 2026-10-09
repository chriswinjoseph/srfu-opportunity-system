"""
Create the first Admin securely during system setup.

    python manage.py create_first_admin --email you@example.org \
        --name "Your Name" --base-url https://srfu.example.org

No password is ever chosen, displayed or stored. The command creates a
pending Admin and emails them a one-time password-setup link (or, with
--print-link, prints the link to the operator's terminal once). The
Admin must set their own password before they can sign in.

The command refuses to run once an Admin exists; further accounts are
created through User Management.
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from accounts import services
from accounts.roles import ROLE_ADMIN


class Command(BaseCommand):
    help = "Create the first Admin and issue a password-setup link."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)
        parser.add_argument("--name", required=True)
        parser.add_argument(
            "--base-url",
            required=True,
            help="Public site address used to build the setup link, "
            "for example https://srfu.example.org",
        )
        parser.add_argument(
            "--print-link",
            action="store_true",
            help="Print the setup link instead of emailing it. Treat "
            "the output as a secret.",
        )

    def handle(self, *args, **options):
        User = get_user_model()

        if User.objects.filter(
            role=ROLE_ADMIN,
            is_active=True,
            invitation_pending=False,
        ).exists():
            raise CommandError(
                "An Admin already exists. Create further accounts "
                "through User Management."
            )

        email = User.objects.normalize_email(options["email"]).lower()
        user = User.objects.filter(
            email__iexact=email,
            role=ROLE_ADMIN,
            invitation_pending=True,
        ).first()

        if user is not None:
            # Setup was started earlier but never completed: rotate the
            # credential state so any earlier link stops working.
            user.set_unusable_password()
            user.save(update_fields=["password"])
        else:
            try:
                user = services.create_invited_user(
                    None,
                    options["name"],
                    email,
                    ROLE_ADMIN,
                    action="first_admin_created",
                )
            except services.AccountOperationError as exc:
                raise CommandError(str(exc))

        base_url = options["base_url"]

        if options["print_link"]:
            self.stdout.write(
                "Password-setup link (single use, keep it private):"
            )
            self.stdout.write(
                services.invitation_url(None, user, base_url=base_url)
            )
            services.record_invitation_result(None, user, True)
            return

        delivered = services.send_invitation_email(
            None, user, base_url=base_url
        )
        services.record_invitation_result(None, user, delivered)

        if not delivered:
            raise CommandError(
                "The Admin account exists but the invitation email "
                "could not be sent. Check the email settings and run "
                "this command again (or add --print-link)."
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"First Admin created. A password-setup link was "
                f"emailed to {user.email}."
            )
        )
