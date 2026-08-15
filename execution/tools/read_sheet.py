#!/usr/bin/env python3
"""Read a range from a Google Sheet. Prints JSON on stdout.

    python execution/tools/read_sheet.py --sheet-id <id> --range 'Sheet1!A1:D50'
    python execution/tools/read_sheet.py --sheet-id <id> --range 'A1:D50' --header
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.google_auth import sheets_service  # noqa: E402


def read_range(sheet_id: str, cell_range: str) -> list[list[str]]:
    resp = (
        sheets_service()
        .spreadsheets()
        .values()
        .get(spreadsheetId=sheet_id, range=cell_range)
        .execute()
    )
    return resp.get("values", [])


def as_records(rows: list[list[str]]) -> list[dict]:
    """First row becomes keys. Short rows are padded so keys stay aligned."""
    if not rows:
        return []
    header, *body = rows
    width = len(header)
    return [dict(zip(header, row + [""] * (width - len(row)))) for row in body]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sheet-id", required=True)
    ap.add_argument("--range", dest="cell_range", required=True, help="A1 notation")
    ap.add_argument("--header", action="store_true", help="treat row 1 as keys, emit records")
    args = ap.parse_args()

    try:
        rows = read_range(args.sheet_id, args.cell_range)
    except Exception as exc:  # noqa: BLE001 - the caller is a model reading stdout
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1

    payload = {"ok": True, "range": args.cell_range, "row_count": len(rows)}
    payload["records" if args.header else "values"] = as_records(rows) if args.header else rows
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
