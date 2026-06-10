#!/usr/bin/env python3
"""
Push Instagram DM leads to the "Instagram DM" tab in Google Sheets.
Called automatically by scraper.py, or run manually: python3 sheets_sync.py
"""

import csv
import os
from datetime import datetime

import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

load_dotenv()

SHEET_ID   = os.getenv("GOOGLE_SHEET_ID", "")
CREDS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "/home/cohen/google_credentials.json")
DMS_FILE   = "ig_dms.csv"
TAB_NAME   = "Instagram DM"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

HEADER = [
    "Handle", "Full Name", "Followers", "Website", "Location",
    "DM Copy", "Sent", "Replied", "Scraped At",
]


def load_dms() -> list[dict]:
    try:
        with open(DMS_FILE, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except FileNotFoundError:
        return []


def push_to_sheets(rows: list[dict]):
    if not SHEET_ID:
        print("  ERROR: GOOGLE_SHEET_ID missing in .env")
        return
    if not os.path.exists(CREDS_FILE):
        print(f"  ERROR: credentials file not found: {CREDS_FILE}")
        return

    creds  = Credentials.from_service_account_file(CREDS_FILE, scopes=SCOPES)
    gc     = gspread.authorize(creds)
    ss     = gc.open_by_key(SHEET_ID)

    # Get or create the tab
    try:
        ws = ss.worksheet(TAB_NAME)
        ws.clear()
    except gspread.exceptions.WorksheetNotFound:
        ws = ss.add_worksheet(title=TAB_NAME, rows=5000, cols=len(HEADER))

    scraped_at = datetime.now().strftime("%Y-%m-%d %H:%M")

    sheet_rows = [HEADER]
    for r in rows:
        sheet_rows.append([
            f"@{r.get('handle', '')}",
            r.get("full_name", ""),
            r.get("followers", ""),
            r.get("website", ""),
            r.get("location", ""),
            r.get("dm", ""),
            r.get("sent", "no"),
            r.get("replied", "no"),
            scraped_at,
        ])

    ws.update(sheet_rows, value_input_option="USER_ENTERED")

    # Bold + dark header row with white text
    ws.format("1:1", {
        "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
        "backgroundColor": {"red": 0.12, "green": 0.12, "blue": 0.12},
    })

    # Freeze header
    ss.batch_update({"requests": [{"updateSheetProperties": {
        "properties": {"sheetId": ws.id, "gridProperties": {"frozenRowCount": 1}},
        "fields": "gridProperties.frozenRowCount",
    }}]})

    print(f"  Pushed {len(rows)} leads to '{TAB_NAME}' tab")
    print(f"  https://docs.google.com/spreadsheets/d/{SHEET_ID}")


def main():
    rows = load_dms()
    if not rows:
        print(f"  {DMS_FILE} not found or empty. Run scraper.py first.")
        return
    push_to_sheets(rows)


if __name__ == "__main__":
    main()
