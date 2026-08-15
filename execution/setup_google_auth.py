#!/usr/bin/env python3
"""One-time Google OAuth consent for the Python tools.

Run this ONCE, from an interactive shell on this Mac, with a browser
available. It mints `token.json`, which unlocks read_sheet, update_sheet and
send_email. A webhook run cannot do this for you: the consent screen needs a
human, which is exactly why the connector-backed tools (drive_search,
drive_read, gmail_draft) exist for the unattended path.

    python execution/setup_google_auth.py            # run the consent flow
    python execution/setup_google_auth.py --check    # report status, change nothing

Exit codes: 0 authorized, 1 not (with instructions).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402

CONSOLE_STEPS = """
`credentials.json` is missing. To create it:

  1. Open https://console.cloud.google.com/ and select (or create) a project.
  2. Enable both APIs for that project:
       - Google Sheets API
       - Gmail API
     https://console.cloud.google.com/apis/library
  3. Configure the OAuth consent screen (External is fine for a personal
     account). Add yourself as a test user.
  4. Credentials -> Create credentials -> OAuth client ID
       Application type: **Desktop app**
  5. Download the JSON and save it as:
       {path}

Then run this script again. The file is gitignored and never committed.
""".strip()


def status() -> tuple[bool, str]:
    if not config.CREDENTIALS_FILE.exists():
        return False, CONSOLE_STEPS.format(path=config.CREDENTIALS_FILE)
    if not config.TOKEN_FILE.exists():
        return False, (
            f"{config.CREDENTIALS_FILE.name} is present but {config.TOKEN_FILE.name} "
            "is not. Run this script with no arguments to complete consent."
        )
    return True, f"authorized — {config.TOKEN_FILE} exists"


def verify() -> bool:
    """Prove the token actually works, rather than trusting the file exists."""
    from lib.google_auth import SCOPES, get_credentials

    creds = get_credentials()
    print(f"\n  token valid: {creds.valid}")
    print(f"  scopes: {', '.join(SCOPES)}")

    # A real call is the only honest check. Drive-free, quota-cheap.
    try:
        from lib.google_auth import gmail_service

        profile = gmail_service().users().getProfile(userId="me").execute()
        print(f"  gmail authorized as: {profile.get('emailAddress')}")
    except Exception as exc:  # noqa: BLE001 - report, do not crash setup
        print(f"  warning: token minted but a Gmail call failed: {exc}")
        return False
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="report status, change nothing")
    args = ap.parse_args()

    ok, message = status()

    if args.check:
        print(message)
        return 0 if ok else 1

    if not config.CREDENTIALS_FILE.exists():
        print(message, file=sys.stderr)
        return 1

    if ok:
        print(message)
        print("\nRe-verifying...")
        return 0 if verify() else 1

    print("Opening a browser for Google consent. Approve the requested scopes.\n")
    try:
        if verify():
            print(f"\n✓ done — wrote {config.TOKEN_FILE}")
            print("  read_sheet, update_sheet and send_email are now usable.")
            print("\n  Note: send_email SENDS. Use --dry-run while iterating, and")
            print("  prefer the gmail_draft tool for unattended webhook runs.")
            return 0
    except Exception as exc:  # noqa: BLE001 - the flow is user-facing
        print(f"\nconsent failed: {exc}", file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    sys.exit(main())
