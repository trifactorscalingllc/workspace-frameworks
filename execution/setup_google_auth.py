#!/usr/bin/env python3
"""One-time Google OAuth consent for the Python tools.

Mints `token.json`, which unlocks read_sheet, update_sheet and send_email. A
webhook run cannot do this for you: the consent screen needs a human. That is
exactly why the connector-backed tools (drive_search, drive_read, gmail_draft)
exist for the unattended path.

Two ways to consent:

  LOCAL — you are at this Mac with a browser:
      python execution/setup_google_auth.py

  REMOTE — you are on a phone or another laptop, off the LAN:
      python execution/setup_google_auth.py --remote
      # open the printed link anywhere, approve, then paste back the URL you
      # land on (it will fail to load — that is expected and fine):
      python execution/setup_google_auth.py --finish '<pasted url>'

  Status only, changes nothing:
      python execution/setup_google_auth.py --check

Exit codes: 0 authorized, 1 not (with instructions).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402

# Nothing ever listens here. For a Desktop-app client Google accepts any
# localhost port, and in the remote flow we only need the code it appends to
# the redirect — the browser landing on a dead port is the expected outcome.
REDIRECT_URI = "http://localhost:8765/"

# Short-lived PKCE/state parked between --remote and --finish. .tmp is gitignored.
PENDING_FILE = config.TMP_DIR / "oauth_pending.json"

CONSOLE_STEPS = """
`credentials.json` is missing, so there is no OAuth client yet and no consent
link can exist. Create one (this part is yours — it needs your Google account):

  1. https://console.cloud.google.com/projectcreate
     Create a project, or pick an existing one.

  2. Enable both APIs for that project:
     https://console.cloud.google.com/apis/library/sheets.googleapis.com
     https://console.cloud.google.com/apis/library/gmail.googleapis.com

  3. Configure the OAuth consent screen (External is fine for a personal
     account) and add yourself as a test user:
     https://console.cloud.google.com/apis/credentials/consent

  4. Create the client:
     https://console.cloud.google.com/apis/credentials
     -> Create credentials -> OAuth client ID
     -> Application type: **Desktop app**

  5. Download the JSON and save it on the mini as:
       {path}

Then run this script again. That file is gitignored and never committed.
""".strip()


def _flow(state: str | None = None):
    """Build an OAuth flow bound to the localhost redirect."""
    from google_auth_oauthlib.flow import Flow

    from lib.google_auth import SCOPES

    return Flow.from_client_secrets_file(
        str(config.CREDENTIALS_FILE),
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI,
        state=state,
    )


def status() -> tuple[bool, str]:
    if not config.CREDENTIALS_FILE.exists():
        return False, CONSOLE_STEPS.format(path=config.CREDENTIALS_FILE)
    if not config.TOKEN_FILE.exists():
        return False, (
            f"{config.CREDENTIALS_FILE.name} is present but {config.TOKEN_FILE.name} "
            "is not. Run with no arguments (local browser) or --remote (consent "
            "from another device)."
        )
    return True, f"authorized — {config.TOKEN_FILE} exists"


def verify() -> bool:
    """Prove the token works, rather than trusting that the file exists."""
    from lib.google_auth import SCOPES, gmail_service

    print(f"\n  scopes: {', '.join(SCOPES)}")
    try:
        profile = gmail_service().users().getProfile(userId="me").execute()
        print(f"  authorized as: {profile.get('emailAddress')}")
    except Exception as exc:  # noqa: BLE001 - report, do not crash setup
        print(f"  warning: token present but a live Gmail call failed: {exc}")
        return False
    return True


def start_remote() -> int:
    """Print a consent URL that can be opened on any device, anywhere."""
    flow = _flow()
    auth_url, state = flow.authorization_url(
        access_type="offline",
        prompt="consent",          # force a refresh token even on re-consent
        include_granted_scopes="true",
    )
    PENDING_FILE.write_text(json.dumps({"state": state, "code_verifier": flow.code_verifier}))

    print("\nOpen this link on any device and approve:\n")
    print(auth_url)
    print(
        "\nAfter you approve, the browser will try to reach "
        f"{REDIRECT_URI} and FAIL TO LOAD.\n"
        "That is expected — nothing is listening there, and on your phone that\n"
        "address means your phone. The part that matters is in the address bar.\n"
        "\nCopy the whole URL you landed on and run, back on the mini:\n"
        "\n  python execution/setup_google_auth.py --finish '<paste the url>'\n"
        "\n(If your browser hides it, the `code=` value alone is enough.)\n"
        "Treat that URL like a password until it is redeemed; it expires quickly."
    )
    return 0


def finish_remote(pasted: str) -> int:
    """Exchange the code from the pasted redirect URL for a token."""
    if not PENDING_FILE.exists():
        print(
            "no pending consent — run --remote first (the PKCE verifier from that "
            "step is required to redeem the code).",
            file=sys.stderr,
        )
        return 1

    pending = json.loads(PENDING_FILE.read_text())

    code = pasted.strip()
    if "://" in code or code.startswith("localhost") or "code=" in code:
        query = parse_qs(urlparse(code if "://" in code else f"http://{code}").query)
        if err := query.get("error"):
            print(f"Google returned an error instead of a code: {err[0]}", file=sys.stderr)
            return 1
        if not query.get("code"):
            print("no ?code= found in that URL. Paste the full redirected URL.", file=sys.stderr)
            return 1
        code = query["code"][0]

    flow = _flow(state=pending["state"])
    flow.code_verifier = pending["code_verifier"]
    try:
        # Exchange the bare code, not the URL: passing an http:// response
        # trips oauthlib's insecure-transport guard.
        flow.fetch_token(code=code)
    except Exception as exc:  # noqa: BLE001 - user-facing flow
        print(f"\ncould not redeem that code: {exc}", file=sys.stderr)
        print("Codes are single-use and short-lived — rerun --remote for a fresh link.", file=sys.stderr)
        return 1

    config.TOKEN_FILE.write_text(flow.credentials.to_json())
    PENDING_FILE.unlink(missing_ok=True)
    print(f"✓ wrote {config.TOKEN_FILE}")
    return 0 if verify() else 1


def run_local() -> int:
    """Open a browser on this Mac and consent here."""
    from lib.google_auth import get_credentials

    print("Opening a browser for Google consent. Approve the requested scopes.\n")
    try:
        get_credentials()
    except Exception as exc:  # noqa: BLE001 - user-facing flow
        print(f"\nconsent failed: {exc}", file=sys.stderr)
        return 1
    print(f"✓ wrote {config.TOKEN_FILE}")
    return 0 if verify() else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="report status, change nothing")
    ap.add_argument("--remote", action="store_true", help="print a link to approve on another device")
    ap.add_argument("--finish", metavar="URL", help="redeem the URL you landed on after approving")
    args = ap.parse_args()

    ok, message = status()

    if args.check:
        print(message)
        return 0 if ok else 1

    if not config.CREDENTIALS_FILE.exists():
        print(message, file=sys.stderr)
        return 1

    if args.finish:
        return finish_remote(args.finish)
    if args.remote:
        return start_remote()

    if ok:
        print(message + "\n\nRe-verifying...")
        return 0 if verify() else 1
    return run_local()


if __name__ == "__main__":
    sys.exit(main())
