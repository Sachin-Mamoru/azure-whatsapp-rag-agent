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
    """Community report and photo retention (see CommunityReporter.apply_retention)."""
    if _reporter_instance is None:
        return
    try:
        stats = _reporter_instance.apply_retention()
        if any(stats.values()):
            print(f"[scheduler] retention_job: {stats}")
    except Exception as exc:
        print(f"[scheduler] retention_job error: {exc}")


def start_scheduler(reporter: Optional[CommunityReporter] = None):
    """
    Initialise the DB and start the background scheduler.
    Call once from the FastAPI lifespan startup handler.
    Pass the shared CommunityReporter instance so the retention job
    can call apply_retention().
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
        name="Community report and photo retention",
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
