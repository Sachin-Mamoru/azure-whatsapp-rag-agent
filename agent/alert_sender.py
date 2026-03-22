"""
Alert sender module.

Orchestrates the full alert pipeline:
  1. Crawl the GitHub Pages site for active warnings.
  2. Look up registered subscribers in those districts.
  3. Send a WhatsApp message to each subscriber in their preferred language.
  4. Track sent alerts in Redis to avoid duplicate messages within a cooldown
     window (default 12 hours).
"""

from __future__ import annotations

import json
import redis
import asyncio
import httpx
from datetime import datetime
from typing import List, Dict, Any

from config import Config
from agent.registration import get_subscribers_for_district
from agent.alert_crawler import fetch_warnings, build_alert_message

# Redis key prefix for dedup tracking
_ALERT_SENT_PREFIX = "alert_sent:"
# Seconds before the same subscriber gets the same district alert again
_COOLDOWN_SECONDS = 60 * 60 * 12  # 12 hours


def _sent_key(phone: str, district: str) -> str:
    safe_district = district.replace(" ", "_").lower()
    return f"{_ALERT_SENT_PREFIX}{phone}:{safe_district}"


def _already_sent(redis_client: redis.Redis, phone: str, district: str) -> bool:
    return bool(redis_client.exists(_sent_key(phone, district)))


def _mark_sent(redis_client: redis.Redis, phone: str, district: str):
    redis_client.setex(_sent_key(phone, district), _COOLDOWN_SECONDS, "1")


async def _send_whatsapp(phone: str, message: str) -> bool:
    """Send a single WhatsApp message via the Cloud API."""
    url = f"{Config.WHATSAPP_BASE_URL}/messages"
    headers = {
        "Authorization": f"Bearer {Config.WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "text",
        "text": {"body": message},
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            return True
    except Exception as e:
        print(f"[alert_sender] Failed to send to {phone}: {e}")
        return False


async def run_alert_cycle() -> Dict[str, int]:
    """
    Full alert cycle: crawl → match → send.

    Returns a summary dict:
      { "warnings": int, "notified": int, "skipped": int, "errors": int }
    """
    stats = {"warnings": 0, "notified": 0, "skipped": 0, "errors": 0}

    # 1. Fetch active warnings
    warnings = await fetch_warnings()
    stats["warnings"] = len(warnings)

    if not warnings:
        print("[alert_sender] No active warnings – nothing to send.")
        return stats

    # 2. Connect to Redis for dedup tracking
    try:
        redis_client = redis.from_url(Config.REDIS_URL)
        redis_client.ping()
    except Exception as e:
        print(f"[alert_sender] Redis unavailable: {e} – dedup disabled.")
        redis_client = None  # type: ignore[assignment]

    # 3. For each warning, find matching subscribers and send
    for warning in warnings:
        district = warning["district"]
        subscribers = get_subscribers_for_district(district)

        if not subscribers:
            print(f"[alert_sender] No subscribers for district: {district}")
            continue

        for sub in subscribers:
            phone = sub["phone_number"]
            language = sub.get("language", "en")
            name = sub.get("name")

            # Dedup check
            if redis_client and _already_sent(redis_client, phone, district):
                stats["skipped"] += 1
                continue

            message = build_alert_message(warning, language, name)
            success = await _send_whatsapp(phone, message)

            if success:
                if redis_client:
                    _mark_sent(redis_client, phone, district)
                stats["notified"] += 1
                print(
                    f"[alert_sender] ✅ Alert sent → {phone} "
                    f"({district}, lang={language})"
                )
            else:
                stats["errors"] += 1

            # Rate-limit: WhatsApp API allows ~80 msgs/sec; be conservative
            await asyncio.sleep(0.2)

    print(
        f"[alert_sender] Cycle complete – "
        f"warnings={stats['warnings']}, notified={stats['notified']}, "
        f"skipped={stats['skipped']}, errors={stats['errors']}"
    )
    return stats
