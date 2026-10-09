import re
import smtplib
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts import services
from accounts.models import UserActivity
from accounts.roles import ROLE_ADMIN, ROLE_STAFF

User = get_user_model()

PASSWORD = "Testing123!"

DENIED_TEXT = "You do not have permission to access this page."
DISABLED_TEXT = (
    "Your account has been disabled. Please contact an administrator."
)


def make_user(email, role=ROLE_STAFF, **extra):
    return User.objects.create_user(
        email=email,
        first_name=extra.pop("first_name", "Test"),
        last_name=extra.pop("last_name", "User"),
        password=PASSWORD,
        role=role,
        **extra,
    )


@override_settings(DEFAULT_FROM_EMAIL="noreply@example.com")
class UserManagementBase(TestCase):
    def setUp(self):
        self.admin = make_user("admin@example.com", ROLE_ADMIN)
        self.admin2 = make_user("admin2@example.com", ROLE_ADMIN)
        self.staff = make_user("staff@example.com", ROLE_STAFF)

    def login(self, user):
        self.client.force_login(user)

    def invitation_link_from_outbox(self):
        body = mail.outbox[-1].body
        return re.search(r"https?://\S+", body).group(0)


class RolePermissionTests(UserManagementBase):
    def test_admin_and_staff_permission_sets(self):
        for perm in (
            "outreach.approve_emaildraft",
            "outreach.add_bank",
            "outreach.change_bank",
            "outreach.generate_emaildraft",
            "outreach.send_emaildraft",
        ):
            self.assertTrue(self.admin.has_perm(perm), perm)

        for perm in (
            "outreach.generate_emaildraft",
            "outreach.send_emaildraft",
            "outreach.view_bank",
        ):
            self.assertTrue(self.staff.has_perm(perm), perm)

        for perm in (
            "outreach.approve_emaildraft",
            "outreach.add_bank",
            "outreach.add_club",
            "outreach.change_bank",
            "outreach.change_club",
        ):
            self.assertFalse(self.staff.has_perm(perm), perm)

    def test_superuser_flag_does_not_bypass_staff_role(self):
        user = make_user(
            "super-staff@example.com",
            ROLE_STAFF,
            is_superuser=True,
            is_staff=True,
        )

        self.assertFalse(user.has_perm("outreach.approve_emaildraft"))
        self.assertFalse(user.has_perm("outreach.add_bank"))

    def test_groups_and_individual_permissions_do_not_bypass_role(self):
        permission = Permission.objects.get(
            content_type__app_label="outreach",
            codename="approve_emaildraft",
        )
        group = Group.objects.create(name="Legacy approvers")
        group.permissions.add(permission)

        self.staff.groups.add(group)
        self.staff.user_permissions.add(permission)

        staff = User.objects.get(pk=self.staff.pk)

        self.assertFalse(staff.has_perm("outreach.approve_emaildraft"))

    def test_is_staff_flag_is_not_the_staff_role(self):
        user = make_user("flag@example.com", ROLE_STAFF, is_staff=True)

        self.assertFalse(user.has_perm("outreach.add_bank"))
        self.assertFalse(user.is_app_admin)

    def test_unrecognised_role_has_no_outreach_access(self):
        user = make_user("norole@example.com", "")

        self.assertFalse(user.has_perm("outreach.generate_emaildraft"))
        self.assertFalse(user.has_module_perms("outreach"))

    def test_inactive_admin_has_no_permissions(self):
        self.admin2.is_active = False
        self.admin2.save()

        self.assertFalse(self.admin2.has_perm("outreach.approve_emaildraft"))

    def test_role_change_takes_effect_on_next_request(self):
        self.login(self.admin2)

        self.assertEqual(
            self.client.get(reverse("user_list")).status_code, 200
        )

        services.change_role(self.admin, self.admin2, ROLE_STAFF)

        response = self.client.get(reverse("user_list"))

        self.assertEqual(response.status_code, 403)
        self.assertContains(response, DENIED_TEXT, status_code=403)


class SignupRemovedTests(TestCase):
    def test_signup_get_and_post_are_unavailable(self):
        self.assertEqual(self.client.get("/accounts/signup/").status_code, 404)

        response = self.client.post(
            "/accounts/signup/",
            {
                "first_name": "A",
                "last_name": "B",
                "email": "new@example.com",
                "password1": PASSWORD,
                "password2": PASSWORD,
            },
        )

        self.assertEqual(response.status_code, 404)
        self.assertFalse(User.objects.filter(email="new@example.com").exists())

    def test_login_page_has_no_signup_link(self):
        response = self.client.get(reverse("login"))

        self.assertNotContains(response, "Sign up")


class AccessControlTests(UserManagementBase):
    def urls(self):
        pk = self.staff.pk
        return [
            reverse("user_list"),
            reverse("user_add"),
            reverse("user_activity"),
            reverse("user_options", args=[pk]),
            reverse("user_role", args=[pk]),
            reverse("user_reassign_drafts", args=[pk]),
        ]

    def test_staff_gets_permission_message_and_dashboard_link(self):
        self.login(self.staff)

        for url in self.urls():
            response = self.client.get(url)

            self.assertEqual(response.status_code, 403, url)
            self.assertContains(response, DENIED_TEXT, status_code=403)
            self.assertContains(
                response,
                reverse("outreach_dashboard"),
                status_code=403,
            )

    def test_staff_cannot_post_account_changes(self):
        self.login(self.staff)
        pk = self.admin.pk

        for name in ("user_disable", "user_enable", "user_resend_invitation"):
            response = self.client.post(reverse(name, args=[pk]))
            self.assertEqual(response.status_code, 403, name)

        response = self.client.post(reverse("user_role", args=[pk]))
        self.assertEqual(response.status_code, 403)

        response = self.client.post(
            reverse("user_add"),
            {"full_name": "X Y", "email": "x@example.com", "role": "admin"},
        )
        self.assertEqual(response.status_code, 403)

        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)
        self.assertEqual(self.admin.role, ROLE_ADMIN)
        self.assertFalse(User.objects.filter(email="x@example.com").exists())

    def test_anonymous_users_are_sent_to_login(self):
        for url in self.urls():
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302, url)
            self.assertIn(reverse("login"), response["Location"])

    def test_admin_can_open_pages_and_staff_dashboard_hides_users_link(self):
        self.login(self.admin)

        for url in self.urls():
            self.assertEqual(self.client.get(url).status_code, 200, url)

        dashboard = self.client.get(reverse("outreach_dashboard"))
        self.assertContains(dashboard, reverse("user_list"))

        self.login(self.staff)
        dashboard = self.client.get(reverse("outreach_dashboard"))
        self.assertNotContains(dashboard, reverse("user_list"))

    def test_users_link_sits_beside_dashboard_in_the_same_nav_for_admins_only(self):
        self.login(self.admin)
        html = self.client.get(reverse("outreach_dashboard")).content.decode()

        nav = re.search(
            r'<nav class="topbar-nav".*?</nav>', html, re.S
        ).group(0)

        self.assertLess(
            nav.index(reverse("outreach_dashboard")),
            nav.index(reverse("user_list")),
        )
        self.assertIn('aria-current="page"', nav)

        self.login(self.staff)
        html = self.client.get(reverse("outreach_dashboard")).content.decode()
        nav = re.search(r'<nav class="topbar-nav".*?</nav>', html, re.S).group(0)
        self.assertNotIn(reverse("user_list"), nav)

    def test_user_list_empty_staff_state(self):
        self.staff.delete()
        self.login(self.admin)

        response = self.client.get(reverse("user_list"))

        self.assertContains(response, "No staff users have been added yet.")
        self.assertContains(response, reverse("user_add"))

    def test_no_delete_user_action_exists(self):
        self.login(self.admin)

        response = self.client.get(
            reverse("user_options", args=[self.staff.pk])
        )

        self.assertNotContains(response, "Delete")
        self.assertNotContains(response, "one-time", status_code=200)
        self.assertNotContains(response, "OTP")


@override_settings(DEFAULT_FROM_EMAIL="noreply@example.com")
class CreateUserAndInvitationTests(UserManagementBase):
    def create(self, **overrides):
        data = {
            "full_name": "Jane Citizen",
            "email": "jane@example.com",
            "role": "staff",
        }
        data.update(overrides)
        return self.client.post(reverse("user_add"), data)

    def test_admin_creates_pending_user_and_invitation_is_emailed(self):
        self.login(self.admin)

        response = self.create()

        user = User.objects.get(email="jane@example.com")

        self.assertRedirects(
            response, reverse("user_options", args=[user.pk])
        )
        self.assertEqual(user.role, ROLE_STAFF)
        self.assertEqual(user.first_name, "Jane")
        self.assertEqual(user.last_name, "Citizen")
        self.assertTrue(user.invitation_pending)
        self.assertTrue(user.is_active)
        self.assertFalse(user.has_usable_password())
        self.assertEqual(user.account_state, "pending")

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["jane@example.com"])
        self.assertIn("/accounts/reset/", mail.outbox[0].body)
        self.assertNotIn("password:", mail.outbox[0].body.lower())

        self.assertTrue(
            UserActivity.objects.filter(
                action="user_created", target=user, actor=self.admin
            ).exists()
        )
        self.assertTrue(
            UserActivity.objects.filter(
                action="invitation_sent", target=user
            ).exists()
        )

    def test_pending_user_cannot_log_in(self):
        self.login(self.admin)
        self.create()

        self.client.logout()

        response = self.client.post(
            reverse("login"),
            {"username": "jane@example.com", "password": PASSWORD},
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.wsgi_request.user.is_authenticated)

    def test_admin_can_create_admin(self):
        self.login(self.admin)

        self.create(email="boss@example.com", role="admin")

        self.assertEqual(
            User.objects.get(email="boss@example.com").role, ROLE_ADMIN
        )

    def test_validation_errors_are_per_field_and_input_is_kept(self):
        self.login(self.admin)

        response = self.client.post(
            reverse("user_add"),
            {"full_name": "Keep Me", "email": "not-an-email", "role": ""},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Enter a valid email address.")
        self.assertContains(response, "Please choose a role.")
        self.assertContains(response, 'value="Keep Me"')
        self.assertContains(response, 'value="not-an-email"')
        self.assertEqual(User.objects.count(), 3)
        self.assertEqual(len(mail.outbox), 0)

    def test_missing_required_fields(self):
        self.login(self.admin)

        response = self.client.post(reverse("user_add"), {})

        self.assertContains(response, "User name is required.")
        self.assertContains(response, "User email is required.")
        self.assertContains(response, "Please choose a role.")

    def test_duplicate_email_is_rejected_case_insensitively(self):
        self.login(self.admin)

        response = self.create(email="STAFF@example.com")

        self.assertContains(
            response, "A user with this email address already exists."
        )
        self.assertEqual(User.objects.count(), 3)

    def test_contact_number_is_not_collected(self):
        self.login(self.admin)

        response = self.client.get(reverse("user_add"))

        self.assertNotContains(response, "Contact Number")

    def test_delivery_failure_keeps_pending_user_and_allows_resend(self):
        self.login(self.admin)

        with patch(
            "accounts.services.send_mail",
            side_effect=smtplib.SMTPException("boom"),
        ):
            response = self.create()

        user = User.objects.get(email="jane@example.com")

        self.assertRedirects(
            response,
            reverse("user_options", args=[user.pk]),
            fetch_redirect_response=False,
        )
        self.assertTrue(user.invitation_pending)
        self.assertIsNone(user.invitation_sent_at)
        self.assertTrue(
            UserActivity.objects.filter(
                action="invitation_failed", target=user
            ).exists()
        )

        page = self.client.get(reverse("user_options", args=[user.pk]))
        self.assertContains(page, "could not be sent")
        self.assertContains(page, "Invitation has not been delivered yet.")
        self.assertContains(page, "Resend Invitation")
        self.assertNotContains(page, "boom")

        self.client.post(reverse("user_resend_invitation", args=[user.pk]))

        self.assertEqual(len(mail.outbox), 1)
        user.refresh_from_db()
        self.assertIsNotNone(user.invitation_sent_at)

    def test_invitation_sets_password_once_and_clears_pending(self):
        self.login(self.admin)
        self.create()
        link = self.invitation_link_from_outbox()

        self.client.logout()

        response = self.client.get(link, follow=True)
        set_url = response.redirect_chain[-1][0]

        response = self.client.post(
            set_url,
            {
                "new_password1": "Brand-New-1Pass!",
                "new_password2": "Brand-New-1Pass!",
            },
        )

        self.assertEqual(response.status_code, 302)

        user = User.objects.get(email="jane@example.com")

        self.assertFalse(user.invitation_pending)
        self.assertTrue(user.check_password("Brand-New-1Pass!"))
        self.assertTrue(
            UserActivity.objects.filter(
                action="invitation_accepted", target=user
            ).exists()
        )

        # The same link cannot be used again.
        self.client.logout()
        reuse = self.client.get(link)
        self.assertContains(reuse, "invalid")

    def test_expired_invitation_is_rejected(self):
        self.login(self.admin)
        self.create()
        link = self.invitation_link_from_outbox()
        self.client.logout()

        future = timezone.now() + timedelta(days=30)

        with patch.object(
            type(default_token_generator),
            "_now",
            lambda self_: future.replace(tzinfo=None),
        ):
            response = self.client.get(link)

        self.assertFalse(response.context["validlink"])

    def test_password_policy_still_applies_to_invitation(self):
        self.login(self.admin)
        self.create()
        link = self.invitation_link_from_outbox()
        self.client.logout()

        response = self.client.get(link, follow=True)
        set_url = response.redirect_chain[-1][0]

        response = self.client.post(
            set_url,
            {"new_password1": "weakpass", "new_password2": "weakpass"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            User.objects.get(email="jane@example.com").invitation_pending
        )

    def test_resend_invalidates_the_previous_link(self):
        self.login(self.admin)
        self.create()
        old_link = self.invitation_link_from_outbox()
        user = User.objects.get(email="jane@example.com")

        self.client.post(reverse("user_resend_invitation", args=[user.pk]))
        new_link = self.invitation_link_from_outbox()

        self.client.logout()

        self.assertNotEqual(old_link, new_link)
        self.assertFalse(self.client.get(old_link).context["validlink"])
        self.assertTrue(
            self.client.get(new_link, follow=True).context["validlink"]
        )

    def test_only_admin_can_resend_and_only_for_pending_users(self):
        self.login(self.admin)
        self.create()
        user = User.objects.get(email="jane@example.com")

        self.login(self.staff)
        self.assertEqual(
            self.client.post(
                reverse("user_resend_invitation", args=[user.pk])
            ).status_code,
            403,
        )

        self.login(self.admin)
        mail.outbox.clear()
        self.client.post(
            reverse("user_resend_invitation", args=[self.staff.pk])
        )
        self.assertEqual(len(mail.outbox), 0)

    def test_creation_failure_saves_nothing(self):
        self.login(self.admin)

        with patch(
            "accounts.services.UserActivity.objects.create",
            side_effect=RuntimeError("db"),
        ):
            with self.assertRaises(RuntimeError):
                services.create_invited_user(
                    self.admin, "No Partial", "partial@example.com", "staff"
                )

        self.assertFalse(
            User.objects.filter(email="partial@example.com").exists()
        )


class RoleChangeTests(UserManagementBase):
    def test_confirmation_page_then_promotion_is_audited(self):
        self.login(self.admin)
        url = reverse("user_role", args=[self.staff.pk])

        page = self.client.get(url)
        self.assertContains(page, "Swap Role")
        self.staff.refresh_from_db()
        self.assertEqual(self.staff.role, ROLE_STAFF)

        self.client.post(url)

        self.staff.refresh_from_db()
        self.assertEqual(self.staff.role, ROLE_ADMIN)
        self.assertTrue(self.staff.has_perm("outreach.approve_emaildraft"))

        activity = UserActivity.objects.get(action="role_changed")
        self.assertEqual(activity.previous_value, ROLE_STAFF)
        self.assertEqual(activity.new_value, ROLE_ADMIN)
        self.assertEqual(activity.actor, self.admin)
        self.assertEqual(activity.target, self.staff)

    def test_admin_can_demote_another_admin_and_legacy_power_is_removed(self):
        self.admin2.is_superuser = True
        self.admin2.is_staff = True
        self.admin2.save()
        group = Group.objects.create(name="g")
        self.admin2.groups.add(group)

        self.login(self.admin)
        self.client.post(reverse("user_role", args=[self.admin2.pk]))

        self.admin2.refresh_from_db()
        self.assertEqual(self.admin2.role, ROLE_STAFF)
        self.assertFalse(self.admin2.is_superuser)
        self.assertFalse(self.admin2.is_staff)
        self.assertEqual(self.admin2.groups.count(), 0)
        self.assertFalse(self.admin2.has_perm("outreach.approve_emaildraft"))
        self.assertTrue(self.admin.is_app_admin)

    def test_own_role_cannot_be_changed_and_control_is_hidden(self):
        self.login(self.admin)

        page = self.client.get(reverse("user_options", args=[self.admin.pk]))
        self.assertNotContains(page, "Assign new role")
        self.assertNotContains(page, "Disable User")

        response = self.client.post(
            reverse("user_role", args=[self.admin.pk]), follow=True
        )

        self.assertContains(response, "You cannot change your own role")
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.role, ROLE_ADMIN)

    def test_demotion_is_rechecked_against_current_roles(self):
        # A stale Admin instance (already demoted elsewhere) cannot act.
        stale_admin = User.objects.get(pk=self.admin.pk)
        services.change_role(self.admin2, self.admin, ROLE_STAFF)

        with self.assertRaises(services.AccountOperationError):
            services.change_role(stale_admin, self.admin2, ROLE_STAFF)

        self.admin2.refresh_from_db()
        self.assertEqual(self.admin2.role, ROLE_ADMIN)

    def test_role_change_failure_is_atomic(self):
        with patch(
            "accounts.services.UserActivity.objects.create",
            side_effect=RuntimeError("db"),
        ):
            with self.assertRaises(RuntimeError):
                services.change_role(self.admin, self.staff, ROLE_ADMIN)

        self.staff.refresh_from_db()
        self.assertEqual(self.staff.role, ROLE_STAFF)

    def test_pending_admin_does_not_count_as_active_admin(self):
        pending = services.create_invited_user(
            self.admin, "Pending Admin", "pending@example.com", "admin"
        )

        self.assertFalse(services._is_active_admin(pending))
        self.assertTrue(services._is_active_admin(self.admin))

        # With admin2 demoted, the only signed-in Admin is self.admin.
        # A pending Admin must not be counted as someone who could take
        # over, so the guard still protects self.admin.
        services.change_role(self.admin, self.admin2, ROLE_STAFF)

        admins = [
            a for a in User.objects.filter(role=ROLE_ADMIN)
            if services._is_active_admin(a)
        ]
        self.assertEqual(admins, [self.admin])


class DisableAccountTests(UserManagementBase):
    def test_disable_blocks_login_with_required_message(self):
        self.login(self.admin)
        self.client.post(reverse("user_disable", args=[self.staff.pk]))

        self.staff.refresh_from_db()
        self.assertFalse(self.staff.is_active)
        self.assertEqual(self.staff.account_state, "disabled")

        self.client.logout()

        response = self.client.post(
            reverse("login"),
            {"username": "staff@example.com", "password": PASSWORD},
        )

        self.assertContains(response, DISABLED_TEXT)
        self.assertFalse(response.wsgi_request.user.is_authenticated)

    def test_wrong_password_for_disabled_user_does_not_reveal_status(self):
        services.disable_user(self.admin, self.staff)

        response = self.client.post(
            reverse("login"),
            {"username": "staff@example.com", "password": "Wrong-1pass!"},
        )

        self.assertNotContains(response, "disabled")

    def test_existing_session_is_signed_out_on_next_request(self):
        staff_client = self.client_class()
        staff_client.force_login(self.staff)
        self.assertEqual(
            staff_client.get(reverse("outreach_dashboard")).status_code, 200
        )

        services.disable_user(self.admin, self.staff)

        response = staff_client.get(reverse("outreach_dashboard"))

        self.assertContains(response, DISABLED_TEXT, status_code=403)

        # The session is gone: a further request is simply anonymous.
        again = staff_client.get(reverse("outreach_dashboard"))
        self.assertEqual(again.status_code, 302)
        self.assertIn(reverse("login"), again["Location"])

    def test_cannot_disable_self(self):
        self.login(self.admin)

        response = self.client.post(
            reverse("user_disable", args=[self.admin.pk]), follow=True
        )

        self.assertContains(response, "cannot disable your own account")
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_last_active_admin_cannot_be_disabled_by_a_stale_session(self):
        # Two Admins disable each other at the same time. Whoever loses
        # the race is no longer an Admin when their request is applied,
        # so the remaining Admin can never be removed.
        stale_admin = User.objects.get(pk=self.admin.pk)

        services.disable_user(self.admin2, self.admin)

        with self.assertRaises(services.AccountOperationError):
            services.disable_user(stale_admin, self.admin2)

        self.admin2.refresh_from_db()
        self.assertTrue(self.admin2.is_active)
        self.assertTrue(self.admin2.is_app_admin)

    def test_disable_failure_is_atomic(self):
        with patch(
            "accounts.services.UserActivity.objects.create",
            side_effect=RuntimeError("db"),
        ):
            with self.assertRaises(RuntimeError):
                services.disable_user(self.admin, self.staff)

        self.staff.refresh_from_db()
        self.assertTrue(self.staff.is_active)

    def test_enable_restores_access_and_is_audited(self):
        services.disable_user(self.admin, self.staff)
        self.login(self.admin)

        page = self.client.get(reverse("user_options", args=[self.staff.pk]))
        self.assertContains(page, "Re-enable User")
        self.assertNotContains(page, "Disable User")

        self.client.post(reverse("user_enable", args=[self.staff.pk]))

        self.staff.refresh_from_db()
        self.assertTrue(self.staff.is_active)
        self.assertTrue(
            UserActivity.objects.filter(action="account_enabled").exists()
        )

        self.client.logout()
        response = self.client.post(
            reverse("login"),
            {"username": "staff@example.com", "password": PASSWORD},
        )
        self.assertRedirects(
            response,
            reverse("outreach_dashboard"),
            fetch_redirect_response=False,
        )

    def test_disabled_user_cannot_regain_access_with_setup_or_reset_link(self):
        uid = services.urlsafe_base64_encode(
            services.force_bytes(self.staff.pk)
        )
        token = default_token_generator.make_token(self.staff)
        link = reverse(
            "password_reset_confirm",
            kwargs={"uidb64": uid, "token": token},
        )
        services.disable_user(self.admin, self.staff)

        response = self.client.get(link)

        self.assertFalse(response.context["validlink"])

        mail.outbox.clear()
        self.client.post(
            reverse("forgot_password"), {"email": "staff@example.com"}
        )
        self.assertEqual(len(mail.outbox), 0)

    def test_pending_user_cannot_use_forgot_password(self):
        pending = services.create_invited_user(
            self.admin, "Pend Ing", "pend@example.com", "staff"
        )

        mail.outbox.clear()
        self.client.post(
            reverse("forgot_password"), {"email": pending.email}
        )

        self.assertEqual(len(mail.outbox), 0)

    def test_active_user_forgot_password_still_works(self):
        mail.outbox.clear()

        response = self.client.post(
            reverse("forgot_password"), {"email": "staff@example.com"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)

    def test_disable_preserves_records_and_unfinished_drafts_can_move(self):
        from outreach.models import Bank, EmailDraft, Opportunity
        from django.contrib.contenttypes.models import ContentType

        bank = Bank.objects.create(
            bank_name="Reassign Bank",
            region="Victoria",
            public_email="reassign@example.com",
        )
        opportunity = Opportunity.objects.create(
            content_type=ContentType.objects.get_for_model(Bank),
            object_id=bank.pk,
            status="not_yet_contacted",
        )
        unfinished = EmailDraft.objects.create(
            opportunity=opportunity,
            recipient_email=bank.public_email,
            subject="S",
            body="B",
            requested_by=self.staff,
            workflow_status="draft",
        )
        finished = EmailDraft.objects.create(
            opportunity=opportunity,
            recipient_email=bank.public_email,
            subject="S2",
            body="B2",
            requested_by=self.staff,
            workflow_status="sent",
        )

        services.disable_user(self.admin, self.staff)

        unfinished.refresh_from_db()
        self.assertEqual(unfinished.requested_by, self.staff)

        version_before = unfinished.version
        self.login(self.admin)
        response = self.client.post(
            reverse("user_reassign_drafts", args=[self.staff.pk]),
            {"destination": self.admin2.pk},
        )

        self.assertEqual(response.status_code, 302)

        unfinished.refresh_from_db()
        finished.refresh_from_db()

        self.assertEqual(unfinished.assigned_to, self.admin2)
        self.assertEqual(unfinished.requested_by, self.staff)
        self.assertEqual(unfinished.version, version_before)
        self.assertEqual(unfinished.workflow_status, "draft")
        self.assertIsNone(finished.assigned_to)
        self.assertTrue(unfinished.user_can_modify(self.admin2))
        self.assertTrue(
            unfinished.workflow_history.filter(action="reassigned").exists()
        )
        self.assertTrue(
            UserActivity.objects.filter(action="drafts_reassigned").exists()
        )

    def test_reassign_requires_active_destination(self):
        inactive = make_user("gone@example.com", ROLE_STAFF, is_active=False)

        with self.assertRaises(services.AccountOperationError):
            services.reassign_unfinished_drafts(
                self.admin, self.staff, inactive
            )


class ActivityHistoryTests(UserManagementBase):
    def test_history_is_admin_only_and_never_deleted_automatically(self):
        self.login(self.staff)
        self.assertEqual(
            self.client.get(reverse("user_activity")).status_code, 403
        )

        services.change_role(self.admin, self.staff, ROLE_ADMIN)

        self.login(self.admin)
        response = self.client.get(reverse("user_activity"))

        self.assertContains(response, "Role changed")
        self.assertContains(response, "staff@example.com")

        self.assertEqual(UserActivity.objects.count(), 1)


class DjangoAdminBypassTests(UserManagementBase):
    def test_staff_role_cannot_use_django_admin_even_with_is_staff(self):
        user = make_user(
            "adminsite@example.com", ROLE_STAFF, is_staff=True,
            is_superuser=True,
        )
        self.login(user)

        response = self.client.get("/admin/")

        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response["Location"])

    def test_user_admin_is_read_only(self):
        admin_site_user = make_user(
            "dev@example.com", ROLE_ADMIN, is_staff=True, is_superuser=True
        )
        self.login(admin_site_user)

        self.assertEqual(self.client.get("/admin/accounts/user/").status_code, 200)

        response = self.client.post(
            f"/admin/accounts/user/{self.staff.pk}/change/",
            {"role": "admin", "is_superuser": "on"},
        )
        self.assertIn(response.status_code, (302, 403))

        self.staff.refresh_from_db()
        self.assertEqual(self.staff.role, ROLE_STAFF)
        self.assertFalse(self.staff.is_superuser)

        self.assertEqual(
            self.client.get("/admin/accounts/user/add/").status_code, 403
        )
        self.assertEqual(
            self.client.post(
                f"/admin/accounts/user/{self.staff.pk}/delete/", {"post": "yes"}
            ).status_code,
            403,
        )
        self.assertTrue(User.objects.filter(pk=self.staff.pk).exists())

    def test_organisations_cannot_be_deleted_in_django_admin(self):
        from outreach.models import Bank

        dev = make_user(
            "dev2@example.com", ROLE_ADMIN, is_staff=True, is_superuser=True
        )
        bank = Bank.objects.create(bank_name="Keep", region="Victoria")
        self.login(dev)

        response = self.client.post(
            f"/admin/outreach/bank/{bank.pk}/delete/", {"post": "yes"}
        )

        self.assertEqual(response.status_code, 403)
        self.assertTrue(Bank.objects.filter(pk=bank.pk).exists())


@override_settings(DEFAULT_FROM_EMAIL="noreply@example.com")
class FirstAdminSetupTests(TestCase):
    def run_command(self, *args):
        out = StringIO()
        call_command(
            "create_first_admin",
            "--email", "first@example.com",
            "--name", "First Admin",
            "--base-url", "https://srfu.example.org",
            *args,
            stdout=out,
        )
        return out.getvalue()

    def test_empty_database_is_supported_and_no_default_credentials(self):
        self.assertEqual(User.objects.count(), 0)

        self.run_command()

        user = User.objects.get()

        self.assertEqual(user.role, ROLE_ADMIN)
        self.assertTrue(user.invitation_pending)
        self.assertFalse(user.has_usable_password())
        self.assertFalse(user.is_superuser)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("https://srfu.example.org/accounts/reset/", mail.outbox[0].body)
        self.assertTrue(
            UserActivity.objects.filter(action="first_admin_created").exists()
        )

    def test_first_admin_cannot_sign_in_before_setting_a_password(self):
        self.run_command()

        response = self.client.post(
            reverse("login"),
            {"username": "first@example.com", "password": "anything"},
        )

        self.assertFalse(response.wsgi_request.user.is_authenticated)

    def test_refuses_when_an_active_admin_exists(self):
        make_user("existing@example.com", ROLE_ADMIN)

        with self.assertRaises(CommandError):
            self.run_command()

    def test_rerun_reissues_link_for_unfinished_setup(self):
        self.run_command()
        first_link = re.search(r"https?://\S+", mail.outbox[-1].body).group(0)

        self.run_command()

        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 2)
        second_link = re.search(r"https?://\S+", mail.outbox[-1].body).group(0)
        self.assertNotEqual(first_link, second_link)
        self.assertFalse(self.client.get(first_link).context["validlink"])

    def test_print_link_outputs_a_link_not_a_password(self):
        output = self.run_command("--print-link")

        self.assertIn("https://srfu.example.org/accounts/reset/", output)
        self.assertEqual(len(mail.outbox), 0)

    def test_delivery_failure_is_reported_without_internals(self):
        with patch(
            "accounts.services.send_mail",
            side_effect=smtplib.SMTPException("secret-detail"),
        ):
            with self.assertRaises(CommandError) as ctx:
                self.run_command()

        self.assertNotIn("secret-detail", str(ctx.exception))
        self.assertTrue(User.objects.filter(email="first@example.com").exists())

    def test_createsuperuser_creates_an_admin_role(self):
        user = User.objects.create_superuser(
            "su@example.com", "Su", "Per", PASSWORD
        )

        self.assertEqual(user.role, ROLE_ADMIN)


class InitialRoleMigrationTests(TransactionTestCase):
    """Run the data migration in the real migration framework."""

    migrate_from = [("accounts", "0002_admin_roles_and_archiving")]
    migrate_to = [("accounts", "0003_assign_initial_roles")]

    def migrate(self, targets):
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor

        executor = MigrationExecutor(connection)
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def tearDown(self):
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor

        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())

    def test_existing_accounts_keep_appropriate_access(self):
        old_apps = self.migrate(self.migrate_from)
        OldUser = old_apps.get_model("accounts", "User")
        Permission = old_apps.get_model("auth", "Permission")
        Group = old_apps.get_model("auth", "Group")

        def make(email, **kw):
            return OldUser.objects.create(
                email=email, first_name="A", last_name="B", password="x", **kw
            )

        superuser = make("su@example.com", is_superuser=True, is_staff=True)
        approver = make("approver@example.com")
        group_approver = make("grp@example.com")
        organiser = make("org@example.com")
        plain = make("plain@example.com", is_staff=True)

        perm = Permission.objects.get(
            codename="approve_emaildraft",
            content_type__app_label="outreach",
        )
        add_bank = Permission.objects.get(
            codename="add_bank", content_type__app_label="outreach"
        )
        approver.user_permissions.add(perm)
        organiser.user_permissions.add(add_bank)
        group = Group.objects.create(name="approvers")
        group.permissions.add(perm)
        group_approver.groups.add(group)

        new_apps = self.migrate(self.migrate_to)
        NewUser = new_apps.get_model("accounts", "User")

        role = lambda user: NewUser.objects.get(pk=user.pk).role

        self.assertEqual(role(superuser), "admin")
        self.assertEqual(role(approver), "admin")
        self.assertEqual(role(group_approver), "admin")
        self.assertEqual(role(organiser), "admin")
        self.assertEqual(role(plain), "staff")

    def test_empty_database_migrates_without_error(self):
        self.migrate(self.migrate_from)

        new_apps = self.migrate(self.migrate_to)

        self.assertEqual(
            new_apps.get_model("accounts", "User").objects.count(), 0
        )
