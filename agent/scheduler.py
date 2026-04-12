"""
Scheduler module.

Sets up two recurring jobs using APScheduler (AsyncIOScheduler):

  1. Google Sheets → SQLite sync      every SHEETS_SYNC_INTERVAL_MINUTES (default 30 min)
  2. Alert crawl + send cycle         every ALERT_CHECK_INTERVAL_MINUTES  (default 60 min)

The scheduler is started once when the FastAPI app boots (lifespan hook) and
shut down cleanly when the app exits.
"""

from __future__ import annotations

import asyncio
import os
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from agent.registration import init_db
from agent.google_sheets_sync import sync_from_google_sheets
from agent.alert_sender import run_alert_cycle
from agent.reporter import CommunityReporter

# How often to pull fresh registrations from Google Sheets
_SHEETS_SYNC_INTERVAL = int(os.getenv("SHEETS_SYNC_INTERVAL_MINUTES", "30"))
# How often to crawl the warning site and send alerts
_ALERT_CHECK_INTERVAL = int(os.getenv("ALERT_CHECK_INTERVAL_MINUTES", "60"))

# How often to run the community report retention/cleanup job
_RETENTION_CHECK_INTERVAL = int(os.getenv("RETENTION_CHECK_INTERVAL_MINUTES", "360"))  # 6 hours

_scheduler: Optional[AsyncIOScheduler] = None

_reporter_instance: Optional[CommunityReporter] = None


def _sync_sheets_job():
    """Synchronous wrapper – called by the scheduler in the event loop."""
    sync_from_google_sheets()


async def _alert_cycle_job():
    """Async job that runs the full crawl + send pipeline."""
    await run_alert_cycle()


def _retention_job():
    """
    Community report retention and reliability decay.

    Retention policy (spec Table 8):
      - active_hazard reports   older than  7 days → archive
      - infrastructure reports  older than 30 days → archive
      - regulatory reports      older than 180 days → archive
      - low-confidence reports  older than 14 days → delete if not validated

    Reliability update:
      Reports that reach archive/delete threshold without being verified
      are treated as weak rejections (α × 0.5) to decay reliability
      without harshly penalising users for genuinely ambiguous events.
    """
    if _reporter_instance is None:
        return
    import sqlite3
    from datetime import datetime, timezone, timedelta

    now = datetime.now(timezone.utc)
    db  = _reporter_instance.db_path

    retention_rules = [
        # (report_domain, max_age_days, action)
        ("hazard",          7,   "archive"),
        ("infrastructure",  30,  "archive"),
        ("regulatory",      180, "archive"),
        ("safety",          14,  "archive"),
        ("unknown",         14,  "delete"),
    ]

    total_archived = 0
    total_deleted  = 0

    try:
        with sqlite3.connect(db) as conn:
            conn.row_factory = sqlite3.Row

            for domain, max_days, action in retention_rules:
                cutoff = (now - timedelta(days=max_days)).isoformat()

                # Find qualifying reports (new / monitored / under_review only
                # — do not re-process already closed / escalated / archived)
                rows = conn.execute("""
                    SELECT report_id, user_hash, confidence_score, status
                    FROM community_reports
                    WHERE report_domain = ?
                      AND created_at < ?
                      AND status IN ('new', 'monitored', 'under_review')
                """, (domain, cutoff)).fetchall()

                for row in rows:
                    rid        = row["report_id"]
                    user_hash  = row["user_hash"]
                    conf       = row["confidence_score"]
                    old_status = row["status"]
                    changed_at = now.isoformat()

                    if action == "delete" and conf < 0.40:
                        conn.execute(
                            "DELETE FROM community_reports WHERE report_id = ?", (rid,)
                        )
                        conn.execute("""
                            INSERT INTO report_status_log
                              (report_id, old_status, new_status, changed_at, note)
                            VALUES (?, ?, 'deleted', ?, 'retention: low-conf expired')
                        """, (rid, old_status, changed_at))
                        total_deleted += 1
                    else:
                        conn.execute(
                            "UPDATE community_reports SET status = 'archived' "
                            "WHERE report_id = ?", (rid,)
                        )
                        conn.execute("""
                            INSERT INTO report_status_log
                              (report_id, old_status, new_status, changed_at, note)
                            VALUES (?, ?, 'archived', ?, 'retention: age policy')
                        """, (rid, old_status, changed_at))
                        total_archived += 1

                    # Weak reliability decay for unvalidated reports
                    # (half the normal rejection weight — spec Section 11)
                    _reporter_instance.update_user_reliability(
                        user_hash,
                        verified=False,
                        note=f"retention expiry {rid} (half-weight)"
                    )

            conn.commit()

        if total_archived or total_deleted:
            print(
                f"[scheduler] retention_job: archived={total_archived} "
                f"deleted={total_deleted}"
            )

    except Exception as exc:
        print(f"[scheduler] retention_job error: {exc}")


def start_scheduler(reporter: Optional[CommunityReporter] = None):
    """
    Initialise the DB and start the background scheduler.
    Call once from the FastAPI lifespan startup handler.
    Pass the shared CommunityReporter instance so the retention job
    can call update_user_reliability().
    """
    global _scheduler, _reporter_instance
    _reporter_instance = reporter

    # Ensure SQLite DB and tables exist
    init_db()

    # Run an immediate sheets sync on startup so we have fresh data
    try:
        sync_from_google_sheets()
    except Exception as e:
        print(f"[scheduler] Initial sheets sync failed (non-fatal): {e}")

    _scheduler = AsyncIOScheduler()

    _scheduler.add_job(
        _sync_sheets_job,
        trigger=IntervalTrigger(minutes=_SHEETS_SYNC_INTERVAL),
        id="sheets_sync",
        name="Google Sheets → SQLite sync",
        replace_existing=True,
        misfire_grace_time=300,
    )

    _scheduler.add_job(
        _alert_cycle_job,
        trigger=IntervalTrigger(minutes=_ALERT_CHECK_INTERVAL),
        id="alert_cycle",
        name="Early warning crawl + WhatsApp alerts",
        replace_existing=True,
        misfire_grace_time=300,
    )

    _scheduler.add_job(
        _retention_job,
        trigger=IntervalTrigger(minutes=_RETENTION_CHECK_INTERVAL),
        id="retention",
        name="Community report retention + reliability decay",
        replace_existing=True,
        misfire_grace_time=600,
    )

    _scheduler.start()
    print(
        f"[scheduler] Started. "
        f"Sheets sync every {_SHEETS_SYNC_INTERVAL} min, "
        f"alert check every {_ALERT_CHECK_INTERVAL} min, "
        f"retention check every {_RETENTION_CHECK_INTERVAL} min."
    )


def stop_scheduler():
    """Stop the scheduler gracefully. Call from the FastAPI lifespan shutdown."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        print("[scheduler] Stopped.")


async def trigger_alert_now():
    """
    Manually trigger one alert cycle immediately (e.g. called from an API
    endpoint for testing or admin use).
    """
    return await run_alert_cycle()


async def trigger_sheets_sync_now():
    """Manually trigger a sheets sync (useful for the admin endpoint)."""
    return sync_from_google_sheets()
