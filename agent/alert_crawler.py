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
    Fetch the warnings JSON from the GitHub Pages URL and return a list
    of active warning dicts, each with the district key.

    data.json format:
    {
      "last_updated": "...",
      "warnings": { "Colombo": false, "Galle": true, ... }
    }
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

    warnings: Dict[str, bool] = data.get("warnings", {})
    active = [{"district": d} for d, on in warnings.items() if on]

    print(f"[crawler] Active warnings: {len(active)}/{len(warnings)} districts.")
    return active


def build_alert_message(warning: Dict[str, Any], language: str, name: Optional[str] = None) -> str:
    """Build a personalised WhatsApp alert message."""
    district = warning["district"]
    greeting = ""
    if name:
        greeting = f"Hi {name}! " if language == "en" else (
            f"හෙලෝ {name}! " if language == "si" else f"வணக்கம் {name}! "
        )

    if language == "si":
        body = (f"⚠️ *මුල් අනතුරු ඇඟවීම*\n\n"
                f"*{district}* දිස්ත්‍රික්කය සඳහා මුල් අනතුරු ඇඟවීමක් නිකුත් කර ඇත.\n\n"
                f"ආරක්ෂිතව සිටින්න. දේශීය බලධාරීන්ගේ උපදෙස් අනුගමනය කරන්න.")
    elif language == "ta":
        body = (f"⚠️ *ஆரம்ப எச்சரிக்கை*\n\n"
                f"*{district}* மாவட்டத்திற்கு ஆரம்ப எச்சரிக்கை வழங்கப்பட்டுள்ளது.\n\n"
                f"பாதுகாப்பாக இருங்கள். உள்ளூர் அதிகாரிகளின் வழிமுறைகளைப் பின்பற்றுங்கள்.")
    else:
        body = (f"⚠️ *EARLY WARNING ALERT*\n\n"
                f"An early warning has been issued for *{district}* district.\n\n"
                f"Please stay safe and follow instructions from local authorities.")

    return greeting + body
