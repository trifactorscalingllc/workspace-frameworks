#!/usr/bin/env python3
"""One-time Instagram Graph API setup, and the token check you rerun later.

    python execution/setup_meta_auth.py --check                 # what's missing
    python execution/setup_meta_auth.py --exchange <short-token> # make it long-lived
    python execution/setup_meta_auth.py --discover               # find the IG account id

Writes META_ACCESS_TOKEN, META_TOKEN_EXPIRES and IG_USER_ID into `.env`.

Long-lived tokens last ~60 days. That is the trap: everything works for two
months and then every run fails at once. `--check` prints the days remaining so
it is visible before it bites; re-run `--exchange` with a fresh short-lived
token to extend.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402
from lib.meta import GRAPH_VERSION, MetaError, get, token_days_left  # noqa: E402

CONSOLE_STEPS = f"""
Instagram is not connected yet. This needs ~10 minutes in the Meta console, and
the account must be an Instagram **Business or Creator** account linked to a
Facebook Page (a personal IG account cannot use this API at all).

  1. https://developers.facebook.com/apps/  ->  Create app  ->  type "Business"

  2. In the app, add the product **Instagram Graph API**
     (older UI calls it "Instagram" -> "Instagram Graph API")

  3. Settings -> Basic: copy the **App ID** and **App Secret**

  4. https://developers.facebook.com/tools/explorer/
     - pick your app, top right
     - "Generate Access Token", granting these permissions:
         instagram_basic
         instagram_manage_insights
         pages_show_list
         pages_read_engagement
     - copy the token it shows (this one is short-lived, ~1 hour — that is fine)

  5. Put the App ID and App Secret in {config.ENV_FILE}:
         META_APP_ID=...
         META_APP_SECRET=...

  6. Then run, with the token from step 4:
         python execution/setup_meta_auth.py --exchange '<short-lived-token>'

That exchanges it for a ~60 day token, finds your Instagram account id, and
writes both to .env. Nothing else to do afterwards.
""".strip()


def write_env(values: dict[str, str]) -> None:
    """Set or replace keys in .env, leaving everything else untouched."""
    text = config.ENV_FILE.read_text() if config.ENV_FILE.exists() else ""
    for key, value in values.items():
        line = f"{key}={value}"
        if re.search(rf"^{key}=.*$", text, re.M):
            text = re.sub(rf"^{key}=.*$", line, text, flags=re.M)
        else:
            text = text.rstrip("\n") + f"\n{line}\n"
    config.ENV_FILE.write_text(text)
    config.ENV_FILE.chmod(0o600)


def exchange(short_token: str) -> int:
    app_id = config.get("META_APP_ID", "")
    app_secret = config.get("META_APP_SECRET", "")
    if not (app_id and app_secret):
        print("META_APP_ID and META_APP_SECRET must be in .env first "
              "(step 5 of --check).", file=sys.stderr)
        return 1

    try:
        data = get("oauth/access_token", {
            "grant_type": "fb_exchange_token",
            "client_id": app_id,
            "client_secret": app_secret,
            "fb_exchange_token": short_token,
        }, access_token="")
    except MetaError as exc:
        print(f"exchange failed: {exc}", file=sys.stderr)
        return 1

    long_token = data.get("access_token")
    if not long_token:
        print(f"no access_token in response: {data}", file=sys.stderr)
        return 1

    seconds = int(data.get("expires_in", 60 * 24 * 3600))
    expires = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    write_env({
        "META_ACCESS_TOKEN": long_token,
        "META_TOKEN_EXPIRES": expires.isoformat(timespec="seconds"),
    })
    print(f"✓ long-lived token stored, valid ~{seconds // 86400} days "
          f"(until {expires.date()})")

    config.load_dotenv(config.ENV_FILE, override=True)
    return discover(token_override=long_token)


def discover(token_override: str | None = None) -> int:
    """Find the Instagram Business account behind the connected Page."""
    try:
        pages = get("me/accounts", {
            "fields": "name,instagram_business_account{id,username}"
        }, access_token=token_override)
    except MetaError as exc:
        print(f"could not list Pages: {exc}", file=sys.stderr)
        return 1

    linked = [
        (p["name"], p["instagram_business_account"])
        for p in pages.get("data", [])
        if p.get("instagram_business_account")
    ]
    if not linked:
        print(
            "No Instagram Business account is linked to any Page this token can see.\n"
            "Fix in the Instagram app: Settings -> Account type -> switch to Business\n"
            "or Creator, and link it to a Facebook Page. Then rerun --discover.",
            file=sys.stderr,
        )
        return 1
    if len(linked) > 1:
        print("Several linked accounts found — set IG_USER_ID in .env by hand:")
        for name, ig in linked:
            print(f"  {ig['id']}  @{ig.get('username')}   (Page: {name})")
        return 1

    page_name, ig = linked[0]
    write_env({"IG_USER_ID": ig["id"]})
    print(f"✓ Instagram account: @{ig.get('username')} (id {ig['id']}, Page: {page_name})")
    return 0


def check() -> int:
    have = {k: bool(config.get(k, "")) for k in
            ("META_APP_ID", "META_APP_SECRET", "META_ACCESS_TOKEN", "IG_USER_ID")}
    if not any(have.values()):
        print(CONSOLE_STEPS)
        return 1

    print(f"Graph API {GRAPH_VERSION}\n")
    for key, present in have.items():
        print(f"  {'✓' if present else '✗'} {key}")

    if not have["META_ACCESS_TOKEN"]:
        print("\nNext: run --exchange with a short-lived token from the Graph API Explorer.")
        return 1

    if (days := token_days_left()) is not None:
        flag = "✓" if days > 14 else "!"
        print(f"\n  {flag} token expires in {days} days")
        if days <= 14:
            print("    Re-run --exchange with a fresh short-lived token to extend.")

    try:
        me = get(f"{config.get('IG_USER_ID')}", {"fields": "username,media_count"})
        print(f"\n  live check: @{me.get('username')} — {me.get('media_count')} posts")
    except MetaError as exc:
        print(f"\n  ✗ live check failed: {exc}")
        return 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--exchange", metavar="SHORT_TOKEN")
    ap.add_argument("--discover", action="store_true")
    args = ap.parse_args()

    if args.exchange:
        return exchange(args.exchange.strip())
    if args.discover:
        return discover()
    return check()


if __name__ == "__main__":
    sys.exit(main())
