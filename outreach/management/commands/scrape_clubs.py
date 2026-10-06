"""
Collect publicly available sports club information from
Moonee Valley City Council's public sports club directory.

Test:
    python manage.py scrape_clubs --limit 5 --dry-run

Real import:
    python manage.py scrape_clubs
"""

import re

import requests
from bs4 import BeautifulSoup

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email

from outreach.models import Club


DIRECTORY_URL = (
    "https://mvcc.vic.gov.au/"
    "live/my-neighbourhood/local-sports-clubs/"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/120 Safari/537.36"
    )
}


SPORT_TYPES = {
    "AFL": "AFL",
    "Aquatic": "Aquatic",
    "Athletics": "Athletics",
    "Backgammon": "Backgammon",
    "Baseball": "Baseball",
    "Basketball": "Basketball",
    "Boules and mallet": "Bowls / Mallet",
    "Canoeing": "Canoeing",
    "Cricket": "Cricket",
    "Dog Obedience Clubs": "Dog Obedience",
    "Fishing and Angling": "Fishing",
    "Hockey": "Hockey",
    "Martial Arts": "Martial Arts",
    "Netball": "Netball",
    "Racing": "Racing",
    "Rowing": "Rowing",
    "Rugby League": "Rugby League",
    "Soccer": "Soccer",
    "Squash": "Squash",
    "Tennis": "Tennis",
}


SUBURBS = [
    "Ascot Vale",
    "Aberfeldie",
    "Airport West",
    "Avondale Heights",
    "Essendon",
    "Essendon North",
    "Essendon West",
    "Flemington",
    "Keilor East",
    "Keilor Park",
    "Maribyrnong",
    "Moonee Ponds",
    "Strathmore",
    "Strathmore Heights",
]


def clean_text(value):
    if value is None:
        return ""

    return " ".join(str(value).split()).strip()


def extract_email(text):
    match = re.search(
        r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
        text or "",
    )

    if not match:
        return ""

    email = match.group(0)

    try:
        validate_email(email)
        return email
    except ValidationError:
        return ""


def extract_phone(text):
    patterns = [
        r"\(0\d\)\s*\d{4}\s*\d{4}",
        r"0\d\s*\d{4}\s*\d{4}",
        r"04\d{2}\s*\d{3}\s*\d{3}",
        r"1[38]00\s*\d{3}\s*\d{3}",
    ]

    for pattern in patterns:
        match = re.search(pattern, text or "")

        if match:
            return clean_text(match.group(0))

    return ""


def extract_postcode(text):
    match = re.search(
        r"\b3\d{3}\b",
        text or "",
    )

    if match:
        return match.group(0)

    return ""


def extract_suburb(text):
    lower_text = (text or "").lower()

    for suburb in SUBURBS:
        if suburb.lower() in lower_text:
            return suburb

    return ""


def fetch_directory():
    try:
        response = requests.get(
            DIRECTORY_URL,
            headers=HEADERS,
            timeout=15,
        )

        response.raise_for_status()

        return response.text

    except requests.RequestException as exc:
        raise ValueError(
            f"Could not access club directory: {exc}"
        )


def get_website_map(soup):
    """
    Build a map:
        club name -> public website URL
    """

    websites = {}

    for link in soup.find_all("a", href=True):
        name = clean_text(
            link.get_text(" ", strip=True)
        )

        href = clean_text(
            link.get("href")
        )

        if not name or not href:
            continue

        if href.startswith("http"):
            websites[name.lower()] = href

    return websites


def parse_clubs(html):
    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    clubs = []
    seen = set()
    current_sport = ""

    sport_names = {
        "AFL",
        "Aquatic",
        "Athletics",
        "Backgammon",
        "Baseball",
        "Basketball",
        "Boules and mallet",
        "Canoeing",
        "Cricket",
        "Dog Obedience Clubs",
        "Fishing and Angling",
        "Hockey",
        "Martial Arts",
        "Netball",
        "Racing",
        "Rowing",
        "Rugby League",
        "Soccer",
        "Squash",
        "Tennis",
    }

    # Walk through visible page elements in order
    elements = soup.find_all(
        ["h2", "h3", "a", "p"]
    )

    for index, element in enumerate(elements):
        text = clean_text(
            element.get_text(
                " ",
                strip=True,
            )
        )

        if not text:
            continue

        # Category headings
        clean_category = text.replace(
            " Expand",
            "",
        ).strip()

        if clean_category in sport_names:
            current_sport = clean_category
            continue

        # Club names are usually links
        if element.name != "a":
            continue

        href = clean_text(
            element.get("href")
        )

        if not href:
            continue

        club_name = text

        # Ignore navigation links
        if (
            len(club_name) < 4
            or club_name.lower()
            in {
                "contact",
                "email",
                "website",
                "read more",
            }
        ):
            continue

        # Look at text immediately after this link
        details = []

        next_node = element.next_sibling

        count = 0

        while next_node is not None and count < 20:
            if hasattr(next_node, "get_text"):
                next_text = clean_text(
                    next_node.get_text(
                        " ",
                        strip=True,
                    )
                )
            else:
                next_text = clean_text(
                    str(next_node)
                )

            if next_text:
                details.append(
                    next_text
                )

            next_node = next_node.next_sibling
            count += 1

        # Fallback: use parent text
        if not details:
            parent = element.parent

            if parent:
                details.append(
                    clean_text(
                        parent.get_text(
                            " ",
                            strip=True,
                        )
                    )
                )

        details_text = " ".join(
            details
        )

        # A real club entry should normally have
        # Address, Email or Phone information nearby.
        if not any(
            label in details_text
            for label in [
                "Address:",
                "Email:",
                "Phone:",
            ]
        ):
            continue

        email = extract_email(
            details_text
        )

        phone = extract_phone(
            details_text
        )

        postcode = extract_postcode(
            details_text
        )

        suburb = extract_suburb(
            details_text
        )

        key = club_name.lower()

        if key in seen:
            continue

        seen.add(key)

        clubs.append(
            {
                "club_name": club_name,
                "club_type": current_sport,
                "suburb": suburb,
                "state": "VIC",
                "postcode": postcode,
                "region": "Victoria",
                "website_url": href
                if href.startswith("http")
                else "",
                "public_email": email,
                "public_phone": phone,
            }
        )

    return clubs


class Command(BaseCommand):
    help = (
        "Collect public sports club information "
        "from Moonee Valley City Council."
    )

    def add_arguments(
        self,
        parser,
    ):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help=(
                "Validate without writing "
                "to the database."
            ),
        )

        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Optional number of clubs to process.",
        )

    def handle(
        self,
        *args,
        **options,
    ):
        dry_run = options["dry_run"]
        limit = options["limit"]

        if limit is not None and limit < 1:
            raise CommandError(
                "--limit must be greater than 0."
            )

        self.stdout.write(
            "Collecting public club data "
            "from Moonee Valley City Council..."
        )

        try:
            html = fetch_directory()
            clubs = parse_clubs(html)

        except ValueError as exc:
            raise CommandError(
                f"Collection failed: {exc}"
            )

        if not clubs:
            raise CommandError(
                "No clubs were detected on the directory page."
            )

        if limit:
            clubs = clubs[:limit]

        created_count = 0
        duplicate_count = 0
        skipped_count = 0

        for entry in clubs:
            club_name = clean_text(
                entry["club_name"]
            )

            suburb = clean_text(
                entry["suburb"]
            )

            state = clean_text(
                entry["state"]
            )

            if not club_name:
                skipped_count += 1
                continue

            duplicate_query = (
                Club.objects.filter(
                    club_name__iexact=club_name
                )
            )

            if suburb:
                duplicate_query = (
                    duplicate_query.filter(
                        suburb__iexact=suburb
                    )
                )

            if state:
                duplicate_query = (
                    duplicate_query.filter(
                        state__iexact=state
                    )
                )

            if duplicate_query.exists():
                duplicate_count += 1

                self.stdout.write(
                    self.style.WARNING(
                        f"'{club_name}' already exists — skipped."
                    )
                )

                continue

            if dry_run:
                created_count += 1

                self.stdout.write(
                    self.style.SUCCESS(
                        f"Would create: "
                        f"{club_name} | "
                        f"{entry['club_type']} | "
                        f"{suburb} | "
                        f"{entry['public_email']}"
                    )
                )

                continue

            Club.objects.create(
                club_name=club_name,
                club_type=entry["club_type"],
                suburb=suburb,
                state=state,
                postcode=entry["postcode"],
                region="Victoria",
                website_url=entry["website_url"],
                public_email=entry["public_email"],
                public_phone=entry["public_phone"],
                contact_status="not_yet_contacted",
                record_source=(
                    "Public Web - Moonee Valley City Council"
                ),
            )

            created_count += 1

            self.stdout.write(
                self.style.SUCCESS(
                    f"Created '{club_name}'"
                )
            )

        self.stdout.write("")

        self.stdout.write(
            self.style.SUCCESS(
                f"New clubs: {created_count}"
            )
        )

        self.stdout.write(
            self.style.WARNING(
                f"Duplicates skipped: "
                f"{duplicate_count}"
            )
        )

        self.stdout.write(
            f"Invalid/skipped records: "
            f"{skipped_count}"
        )

        if dry_run:
            self.stdout.write(
                self.style.NOTICE(
                    "Dry run only — nothing was written "
                    "to the database."
                )
            )