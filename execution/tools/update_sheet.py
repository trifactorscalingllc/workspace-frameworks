#!/usr/bin/env python3
"""Write or append rows in a Google Sheet. Prints JSON on stdout.

    # overwrite a range
    python execution/tools/update_sheet.py --sheet-id <id> --range 'Sheet1!A1' \
        --values-json '[["name","email"],["Ada","ada@example.com"]]'

    # append below the last populated row
    python execution/tools/update_sheet.py --sheet-id <id> --range 'Sheet1!A:B' \
        --values-json '[["Grace","grace@example.com"]]' --append
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.google_auth import sheets_service  # noqa: E402


def write_range(sheet_id: str, cell_range: str, values: list[list], append: bool) -> dict:
    values_api = sheets_service().spreadsheets().values()
    body = {"values": values}
    common = dict(
        spreadsheetId=sheet_id,
        range=cell_range,
        valueInputOption="USER_ENTERED",
        body=body,
    )
    if append:
        return values_api.append(insertDataOption="INSERT_ROWS", **common).execute()
    return values_api.update(**common).execute()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sheet-id", required=True)
    ap.add_argument("--range", dest="cell_range", required=True, help="A1 notation")
    ap.add_argument("--values-json", required=True, help="JSON list of rows, e.g. [[\"a\",\"b\"]]")
    ap.add_argument("--append", action="store_true", help="append instead of overwrite")
    args = ap.parse_args()

    try:
        values = json.loads(args.values_json)
        if not isinstance(values, list) or not all(isinstance(r, list) for r in values):
            raise ValueError("--values-json must be a list of lists (rows of cells)")
        resp = write_range(args.sheet_id, args.cell_range, values, args.append)
    except Exception as exc:  # noqa: BLE001 - the caller is a model reading stdout
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1

    updates = resp.get("updates", resp)
    print(
        json.dumps(
            {
                "ok": True,
                "mode": "append" if args.append else "update",
                "updated_range": updates.get("updatedRange"),
                "updated_rows": updates.get("updatedRows"),
                "updated_cells": updates.get("updatedCells"),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
