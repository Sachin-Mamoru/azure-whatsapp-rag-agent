"""
Alert crawler module.

Fetches the `data.json` published on the GitHub Pages early-warning site and
returns a list of active warning entries so the alert-sender can notify
registered subscribers.

Expected data.json format
--------------------------
{
  "last_updated": "2026-03-22T10:00:00Z",
  "district_warnings": {
    "Colombo": {
      "active": false,
      "level": "none",
      "hazard": "flood",
      "message": {
        "en": "No active warnings for Colombo.",
        "si": "කොළඹ දිස්ත්‍රික්කය සඳහා ක්‍රියාකාරී අනතුරු ඇඟවීම් නොමැත.",
        "ta": "கொழும்பு மாவட்டத்திற்கு செயல்பாட்டு எச்சரிக்கைகள் இல்லை."
      }
    },
    "Galle": {
      "active": true,
      "level": "high",
      "hazard": "flood",
      "message": {
        "en": "⚠️ High flood risk in Galle district. Move to higher ground.",
        "si": "⚠️ ගාල්ල දිස්ත්‍රික්කයේ ඉහළ ගංවතුර අවදානමක්. උස් භූමිය වෙත යන්න.",
        "ta": "⚠️ காலி மாவட்டத்தில் அதிக வெள்ளம் ஆபத்து. உயரமான இடங்களுக்கு நகரவும்."
      }
    }
  }
}

Active warnings are those with `"active": true`.
The `level` field can be: "none" | "low" | "medium" | "high" | "extreme"
The `hazard` field examples: "flood" | "landslide" | "cyclone" | "drought"
"""

from __future__ import annotations

import httpx
from typing import List, Dict, Any, Optional
from config import Config


async def fetch_warnings() -> List[Dict[str, Any]]:
    """
    Fetch the warnings JSON from the GitHub Pages URL configured in
    EARLY_WARNING_DATA_URL and return a list of active warning dicts,
    each enriched with the district key.

    Returns an empty list if the URL is not configured or the request fails.
    """
    url = Config.EARLY_WARNING_DATA_URL
    if not url:
        print("[crawler] EARLY_WARNING_DATA_URL not set – skipping crawl.")
        return []

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        print(f"[crawler] Failed to fetch warning data from {url}: {e}")
        return []

    district_warnings: Dict[str, Any] = data.get("district_warnings", {})
    active: List[Dict[str, Any]] = []

    for district, info in district_warnings.items():
        if info.get("active", False):
            active.append(
                {
                    "district": district,
                    "level": info.get("level", "medium"),
                    "hazard": info.get("hazard", "unknown"),
                    "message": info.get("message", {}),
                }
            )

    print(
        f"[crawler] Fetched warnings. "
        f"Active: {len(active)}/{len(district_warnings)} districts."
    )
    return active


def build_alert_message(warning: Dict[str, Any], language: str, name: Optional[str] = None) -> str:
    """
    Build a personalised WhatsApp alert message from a warning entry.

    Args:
        warning:  A dict returned by fetch_warnings().
        language: 'en' | 'si' | 'ta'
        name:     Optional subscriber name for personalisation.
    """
    greeting = ""
    if name:
        greeting = f"Hi {name}! " if language == "en" else (
            f"හෙලෝ {name}! " if language == "si" else f"வணக்கம் {name}! "
        )

    # Use the translated message from the data.json if available
    msg_dict: Dict[str, str] = warning.get("message", {})
    body = msg_dict.get(language) or msg_dict.get("en", "")

    if not body:
        # Fallback generated message
        district = warning["district"]
        level = warning["level"].upper()
        hazard = warning["hazard"]
        if language == "si":
            body = (
                f"⚠️ {district} දිස්ත්‍රික්කය සඳහා {level} {hazard} අනතුරු ඇඟවීමක්. "
                "කරුණාකර ආරක්ෂිතව සිටින්න. දේශීය බලධාරීන්ගේ උපදෙස් අනුගමනය කරන්න."
            )
        elif language == "ta":
            body = (
                f"⚠️ {district} மாவட்டத்திற்கு {level} {hazard} எச்சரிக்கை. "
                "தயவுசெய்து பாதுகாப்பாக இருங்கள். உள்ளூர் அதிகாரிகளின் வழிமுறைகளை பின்பற்றுங்கள்."
            )
        else:
            body = (
                f"⚠️ {level} {hazard} warning issued for {district} district. "
                "Please stay safe and follow instructions from local authorities."
            )

    return greeting + body
