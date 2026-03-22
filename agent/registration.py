"""
Registration module.

Stores subscriber data (collected via Google Form → Google Sheets) in a
local SQLite database so the alert-sender cron job can query it quickly
without hitting external APIs on every run.

Schema
------
registrations
  id             INTEGER PRIMARY KEY AUTOINCREMENT
  phone_number   TEXT UNIQUE NOT NULL   -- E.164, e.g. +94771234567
  name           TEXT                   -- optional personalisation
  language       TEXT NOT NULL          -- 'en' | 'si' | 'ta'
  district       TEXT NOT NULL
  ds_division    TEXT                   -- optional finer match
  gn_division    TEXT                   -- optional finest match
  consent        INTEGER NOT NULL       -- 1 = yes
  synced_at      TEXT                   -- ISO-8601 timestamp of last sync
  created_at     TEXT
"""

import sqlite3
import os
from datetime import datetime
from typing import List, Optional, Dict, Any
from config import Config


DB_PATH = os.getenv("REGISTRATIONS_DB", "./data/registrations.db")


def _get_conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create the registrations table if it doesn't exist."""
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS registrations (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                phone_number TEXT UNIQUE NOT NULL,
                name         TEXT,
                language     TEXT NOT NULL DEFAULT 'en',
                district     TEXT NOT NULL,
                ds_division  TEXT,
                gn_division  TEXT,
                consent      INTEGER NOT NULL DEFAULT 1,
                synced_at    TEXT,
                created_at   TEXT NOT NULL
            )
        """)
        conn.commit()
    print("[registration] DB initialised at", DB_PATH)


def upsert_registration(
    phone_number: str,
    language: str,
    district: str,
    name: Optional[str] = None,
    ds_division: Optional[str] = None,
    gn_division: Optional[str] = None,
    consent: bool = True,
    synced_at: Optional[str] = None,
) -> None:
    """Insert or update a single registration row."""
    now = datetime.utcnow().isoformat()
    synced_at = synced_at or now
    with _get_conn() as conn:
        conn.execute(
            """
            INSERT INTO registrations
                (phone_number, name, language, district, ds_division, gn_division,
                 consent, synced_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(phone_number) DO UPDATE SET
                name        = excluded.name,
                language    = excluded.language,
                district    = excluded.district,
                ds_division = excluded.ds_division,
                gn_division = excluded.gn_division,
                consent     = excluded.consent,
                synced_at   = excluded.synced_at
            """,
            (
                phone_number,
                name,
                language,
                district,
                ds_division,
                gn_division,
                1 if consent else 0,
                synced_at,
                now,
            ),
        )
        conn.commit()


def get_subscribers_for_district(district: str) -> List[Dict[str, Any]]:
    """Return all consenting subscribers whose district matches."""
    with _get_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM registrations
            WHERE consent = 1
              AND LOWER(district) = LOWER(?)
            """,
            (district,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_subscribers_for_area(
    district: str,
    ds_division: Optional[str] = None,
    gn_division: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Return consenting subscribers matching the given area.

    Matching priority (most specific wins):
      1. district + ds_division + gn_division
      2. district + ds_division
      3. district only
    All three groups are returned so the caller decides deduplication.
    """
    with _get_conn() as conn:
        query = """
            SELECT * FROM registrations
            WHERE consent = 1
              AND LOWER(district) = LOWER(?)
        """
        params: list = [district]

        if ds_division:
            query += " AND (ds_division IS NULL OR LOWER(ds_division) = LOWER(?))"
            params.append(ds_division)

        if gn_division:
            query += " AND (gn_division IS NULL OR LOWER(gn_division) = LOWER(?))"
            params.append(gn_division)

        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def get_all_subscribers() -> List[Dict[str, Any]]:
    """Return every consenting subscriber."""
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM registrations WHERE consent = 1"
        ).fetchall()
    return [dict(r) for r in rows]


def count_registrations() -> int:
    with _get_conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM registrations").fetchone()[0]
