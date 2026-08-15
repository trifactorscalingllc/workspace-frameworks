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

# One token covers both tools, so keep the scope list stable — changing it
# invalidates token.json and forces a re-consent.
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/gmail.send",
]


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
