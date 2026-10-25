"""
VERIFICATION-ONLY Django settings for independent testing (BA, reviewers).

NOT for real use. It sits OUTSIDE the project repository and changes only:

  * the database file      -> the path in SRFU_VERIFY_DB (required; never db.sqlite3 by accident)
  * outgoing email         -> written to files in SRFU_VERIFY_MAIL_DIR (required; nothing is sent)
  * the OpenAI client      -> a local stand-in that returns a synthetic email (no AI call, no cost)
  * the network            -> any connection to a non-local address is refused, so live email,
                              live AI and live scraping cannot happen even by mistake

Usage (PowerShell, from the project folder, with the project's virtual environment active):

    $env:PYTHONPATH           = "<folder containing this file>"
    $env:SRFU_VERIFY_DB       = "D:\\verify\\verify.sqlite3"
    $env:SRFU_VERIFY_MAIL_DIR = "D:\\verify\\mail"
    python manage.py migrate --settings=verification_settings

Optional: SRFU_VERIFY_AI_WORDS = length of the synthetic AI email in words (default 100, minimum 20).
The network guard also stops the scraper from reaching any public site.
"""

import json
import os
import re
import socket
import sys
from types import SimpleNamespace

from srfu.settings import *  # noqa: F401,F403  (project settings, then the overrides below)


def _required(name):
    value = os.environ.get(name, "").strip()

    if not value:
        raise RuntimeError(
            f"verification_settings: set the environment variable {name} first. "
            "This mode refuses to guess a database or mail folder."
        )

    return value


# ---- database and email -------------------------------------------------------------
DATABASES["default"]["NAME"] = _required("SRFU_VERIFY_DB")  # noqa: F405
EMAIL_BACKEND = "django.core.mail.backends.filebased.EmailBackend"
EMAIL_FILE_PATH = _required("SRFU_VERIFY_MAIL_DIR")
os.makedirs(EMAIL_FILE_PATH, exist_ok=True)
EMAIL_HOST = ""
OPENAI_API_KEY = "verification-only-not-a-real-key"
ALLOWED_HOSTS = ["127.0.0.1", "localhost", "testserver"]

# ---- no network except this machine -----------------------------------------------------
_LOCAL = {"127.0.0.1", "::1", "localhost"}
_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex


def _blocked(address):
    host = address[0] if isinstance(address, tuple) else address
    return str(host) not in _LOCAL


def _guarded_connect(self, address, *args, **kwargs):
    if self.family != getattr(socket, "AF_UNIX", -1) and _blocked(address):
        raise OSError(f"verification_settings: connection to {address[0]!r} blocked (local only)")

    return _real_connect(self, address, *args, **kwargs)


def _guarded_connect_ex(self, address, *args, **kwargs):
    if self.family != getattr(socket, "AF_UNIX", -1) and _blocked(address):
        return 10061

    return _real_connect_ex(self, address, *args, **kwargs)


socket.socket.connect = _guarded_connect
socket.socket.connect_ex = _guarded_connect_ex


# ---- local stand-in for the OpenAI client -----------------------------------------------
def _section(text, begin, end):
    match = re.search(re.escape(begin) + r"\s*(\{.*?\})\s*" + re.escape(end), text, re.S)

    return json.loads(match.group(1)) if match else {}


class _FakeResponses:
    def parse(self, model=None, input=None, text_format=None, **kwargs):
        prompt = " ".join(str(m.get("content", "")) for m in (input or []))
        data = _section(prompt, "BEGIN VERIFIED ORGANISATION DATA", "END VERIFIED ORGANISATION DATA")
        config = _section(prompt, "BEGIN APPROVED EMAIL CONFIGURATION", "END APPROVED EMAIL CONFIGURATION")
        name = data.get("organisation_name") or "team"
        contact = (data.get("contact_name") or "").strip()
        greeting = f"Hello {contact}," if contact else f"Hello {name} team,"
        signature = (config.get("signature") or "SYNTHETIC SENDER").strip()
        target = max(int(os.environ.get("SRFU_VERIFY_AI_WORDS", "100")), 20)
        head = f"{greeting}\n\nThis is a synthetic verification email, not real outreach."
        tail = f"\n\nPlease let us know if you would like to talk.\n\nKind regards,\n{signature}"
        needed = max(target - len((head + tail).split()), 0)
        filler = " ".join((["Synthetic verification text."] * (needed // 3 + 1)))
        filler = " ".join(filler.split()[:needed])
        body = head + (" " + filler if filler else "") + tail

        return SimpleNamespace(
            output_parsed=text_format(subject="Synthetic verification email", body=body),
            usage=SimpleNamespace(input_tokens=0, output_tokens=0, total_tokens=0),
        )


class _FakeOpenAI:
    def __init__(self, *args, **kwargs):
        self.responses = _FakeResponses()


import openai  # noqa: E402  (must be patched before outreach.services imports it)

openai.OpenAI = _FakeOpenAI

print(
    "VERIFICATION MODE: database=%s, email -> files in %s, AI = local stand-in, network = local only"
    % (DATABASES["default"]["NAME"], EMAIL_FILE_PATH),  # noqa: F405
)
