"""
BOUNDED LIVE SCRAPER CHECK settings (verification mode plus named public hosts).

Everything in verification_settings.py still applies: separate disposable database, email written
to files, a local stand-in for the AI, and no network except this computer. The ONLY addition is
that connections to the hosts you name in SRFU_LIVE_ALLOW_HOSTS are permitted, and each named host
must be one of the four approved scraper sources. SMTP servers, OpenAI and every other address stay blocked.

    $env:SRFU_LIVE_ALLOW_HOSTS = "www.bendigobank.com.au,bendigobank.com.au"
    $env:DJANGO_SETTINGS_MODULE = "live_scrape_check_settings"

The application's own fetcher still enforces HTTPS, the approved-host list, robots.txt, a pause between
requests, size and time limits, and it never bypasses a bot check. Use only with a disposable database and
only with a worker run of the form  python manage.py run_intake_worker --once.
"""

import os
import socket
import sys

import verification_settings as _v
from verification_settings import *  # noqa: F401,F403

APPROVED_SCRAPER_HOSTS = {
    "www.bendigobank.com.au",
    "bendigobank.com.au",
    "mvcc.vic.gov.au",
    "www.mvcc.vic.gov.au",
}

_hosts = [h.strip().lower() for h in os.environ.get("SRFU_LIVE_ALLOW_HOSTS", "").split(",") if h.strip()]

if not _hosts:
    raise RuntimeError("live_scrape_check_settings: set SRFU_LIVE_ALLOW_HOSTS to the approved host(s) to reach.")

_unapproved = [h for h in _hosts if h not in APPROVED_SCRAPER_HOSTS]

if _unapproved:
    raise RuntimeError(f"live_scrape_check_settings: not an approved scraper host: {', '.join(_unapproved)}")

for _host in _hosts:
    for _info in socket.getaddrinfo(_host, 443):
        _v._LOCAL.add(_info[4][0])

print(
    "LIVE SCRAPE CHECK: network allowed only to " + ", ".join(_hosts) + " (plus this computer); "
    "email -> files, AI = stand-in",
    file=sys.stdout,
)
