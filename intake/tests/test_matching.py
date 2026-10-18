"""Normalisation and exact/likely duplicate rules for banks, branches, clubs and contacts."""

from django.contrib.contenttypes.models import ContentType

from intake.matching import Submission, find_matches, match_contact
from intake.models import ContactSource, OrganisationSource
from intake.normalise import (
    norm_email, norm_name, norm_phone, norm_postcode, norm_state, norm_url, similarity,
)
from outreach.models import Contact

from .helpers import IntakeTestCase


class NormalisationTests(IntakeTestCase):
    def test_names_ignore_case_spacing_punctuation_and_ampersand(self):
        self.assertEqual(norm_name("  Smith  &  Jones, Community-Bank "), norm_name("smith and jones community bank"))
        self.assertEqual(norm_name("St. Mary's"), "st marys")
        self.assertEqual(norm_name("Northside F.C."), norm_name("northside FC"))

    def test_states_are_standardised(self):
        for raw, code in (("Victoria", "VIC"), ("vic", "VIC"), ("New South Wales", "NSW"),
                          ("w.a.", "WA"), ("Western Australia", "WA"), ("", ""), ("Narnia", "")):
            self.assertEqual(norm_state(raw), code, raw)

    def test_email_phone_url_postcode(self):
        self.assertEqual(norm_email(" Info@Example.TEST "), "info@example.test")
        self.assertEqual(norm_phone("(03) 9555 0000"), "0395550000")
        self.assertEqual(norm_phone("+61 3 9555 0000"), "0395550000")
        self.assertEqual(norm_url("https://www.Example.test/Page/"), "example.test/page")
        self.assertEqual(norm_postcode("3350"), "3350")
        self.assertEqual(norm_postcode("33"), "")

    def test_generic_words_do_not_make_different_towns_similar(self):
        self.assertLess(similarity("Community Bank Yea & District", "Community Bank Kyabram & District"), 90)
        self.assertGreaterEqual(similarity("Alpha Community Bank", "Alpha Community Bank Ltd"), 90)

    def test_original_values_are_kept_for_display(self):
        bank = self.bank("  Smith & Jones  ", "VIC")
        bank.refresh_from_db()

        self.assertEqual(bank.bank_name, "  Smith & Jones  ")


class BankMatchingTests(IntakeTestCase):
    def sub(self, name, state="VIC", **kw):
        return Submission(org_type="bank", name=name, state=state, **kw)

    def test_exact_needs_name_and_state(self):
        bank = self.bank("Alpha Community Bank", "VIC")

        exact = find_matches(self.sub("ALPHA  community bank"))
        self.assertEqual((exact.kind, exact.exact), ("exact", ("bank", bank.pk)))

        other_state = find_matches(self.sub("Alpha Community Bank", "NSW"))
        self.assertEqual(other_state.kind, "none")

    def test_name_alone_is_not_enough_when_the_state_is_missing(self):
        self.bank("Alpha Community Bank", "VIC")

        result = find_matches(self.sub("Alpha Community Bank", ""))

        self.assertEqual(result.kind, "likely")
        self.assertIn("state is missing", " ".join(result.reasons))

    def test_ampersand_equals_and(self):
        bank = self.bank("Smith and Jones Community Bank", "VIC")

        self.assertEqual(find_matches(self.sub("Smith & Jones Community Bank")).exact, ("bank", bank.pk))

    def test_similar_name_same_state_is_likely_never_exact(self):
        self.bank("Alpha Community Bank Ltd", "VIC")

        result = find_matches(self.sub("Alpha Community Bank"))

        self.assertEqual(result.kind, "likely")
        self.assertIsNone(result.exact)
        self.assertGreaterEqual(result.candidates[0]["score"], 90)

    def test_shared_email_phone_or_website_with_a_different_name_is_likely(self):
        self.bank("Totally Different Bank", "QLD", public_email="shared@example.test",
                  public_phone="03 9555 0000", website_url="https://www.shared.test/")

        for kw, text in (
            ({"email": "SHARED@example.test"}, "email"),
            ({"phone": "+61 3 9555 0000"}, "phone"),
            ({"website": "shared.test"}, "website"),
        ):
            with self.subTest(text=text):
                result = find_matches(self.sub("Zulu Community Bank", **kw))
                self.assertEqual(result.kind, "likely")
                self.assertIn(text, " ".join(result.reasons))

    def test_same_name_in_a_different_organisation_type_is_likely(self):
        self.club("Alpha Community Bank", "VIC")

        result = find_matches(self.sub("Alpha Community Bank"))

        self.assertEqual(result.kind, "likely")
        self.assertIn("different organisation type", " ".join(result.reasons))

    def test_trusted_source_id_matches_even_if_the_name_changed_slightly(self):
        bank = self.bank("Alpha Community Bank", "VIC")
        OrganisationSource.objects.create(
            content_type=self.bank_ct, object_id=bank.pk, source_key="s", source_org_id="X1",
            first_collected_at=bank.date_added, last_checked_at=bank.date_added,
        )

        result = find_matches(self.sub("Alpha Community Bank Ltd", source_key="s", source_org_id="X1"))

        self.assertEqual(result.exact, ("bank", bank.pk))

    def test_source_ids_are_scoped_to_their_source(self):
        bank = self.bank("Alpha Community Bank", "VIC")
        OrganisationSource.objects.create(
            content_type=self.bank_ct, object_id=bank.pk, source_key="one", source_org_id="X1",
            first_collected_at=bank.date_added, last_checked_at=bank.date_added,
        )

        result = find_matches(self.sub("Unrelated Credit Union", "WA", source_key="two", source_org_id="X1"))

        self.assertEqual(result.kind, "none")

    def test_conflicting_source_id_evidence_requires_review(self):
        bank = self.bank("Alpha Community Bank", "VIC")
        OrganisationSource.objects.create(
            content_type=self.bank_ct, object_id=bank.pk, source_key="s", source_org_id="X1",
            first_collected_at=bank.date_added, last_checked_at=bank.date_added,
        )

        result = find_matches(self.sub("Alpha Community Bank", "NSW", source_key="s", source_org_id="X1"))

        self.assertEqual(result.kind, "conflict")
        self.assertIsNone(result.exact)

    def test_source_id_and_name_pointing_at_different_banks_requires_review(self):
        a = self.bank("Alpha Community Bank", "VIC")
        self.bank("Zulu Community Bank", "VIC")
        OrganisationSource.objects.create(
            content_type=self.bank_ct, object_id=a.pk, source_key="s", source_org_id="X1",
            first_collected_at=a.date_added, last_checked_at=a.date_added,
        )
        # The source says "this is Alpha" but the name/state is Zulu's.
        result = find_matches(self.sub("Zulu Community Bank", source_key="s", source_org_id="X1"))

        self.assertEqual(result.kind, "conflict")

    def test_two_exact_matches_are_ambiguous_and_held(self):
        self.bank("Alpha Community Bank", "VIC")
        self.bank("Alpha Community Bank", "VIC")

        self.assertEqual(find_matches(self.sub("Alpha Community Bank")).kind, "conflict")

    def test_archived_banks_are_still_matched(self):
        bank = self.bank("Alpha Community Bank", "VIC", is_archived=True)

        result = find_matches(self.sub("Alpha Community Bank"))

        self.assertEqual(result.exact, ("bank", bank.pk))
        self.assertTrue(result.candidates[0]["archived"])


class BranchAndClubMatchingTests(IntakeTestCase):
    def test_branch_exact_needs_parent_name_and_location(self):
        parent = self.bank("Parent Bank", "VIC")
        branch = self.branch(parent, "Main Street", "VIC", suburb="Ballarat", postcode="3350")
        sub = Submission(org_type="branch", name="main street", state="VIC", postcode="3350",
                         parent_bank_name="Parent Bank", parent_bank_state="VIC")

        self.assertEqual(find_matches(sub).exact, ("branch", branch.pk))

        by_suburb = Submission(org_type="branch", name="Main Street", state="VIC", suburb="Ballarat",
                               parent_bank_name="Parent Bank")
        self.assertEqual(find_matches(by_suburb).exact, ("branch", branch.pk))

    def test_branch_without_a_known_parent_or_location_is_never_exact(self):
        parent = self.bank("Parent Bank", "VIC")
        self.branch(parent, "Main Street", "VIC", suburb="Ballarat", postcode="3350")

        no_parent = Submission(org_type="branch", name="Main Street", state="VIC", postcode="3350")
        no_location = Submission(org_type="branch", name="Main Street", state="VIC",
                                 parent_bank_name="Parent Bank")

        self.assertNotEqual(find_matches(no_parent).kind, "exact")
        # Missing location is not evidence of an exact match.
        self.assertEqual(find_matches(no_location).kind, "likely")

    def test_branch_with_another_parent_is_not_exact(self):
        parent = self.bank("Parent Bank", "VIC")
        other = self.bank("Other Bank", "VIC")
        self.branch(parent, "Main Street", "VIC", postcode="3350")
        sub = Submission(org_type="branch", name="Main Street", state="VIC", postcode="3350",
                         parent_bank_name="Other Bank")

        self.assertNotEqual(find_matches(sub).kind, "exact")
        self.assertIsNotNone(other)

    def test_branch_that_looks_like_a_bank_without_a_parent_is_flagged(self):
        self.bank("Alpha Community Bank", "VIC")
        sub = Submission(org_type="branch", name="Alpha Community Bank", state="VIC")

        result = find_matches(sub)

        self.assertEqual(result.kind, "likely")
        self.assertIn("no parent bank", " ".join(result.reasons))

    def test_club_exact_by_postcode_or_suburb(self):
        club = self.club("Northside FC", "VIC", suburb="Essendon", postcode="3040")

        for kw in ({"postcode": "3040"}, {"suburb": "ESSENDON"}):
            with self.subTest(kw=kw):
                sub = Submission(org_type="club", name="Northside F.C.", state="VIC", **kw)
                self.assertEqual(find_matches(sub).exact, ("club", club.pk))

    def test_club_with_missing_location_is_not_an_exact_match(self):
        self.club("Northside FC", "VIC")

        for existing_has_location in (False, True):
            with self.subTest(existing_has_location=existing_has_location):
                sub = Submission(org_type="club", name="Northside FC", state="VIC")
                result = find_matches(sub)
                self.assertEqual(result.kind, "likely")
                self.assertIn("location is missing", " ".join(result.reasons))
                self.club("Eastside FC", "VIC", suburb="Essendon")

    def test_club_with_a_different_location_is_likely_not_exact(self):
        self.club("Northside FC", "VIC", suburb="Essendon", postcode="3040")
        sub = Submission(org_type="club", name="Northside FC", state="VIC", suburb="Niddrie", postcode="3042")

        self.assertEqual(find_matches(sub).kind, "likely")


class ContactMatchingTests(IntakeTestCase):
    def test_same_email_in_the_same_organisation_is_an_exact_contact(self):
        bank = self.bank("Alpha Community Bank", "VIC")
        contact = Contact.objects.create(content_type=self.bank_ct, object_id=bank.pk, email="Info@Example.test")

        self.assertEqual(match_contact(bank, "info@EXAMPLE.test"), ("exact", contact))

    def test_same_email_on_another_organisation_is_flagged_not_merged(self):
        a = self.bank("Alpha Community Bank", "VIC")
        b = self.bank("Bravo Community Bank", "VIC")
        Contact.objects.create(content_type=self.bank_ct, object_id=b.pk, email="shared@example.test")

        kind, others = match_contact(a, "shared@example.test")

        self.assertEqual(kind, "shared")
        self.assertEqual(others, [b])

    def test_source_contact_id_matches_first(self):
        bank = self.bank("Alpha Community Bank", "VIC")
        contact = Contact.objects.create(content_type=self.bank_ct, object_id=bank.pk, email="old@example.test")
        ContactSource.objects.create(contact=contact, source_key="s", source_contact_id="C9")

        self.assertEqual(match_contact(bank, "new@example.test", "s", "C9"), ("exact", contact))
        self.assertEqual(match_contact(bank, "new@example.test", "other", "C9")[0], "none")
