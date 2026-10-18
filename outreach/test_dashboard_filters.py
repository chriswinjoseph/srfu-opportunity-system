"""
Dashboard search and filter behaviour.

Fixture names deliberately avoid the words "bank", "branch" and "club" so a
type search can only succeed through organisation-type matching, never
through an accidental name match.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from outreach.models import Bank, Branch, Club

User = get_user_model()

PASSWORD = "Testing123!"


def make_user(email, role):
    return User.objects.create_user(
        email=email,
        first_name="Test",
        last_name="User",
        password=PASSWORD,
        role=role,
    )


class DashboardFilterBase(TestCase):
    def setUp(self):
        self.admin = make_user("admin-filter@example.com", "admin")
        self.staff = make_user("staff-filter@example.com", "staff")

        self.alpha = Bank.objects.create(
            bank_name="Alpha Co-operative",
            region="Gippsland",
            state="VIC",
            public_email="alpha@example.com",
            contact_status="not_yet_contacted",
        )
        self.parent = Bank.objects.create(
            bank_name="Parent Holdings",
            region="Melbourne",
            state="VIC",
            public_email="parent@example.com",
            contact_status="contacted",
        )
        self.zephyr = Branch.objects.create(
            bank=self.alpha,
            branch_name="Zephyr Outlet",
            region="Gippsland",
            state="VIC",
            public_email="zephyr@example.com",
            contact_status="not_yet_contacted",
        )
        self.orion = Club.objects.create(
            club_name="Orion Athletics",
            region="Melbourne",
            state="VIC",
            public_email="orion@example.com",
            contact_status="contacted",
        )

    def api(self, **params):
        response = self.client.get(
            reverse("organisation_list_api"), params
        )
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def names(self, **params):
        return sorted(row["name"] for row in self.api(**params)["results"])


class TypeSearchTests(DashboardFilterBase):
    def test_type_words_match_by_type_not_name_for_both_roles(self):
        for user in (self.admin, self.staff):
            self.client.force_login(user)

            for term, expected in (
                ("branch", ["Zephyr Outlet"]),
                ("BRANCH", ["Zephyr Outlet"]),
                ("Branches", ["Zephyr Outlet"]),
                ("bank", ["Alpha Co-operative", "Parent Holdings"]),
                ("Banks", ["Alpha Co-operative", "Parent Holdings"]),
                ("club", ["Orion Athletics"]),
                ("CLUBS", ["Orion Athletics"]),
            ):
                with self.subTest(user=user.role, term=term):
                    self.assertEqual(self.names(q=term), expected)

    def test_existing_text_search_still_works(self):
        self.client.force_login(self.admin)

        self.assertEqual(self.names(q="zephyr"), ["Zephyr Outlet"])
        self.assertEqual(self.names(q="orion@example"), ["Orion Athletics"])
        self.assertEqual(
            self.names(q="Gippsland"),
            ["Alpha Co-operative", "Zephyr Outlet"],
        )

    def test_name_match_is_kept_alongside_type_match(self):
        Club.objects.create(
            club_name="Branchline Runners",
            region="Melbourne",
            state="VIC",
            public_email="runners@example.com",
        )
        self.client.force_login(self.admin)

        self.assertEqual(
            self.names(q="branch"),
            ["Branchline Runners", "Zephyr Outlet"],
        )

    def test_archived_organisations_stay_hidden_from_type_search(self):
        self.zephyr.is_archived = True
        self.zephyr.save(update_fields=["is_archived"])
        self.client.force_login(self.admin)

        self.assertEqual(self.names(q="branch"), [])


class TypeFilterAndCombinationTests(DashboardFilterBase):
    def test_type_filter_for_all_three_types(self):
        self.client.force_login(self.staff)

        self.assertEqual(
            self.names(type="bank"),
            ["Alpha Co-operative", "Parent Holdings"],
        )
        self.assertEqual(self.names(type="branch"), ["Zephyr Outlet"])
        self.assertEqual(self.names(type="club"), ["Orion Athletics"])
        self.assertEqual(len(self.names()), 4)

    def test_search_type_region_and_status_combine(self):
        self.client.force_login(self.admin)

        self.assertEqual(
            self.names(type="bank", region="Gippsland"),
            ["Alpha Co-operative"],
        )
        self.assertEqual(
            self.names(type="bank", status="contacted"),
            ["Parent Holdings"],
        )
        self.assertEqual(
            self.names(q="alpha", type="bank", region="Gippsland",
                       status="not_yet_contacted"),
            ["Alpha Co-operative"],
        )
        # Contradictory combinations narrow to nothing.
        self.assertEqual(self.names(type="club", region="Gippsland"), [])
        self.assertEqual(
            self.names(q="branch", type="club"), [],
        )
        self.assertEqual(
            self.names(q="branch", status="contacted"), [],
        )

    def test_empty_result_is_a_valid_empty_list(self):
        self.client.force_login(self.admin)

        data = self.api(q="nothing-matches-this")

        self.assertEqual(data["results"], [])

    def test_pagination_keeps_filters(self):
        for index in range(6):
            Branch.objects.create(
                bank=self.alpha,
                branch_name=f"Outlet {index}",
                region="Gippsland",
                state="VIC",
                public_email=f"outlet{index}@example.com",
            )
        self.client.force_login(self.admin)

        page1 = self.api(q="branch", page=1, page_size=4)
        page2 = self.api(q="branch", page=2, page_size=4)

        # 7 branches in total: 4 on the first page, 3 on the second.
        self.assertEqual(len(page1["results"]), 4)
        self.assertEqual(len(page2["results"]), 3)
        for row in page1["results"] + page2["results"]:
            self.assertEqual(row["type"], "branch")
        self.assertEqual(
            page1["pagination"]["total_items"],
            page2["pagination"]["total_items"],
        )


class DashboardControlsTests(DashboardFilterBase):
    def test_dashboard_shows_visible_filters_and_order_by(self):
        for user in (self.admin, self.staff):
            self.client.force_login(user)
            html = self.client.get(reverse("outreach_dashboard")).content.decode()

            with self.subTest(role=user.role):
                self.assertNotRegex(
                    html, r'<input[^>]*type="hidden"[^>]*name="(type|region)"'
                )
                self.assertIn('<select id="typeFilter"', html)
                for label in ("All", "Bank", "Branch", "Club"):
                    self.assertIn(f">{label}</option>", html)
                self.assertIn('<select id="regionFilter"', html)
                self.assertIn("Gippsland", html)
                self.assertIn("Melbourne", html)
                self.assertIn('<select id="statusFilter"', html)
                self.assertIn("Not Yet Contacted</option>", html)
                self.assertIn("Order by", html)
                self.assertNotIn("Sort: ", html)

    def test_selected_filters_are_reflected_in_the_page(self):
        self.client.force_login(self.admin)
        html = self.client.get(
            reverse("outreach_dashboard"),
            {"type": "branch", "region": "Gippsland", "status": "contacted"},
        ).content.decode()

        self.assertIn('value="branch" selected', html)
        self.assertIn('value="Gippsland" selected', html)
        self.assertIn('value="contacted" selected', html)
