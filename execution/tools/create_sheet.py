#!/usr/bin/env python3
"""Create a Google Sheet and print its id and URL as JSON.

Exists because a weekly deliverable should not need a human to pre-create the
file. `update_sheet.py` can only write into a spreadsheet that already exists.

    python execution/tools/create_sheet.py --title 'TFS Content — Week 2' \
        --tab Plan --headers-json '["Date","Day","Post at"]'

    # refuse to make a second copy if one with this title already exists
    python execution/tools/create_sheet.py --title '...' --if-missing
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.google_auth import sheets_service  # noqa: E402


def find_existing(title: str) -> str | None:
    """Sheets API cannot search by name; Drive can, but we only hold the
    spreadsheets scope. So this is best-effort and only used by --if-missing."""
    try:
        from lib.google_auth import get_credentials
        from googleapiclient.discovery import build

        drive = build("drive", "v3", credentials=get_credentials(), cache_discovery=False)
        resp = drive.files().list(
            q=f"name = '{title}' and mimeType = 'application/vnd.google-apps.spreadsheet'"
               " and trashed = false",
            fields="files(id)", pageSize=1,
        ).execute()
        files = resp.get("files", [])
        return files[0]["id"] if files else None
    except Exception:  # noqa: BLE001 - no Drive scope is the normal case
        return None


def create(title: str, tab: str, headers: list[str]) -> dict:
    svc = sheets_service()
    body = {"properties": {"title": title}}
    if tab:
        body["sheets"] = [{"properties": {"title": tab}}]
    resp = svc.spreadsheets().create(body=body).execute()
    sid = resp["spreadsheetId"]
    first = resp["sheets"][0]["properties"]
    tab_name = first["title"]

    if headers:
        svc.spreadsheets().values().update(
            spreadsheetId=sid, range=f"{tab_name}!A1",
            valueInputOption="USER_ENTERED", body={"values": [headers]},
        ).execute()
        # Freeze and bold row 1 so a human can actually use the thing.
        svc.spreadsheets().batchUpdate(spreadsheetId=sid, body={"requests": [
            {"updateSheetProperties": {
                "properties": {"sheetId": first["sheetId"],
                               "gridProperties": {"frozenRowCount": 1}},
                "fields": "gridProperties.frozenRowCount"}},
            {"repeatCell": {
                "range": {"sheetId": first["sheetId"], "startRowIndex": 0, "endRowIndex": 1},
                "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                "fields": "userEnteredFormat.textFormat.bold"}},
        ]}).execute()

    return {
        "ok": True,
        "spreadsheet_id": sid,
        "tab": tab_name,
        "url": f"https://docs.google.com/spreadsheets/d/{sid}/edit",
        "headers": headers,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--title", required=True)
    ap.add_argument("--tab", default="", help="name for the first tab")
    ap.add_argument("--headers-json", default="", help='JSON list, e.g. ["Date","Day"]')
    ap.add_argument("--if-missing", action="store_true",
                    help="return the existing sheet instead of creating a duplicate")
    args = ap.parse_args()

    try:
        headers = json.loads(args.headers_json) if args.headers_json else []
        if not isinstance(headers, list):
            raise ValueError("--headers-json must be a JSON list")

        if args.if_missing and (existing := find_existing(args.title)):
            print(json.dumps({
                "ok": True, "existed": True, "spreadsheet_id": existing,
                "url": f"https://docs.google.com/spreadsheets/d/{existing}/edit",
            }, indent=2))
            return 0

        print(json.dumps(create(args.title, args.tab, headers), indent=2))
    except Exception as exc:  # noqa: BLE001 - the caller is a model reading stdout
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
