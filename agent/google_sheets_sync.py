"""
Google Sheets sync module.

Reads Google Form responses from a linked Google Sheet and upserts them
into the local SQLite registrations DB.

Expected column order produced by the Google Form (1-indexed):
  A  1  Timestamp
  B  2  Phone Number          (required)
  C  3  Name                  (optional)
  D  4  Preferred Language    ("English" | "Sinhala" | "Tamil")
  E  5  District              (required)
  F  6  DS Division           (optional)
  G  7  GN Division           (optional)
  H  8  Consent               ("Yes" | "No")

If your form uses different column names/order, adjust COL_* constants below.

Setup
-----
1. Create a Google Cloud service account and download the JSON key file.
2. Share the Google Sheet with the service account email (Viewer access is enough).
3. Set in .env:
      GOOGLE_SHEETS_CREDENTIALS_FILE=./credentials.json
      GOOGLE_SHEETS_SPREADSHEET_ID=<spreadsheet-id>
"""

import os
import json
import re
from datetime import datetime
from typing import List, Dict, Optional

from config import Config
from agent.registration import upsert_registration, count_registrations

# ── column indices (0-based after reading rows) ─────────────────────────────
COL_TIMESTAMP  = 0
COL_PHONE      = 1
COL_NAME       = 2
COL_LANGUAGE   = 3
COL_DISTRICT   = 4
COL_DS         = 5
COL_GN         = 6
COL_CONSENT    = 7

# ── language label → internal code ───────────────────────────────────────────
LANG_MAP = {
    "english":  "en",
    "sinhala":  "si",
    "tamil":    "ta",
    "සිංහල":    "si",
    "தமிழ்":    "ta",
    "en": "en",
    "si": "si",
    "ta": "ta",
}


def _normalise_phone(raw: str) -> str:
    """
    Normalise a Sri Lankan phone number to E.164 (+94xxxxxxxxx).
    Accepts: 0771234567 / +94771234567 / 94771234567
    """
    digits = re.sub(r"[^\d+]", "", raw.strip())
    if digits.startswith("+"):
        return digits
    if digits.startswith("94"):
        return "+" + digits
    if digits.startswith("0"):
        return "+94" + digits[1:]
    # assume local without leading 0
    return "+94" + digits


def _row_to_registration(row: List[str]) -> Optional[Dict]:
    """Parse a single sheet row. Returns None if the row should be skipped."""
    try:
        # Pad row in case trailing empty cells are missing
        row = list(row) + [""] * (COL_CONSENT + 1)

        consent_raw = row[COL_CONSENT].strip().lower()
        if consent_raw not in ("yes", "true", "1", "y"):
            return None  # skip rows where consent was not given

        phone_raw = row[COL_PHONE].strip()
        if not phone_raw:
            return None

        phone = _normalise_phone(phone_raw)
        name = row[COL_NAME].strip() or None
        lang_raw = row[COL_LANGUAGE].strip().lower()
        language = LANG_MAP.get(lang_raw, "en")
        district = row[COL_DISTRICT].strip()
        if not district:
            return None
        ds_division = row[COL_DS].strip() or None
        gn_division = row[COL_GN].strip() or None
        synced_at = datetime.utcnow().isoformat()

        return {
            "phone_number": phone,
            "name": name,
            "language": language,
            "district": district,
            "ds_division": ds_division,
            "gn_division": gn_division,
            "consent": True,
            "synced_at": synced_at,
        }
    except Exception as e:
        print(f"[sheets_sync] skipping malformed row: {e} | row={row}")
        return None


def sync_from_google_sheets() -> int:
    """
    Pull all rows from the Google Sheet and upsert into SQLite.
    Returns the number of rows synced.
    """
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError:
        print(
            "[sheets_sync] gspread / google-auth not installed. "
            "Run: pip install gspread google-auth"
        )
        return 0

    creds_file = Config.GOOGLE_SHEETS_CREDENTIALS_FILE
    spreadsheet_id = Config.GOOGLE_SHEETS_SPREADSHEET_ID

    if not creds_file or not spreadsheet_id:
        print(
            "[sheets_sync] GOOGLE_SHEETS_CREDENTIALS_FILE or "
            "GOOGLE_SHEETS_SPREADSHEET_ID not set – skipping sync."
        )
        return 0

    if not os.path.exists(creds_file):
        print(f"[sheets_sync] credentials file not found: {creds_file}")
        return 0

    try:
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets.readonly",
            "https://www.googleapis.com/auth/drive.readonly",
        ]
        creds = Credentials.from_service_account_file(creds_file, scopes=scopes)
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(spreadsheet_id)
        worksheet = sh.get_worksheet(0)  # first sheet = Form Responses 1
        rows = worksheet.get_all_values()
    except Exception as e:
        print(f"[sheets_sync] Error reading Google Sheet: {e}")
        return 0

    if not rows:
        print("[sheets_sync] Sheet is empty.")
        return 0

    # Skip the header row
    data_rows = rows[1:]
    synced = 0
    for row in data_rows:
        reg = _row_to_registration(row)
        if reg:
            upsert_registration(**reg)
            synced += 1

    print(
        f"[sheets_sync] Synced {synced}/{len(data_rows)} rows. "
        f"Total registrations: {count_registrations()}"
    )
    return synced
