"""
A small, polite fetcher for approved public pages only.

* an honest user-agent;
* only HTTPS pages on the hosts an adapter explicitly allows (also after
  redirects);
* robots.txt is respected;
* bounded time and size, with a pause between requests;
* pages that need a login are not collected and no access control is
  bypassed.
"""

import logging
import time
from dataclasses import dataclass
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests

logger = logging.getLogger("intake.fetch")

USER_AGENT = (
    "SafeRoadsForUsCollector/1.0 "
    "(public organisation information only; Safe Roads For Us outreach project)"
)
CONNECT_TIMEOUT = 5
READ_TIMEOUT = 15
MAX_BYTES = 2_000_000
LOGIN_HINTS = ("/login", "/signin", "/sign-in", "/log-in", "/account/login", "/sso")

SAFE_MESSAGES = {
    "blocked_host": "The address is not on the approved list of public sources.",
    "robots": "The website's robots rules do not allow this page to be collected.",
    "login_required": "The page requires a login, so nothing was collected from it.",
    "forbidden": "The page is not publicly available, so nothing was collected from it.",
    "not_found": "The page could not be found.",
    "http_error": "The public source returned an error for this page.",
    "timeout": "The public source took too long to respond.",
    "unreachable": "Unable to access the public source.",
    "too_large": "The page was too large to process.",
    "bot_challenge": (
        "The website answered with an automated-access check instead of the page, so nothing was collected. "
        "The check is not bypassed; ask the site owner for permission or another public source."
    ),
}
CHALLENGE_MARKERS = ("_incapsula_resource", "captcha", "cf-chl", "challenge-platform", "request unsuccessful")


@dataclass
class FetchResult:
    ok: bool
    url: str
    status: int = 0
    text: str = ""
    code: str = ""

    @property
    def message(self):
        return SAFE_MESSAGES.get(self.code, "")


class PublicFetcher:
    def __init__(self, session=None, *, allowed_hosts=(), delay=0.5,
                 sleep=time.sleep, respect_robots=True):
        self.session = session or requests.Session()
        self.allowed_hosts = {h.lower() for h in allowed_hosts}
        self.delay = delay
        self.sleep = sleep
        self.respect_robots = respect_robots
        self._robots = {}
        self._last_request = None

    # ------------------------------------------------------------ helpers
    def _host_ok(self, url):
        parsed = urlparse(url)

        return parsed.scheme == "https" and parsed.hostname and parsed.hostname.lower() in self.allowed_hosts

    def _pause(self):
        if self.delay and self._last_request is not None:
            self.sleep(self.delay)

        self._last_request = True

    def _robots_allows(self, url):
        if not self.respect_robots:
            return True

        parsed = urlparse(url)
        host = parsed.hostname.lower()

        if host not in self._robots:
            parser = RobotFileParser()
            verdict = "allow"

            try:
                self._pause()
                response = self.session.get(
                    f"https://{host}/robots.txt",
                    headers={"User-Agent": USER_AGENT},
                    timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
                )
                status = getattr(response, "status_code", 200)

                if status == 200:
                    parser.parse((getattr(response, "text", "") or "").splitlines())
                    verdict = parser
                elif status >= 500:
                    verdict = "deny"
            except Exception:
                logger.warning("robots.txt could not be read for %s", host)
                verdict = "deny"

            self._robots[host] = verdict

        verdict = self._robots[host]

        if verdict == "allow":
            return True

        if verdict == "deny":
            return False

        return verdict.can_fetch(USER_AGENT, url)

    # --------------------------------------------------------------- fetch
    def get(self, url):
        if not self._host_ok(url):
            return FetchResult(False, url, code="blocked_host")

        if not self._robots_allows(url):
            return FetchResult(False, url, code="robots")

        try:
            self._pause()
            response = self.session.get(
                url,
                headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
                timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
                stream=True,
                allow_redirects=True,
            )
        except requests.Timeout:
            return FetchResult(False, url, code="timeout")
        except Exception:
            logger.warning("Fetch failed for %s", url, exc_info=True)

            return FetchResult(False, url, code="unreachable")

        final_url = getattr(response, "url", url) or url
        status = getattr(response, "status_code", 0)

        if not self._host_ok(final_url):
            return FetchResult(False, url, status, code="blocked_host")

        path = urlparse(final_url).path.lower()

        if status == 401 or any(hint in path for hint in LOGIN_HINTS):
            return FetchResult(False, url, status, code="login_required")

        if status == 403:
            return FetchResult(False, url, status, code="forbidden")

        if status == 404:
            return FetchResult(False, url, status, code="not_found")

        if status >= 400:
            return FetchResult(False, url, status, code="http_error")

        chunks, size = [], 0

        try:
            for chunk in response.iter_content(chunk_size=65536):
                size += len(chunk)

                if size > MAX_BYTES:
                    return FetchResult(False, url, status, code="too_large")

                chunks.append(chunk)
        except Exception:
            return FetchResult(False, url, status, code="unreachable")

        body = b"".join(chunks)
        encoding = getattr(response, "encoding", None) or "utf-8"
        text = body.decode(encoding, errors="replace")

        # A tiny page that only carries a bot-protection script is not the real page.
        if len(text) < 3000 and any(marker in text.lower() for marker in CHALLENGE_MARKERS):
            return FetchResult(False, url, status, code="bot_challenge")

        return FetchResult(True, final_url, status, text)
