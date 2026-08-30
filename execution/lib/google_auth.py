"""Google OAuth for the Sheets and Gmail tools.

Uses the installed-app flow. ``credentials.json`` is the client secret you
download from Google Cloud; ``token.json`` is the cached user token this module
writes after the first consent. Both are gitignored.

First run opens a browser, so do it from an interactive shell once:

    python execution/tools/read_sheet.py --sheet-id <id> --range A1:B2
"""

from __future__ import annotations

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

import config

# One token covers every tool, so keep the scope list stable — changing it forces a re-consent.
#
# gmail.readonly was added on 2026-08-15 for the cockpit's inbox panel. Adding a scope does NOT
# break the existing token: google-auth treats this list as what to *request*, and validity is
# about expiry rather than coverage, so the sheets and send tools keep working on the old grant
# until somebody re-consents. Tools that need the new scope check what was actually granted (see
# granted_scopes below) and say so, rather than dying on a 403 from deep inside the API client.
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
]

# Scopes that let a tool read mail. Any one of them is enough.
GMAIL_READ_SCOPES = (
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://mail.google.com/",
)


def granted_scopes() -> list[str]:
    """What token.json was actually consented to — not what SCOPES asks for."""
    import json

    if not config.TOKEN_FILE.exists():
        return []
    try:
        return json.loads(config.TOKEN_FILE.read_text()).get("scopes", []) or []
    except (json.JSONDecodeError, OSError):
        return []


def can_read_gmail() -> bool:
    return any(s in GMAIL_READ_SCOPES for s in granted_scopes())


def get_credentials() -> Credentials:
    creds: Credentials | None = None

    if config.TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(config.TOKEN_FILE), SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        if not config.CREDENTIALS_FILE.exists():
            raise RuntimeError(
                f"{config.CREDENTIALS_FILE} not found. Download an OAuth client "
                "(Desktop app) from Google Cloud and save it there."
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(config.CREDENTIALS_FILE), SCOPES)
        creds = flow.run_local_server(port=0)

    config.TOKEN_FILE.write_text(creds.to_json())
    return creds


def sheets_service():
    return build("sheets", "v4", credentials=get_credentials(), cache_discovery=False)


def gmail_service():
    return build("gmail", "v1", credentials=get_credentials(), cache_discovery=False)
