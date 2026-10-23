from django.test import TestCase
from django.urls import reverse

from outreach.models import Bank, Club
from outreach.test_roles_and_organisations import make_user


class IdenticalNameWithoutLocationTests(TestCase):
    """
    The client workbook holds banks with a State but no suburb or postcode.
    Adding the same bank by hand must warn (and can be confirmed), as the import does.
    """

    def setUp(self):
        self.admin = make_user("dup-admin@example.com", "admin")
        self.client.force_login(self.admin)
        Bank.objects.create(
            bank_name="Community Bank Yea & District",
            state="VIC",
            public_email="yea@example.org",
            contact_status="not_yet_contacted",
        )

    def add(self, **extra):
        data = {
            "organisation_type": "bank",
            "bank_name": "Community Bank Yea & District",
            "state": "VIC",
            "public_email": "another@example.org",
            "region": "",
            "suburb": "",
            "postcode": "",
        }
        data.update(extra)

        return self.client.post(reverse("add_organisation"), data)

    def test_the_same_name_in_the_same_state_with_no_location_is_held_for_confirmation(self):
        response = self.add()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Bank.objects.count(), 1)
        self.assertContains(response, "Community Bank Yea")
        self.assertContains(response, "different")

    def test_name_variations_with_the_same_normalised_text_are_held_too(self):
        for name in ("community bank yea and district", "Community  Bank Yea & District."):
            with self.subTest(name=name):
                response = self.add(bank_name=name)

                self.assertEqual(response.status_code, 200)
                self.assertEqual(Bank.objects.count(), 1)

    def test_confirming_that_it_is_different_creates_it_and_records_the_override(self):
        response = self.add(confirm_likely_duplicate="1", duplicate_override_reason="A separate legal entity")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Bank.objects.count(), 2)
        created = Bank.objects.exclude(public_email="yea@example.org").get()
        self.assertEqual(created.duplicate_override_reason, "A separate legal entity")
        self.assertEqual(created.contact_status, "not_yet_contacted")

    def test_a_different_state_is_not_flagged(self):
        response = self.add(state="NSW")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Bank.objects.count(), 2)

    def test_two_known_and_different_locations_are_not_flagged(self):
        Bank.objects.all().delete()
        Bank.objects.create(
            bank_name="Eagles Bank", state="VIC", suburb="Essendon", postcode="3040",
            public_email="e1@example.org", contact_status="not_yet_contacted",
        )

        response = self.add(bank_name="Eagles Bank", suburb="Carlton", postcode="3053")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Bank.objects.count(), 2)

    def test_a_known_location_against_a_record_with_none_is_flagged(self):
        response = self.add(suburb="Yea", postcode="3717")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Bank.objects.count(), 1)

    def test_clubs_follow_the_same_rule(self):
        Club.objects.create(club_name="Sample FC", club_type="sport", state="VIC", public_email="c@example.org",
                            contact_status="not_yet_contacted")

        response = self.client.post(reverse("add_organisation"), {
            "organisation_type": "club", "club_name": "Sample FC", "club_type": "sport", "state": "VIC",
            "public_email": "other-club@example.org", "region": "", "suburb": "", "postcode": "",
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Club.objects.count(), 1)
