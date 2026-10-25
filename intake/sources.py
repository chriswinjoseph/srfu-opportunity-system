"""
The approved public sources the scraper may use.

Adapters are configured explicitly. Only the organisation types and
locations an adapter declares are offered; anything else is reported as
unsupported rather than invented. Adapters extract only what a public page
displays and never guess a missing value.
"""

import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

from outreach.management.commands.scrape_banks import (
    PUBLIC_BRANCH_URLS,
    clean_text,
    extract_phone,
    extract_state,
)
from outreach.management.commands.scrape_clubs import (
    DIRECTORY_URL,
    extract_suburb,
    parse_clubs,
)

from .normalise import norm_name

ORG_TYPE_LABELS = {"bank": "Bank", "branch": "Branch", "club": "Club"}
ALL_STATES = ("ACT", "NSW", "NT", "QLD", "SA", "TAS", "VIC", "WA")


@dataclass
class Page:
    url: str
    label: str = ""


@dataclass
class ParseOutcome:
    records: list = field(default_factory=list)
    problem: str = ""
    code: str = "unrecognised"


class Adapter:
    key = ""
    label = ""
    org_type = ""
    states = ()
    suburbs = ()  # supported suburb filter values (optional)
    description = ""
    allowed_hosts = ()
    # A restriction found when the source was last checked (shown before queueing).
    known_limitation = ""

    def pages(self, states=(), suburbs=()):
        raise NotImplementedError

    def parse(self, page, html):
        raise NotImplementedError


class BendigoCommunityBanks(Adapter):
    key = "bendigo_community_banks"
    label = "Bendigo Bank Community Bank branch pages"
    org_type = "bank"
    states = ("VIC",)
    description = (
        "Confirmed public Community Bank pages on bendigobank.com.au "
        "(Victoria). Collects the name, state, public phone and page address."
    )
    allowed_hosts = ("www.bendigobank.com.au", "bendigobank.com.au")

    def pages(self, states=(), suburbs=()):
        if states and "VIC" not in states:
            return []

        return [Page(url, "Community Bank page") for url in PUBLIC_BRANCH_URLS.get("Victoria", [])]

    def parse(self, page, html):
        soup = BeautifulSoup(html, "html.parser")

        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()

        text = clean_text(soup.get_text(" ", strip=True))
        heading = soup.find("h1")
        name = clean_text(heading.get_text(" ", strip=True)) if heading else ""

        if not name:
            return ParseOutcome(problem="The page has no organisation name, so nothing was collected.")

        if "community bank" not in name.lower():
            return ParseOutcome(problem="The page is not recognised as a Community Bank page.")

        state = extract_state(text, page.url)
        phone = extract_phone(text)
        fields = ["name", "website", "source_url"]

        if state:
            fields.append("state")

        if phone:
            fields.append("phone")

        return ParseOutcome(
            records=[
                {
                    "name": name,
                    "state": state,
                    "phone": phone,
                    "website": page.url,
                    "source_url": page.url,
                    "source_org_id": page.url,
                    "collected_fields": fields,
                }
            ]
        )


class MooneeValleyClubs(Adapter):
    key = "mvcc_sports_clubs"
    label = "Moonee Valley City Council sports club directory"
    org_type = "club"
    states = ("VIC",)
    suburbs = (
        "Aberfeldie", "Airport West", "Ascot Vale", "Avondale Heights",
        "Essendon", "Flemington", "Moonee Ponds", "Niddrie",
        "Strathmore", "Travancore",
    )
    description = (
        "The council's public sports club directory (Victoria). Collects "
        "the club name, sport, suburb, postcode, public email, phone and website."
    )
    allowed_hosts = ("mvcc.vic.gov.au", "www.mvcc.vic.gov.au")
    known_limitation = (
        "When last checked (23 October 2026) this website answered with an automated-access check "
        "instead of the directory, so nothing could be collected. The check is not bypassed. "
        "Clubs need a permitted source or the council's permission."
    )

    def pages(self, states=(), suburbs=()):
        if states and "VIC" not in states:
            return []

        return [Page(DIRECTORY_URL, "Sports club directory")]

    def parse(self, page, html):
        clubs = parse_clubs(html)

        if not clubs:
            return ParseOutcome(problem="The directory page loaded but listed no clubs.", code="no_records")

        records = []

        for club in clubs:
            fields = ["name", "state", "source_url"]

            for source_key, label in (
                ("club_type", "club_type"), ("suburb", "suburb"), ("postcode", "postcode"),
                ("public_email", "email"), ("public_phone", "phone"), ("website_url", "website"),
            ):
                if club.get(source_key):
                    fields.append(label)

            records.append(
                {
                    "name": club["club_name"],
                    "club_type": club.get("club_type", ""),
                    "state": "VIC",
                    "suburb": club.get("suburb", ""),
                    "postcode": club.get("postcode", ""),
                    "email": club.get("public_email", ""),
                    "phone": club.get("public_phone", ""),
                    "website": club.get("website_url", ""),
                    "source_url": page.url,
                    "source_org_id": f"{page.url}#{norm_name(club['club_name']).replace(' ', '-')}",
                    "collected_fields": fields,
                }
            )

        return ParseOutcome(records=records)


ADAPTERS = {
    adapter.key: adapter
    for adapter in (BendigoCommunityBanks(), MooneeValleyClubs())
}


def supported_org_types():
    return sorted({a.org_type for a in ADAPTERS.values()})


def supported_states():
    return sorted({s for a in ADAPTERS.values() for s in a.states})


def supported_suburbs():
    return sorted({s for a in ADAPTERS.values() for s in a.suburbs})


def plan_coverage(org_types, states, suburbs=()):
    """
    ``(adapters, unsupported)``: the adapters that can serve the request,
    and plain-language notes for anything no approved source covers.
    """
    org_types = [t for t in org_types if t in ORG_TYPE_LABELS] or list(ORG_TYPE_LABELS)
    states = [s.upper() for s in states if s]
    unsupported = []
    chosen = []

    for org_type in org_types:
        candidates = [a for a in ADAPTERS.values() if a.org_type == org_type]

        if not candidates:
            unsupported.append(
                f"{ORG_TYPE_LABELS[org_type]}: no approved public source is configured, so none were collected."
            )
            continue

        for adapter in candidates:
            if states and not set(states) & set(adapter.states):
                unsupported.append(
                    f"{ORG_TYPE_LABELS[org_type]} in {', '.join(states)}: the approved source "
                    f"covers {', '.join(adapter.states)} only."
                )
                continue

            if suburbs and not adapter.suburbs:
                unsupported.append(
                    f"{ORG_TYPE_LABELS[org_type]}: the suburb filter is not supported by its source "
                    "and was not applied."
                )

            chosen.append(adapter)
            missing = sorted(set(states) - set(adapter.states))

            if missing:
                unsupported.append(
                    f"{ORG_TYPE_LABELS[org_type]} in {', '.join(missing)}: the approved source "
                    f"covers {', '.join(adapter.states)} only."
                )

    return chosen, unsupported
