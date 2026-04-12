"""
Community Reporting Module
--------------------------
Converts unstructured citizen observations sent via WhatsApp into structured,
governed mitigation intelligence stored in a separate SQLite database.

Pipeline:  text message → LLM extraction → confidence/severity scoring
           → decision engine → SQLite store → user acknowledgement

The community report store is ALWAYS separate from the authoritative RAG
vectorstore. Community observations only feed the advisory pipeline as
read-only supplementary context with explicit source labelling.
"""

import hashlib
import json
import math
import os
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
import aiohttp

from config import Config


# ── Multilingual indicator dictionaries ──────────────────────────────────────
# Each group covers English, Sinhala (si) and Tamil (ta).

LANDSLIDE_INDICATORS: Dict[str, List[str]] = {
    "en": [
        "crack on slope", "slope crack", "soil crack", "ground cracking",
        "leaning tree", "tilted pole", "wall crack", "soil sliding",
        "rock fall", "debris sliding", "water seeping from slope",
        "landslide", "mudslide", "slope failure", "earth movement",
        "ground movement", "soil movement", "boulders falling",
        "rocks falling", "hillside crack", "road cracking",
        "slope moving", "land slipping", "cracks in ground",
    ],
    "si": [
        "බෑවුමේ ඉරිතලා", "පස් ඉරිතලා", "බිම ඉරිතලා", "ගස් ඇලවී",
        "කඳු නාය", "නාය යාම", "පස් ගෙමින්", "ගල් ඇද", "පස් සෙලවී",
        "ජලය රිංගනවා", "ජලය ගලනවා", "බිම සෙලවෙනවා",
        "කන්ද නාය", "පස් නාය", "ගල් ගෙමින්", "නාය",
        "තාප්පය ඉරිතලා", "ඉරිතැලීම",
    ],
    "ta": [
        "சரிவில் வெடிப்பு", "மண் வெடிப்பு", "தரை வெடிப்பு",
        "சரிந்த மரம்", "நிலச்சரிவு", "மண் சரிவு", "பாறை விழுகிறது",
        "சேறு சரிவு", "மண் நகர்கிறது", "நீர் சரிவிலிருந்து",
        "மலைச்சரிவு", "நிலம் நகர்கிறது",
    ],
}

FLOOD_INDICATORS: Dict[str, List[str]] = {
    "en": [
        "water level rising", "water entering house", "flood water",
        "road under water", "blocked drain", "blocked culvert",
        "drainage overflow", "river overflow", "flooding", "water rising",
        "inundated", "flooded", "submerged", "overflowing river",
        "water spreading", "flash flood", "water in street",
        "water in house", "river rising", "water overflowing",
    ],
    "si": [
        "ජල මට්ටම ඉහළ", "ගෙදර ජලය", "ගංවතුර", "පාර යට ජලය",
        "කාණු අවහිර", "ජලය ගලා", "ගංඟාව ඉතිරී", "ජල ගැලීම",
        "ජලය පැතිරෙනවා", "ගං ජලය", "ජලය වැඩිවෙනවා",
        "ජලය ගෙදරට", "ගං", "ජල",
    ],
    "ta": [
        "நீர் மட்டம் உயர்கிறது", "வீட்டில் தண்ணீர்", "வெள்ளம்",
        "சாலை மூழ்கி", "வடிகால் அடைப்பு", "குழாய் அடைப்பு",
        "வெள்ள நீர்", "ஆறு வழிகிறது", "நீர் பரவுகிறது",
        "நீர் வீட்டில் நுழைகிறது", "வெள்ளப்பெருக்கு",
    ],
}

INFRASTRUCTURE_INDICATORS: Dict[str, List[str]] = {
    "en": [
        "damaged retaining wall", "culvert failure", "road erosion",
        "road washed away", "bridge damage", "stormwater blockage",
        "drain blocked", "culvert blocked", "road broken", "road damaged",
        "embankment damaged", "wall collapsed", "road collapsed",
        "retaining wall", "culvert", "road washout", "bridge collapsed",
    ],
    "si": [
        "රඳවා තබන බිත්තිය හානි", "කාල්වර්ට් හානි", "පාර කා දමා",
        "පාලම හානි", "ජල බස්නිය හානි", "කාණු අවහිර", "පාර කඩා",
        "තාප්පය කඩා", "පාර ගිලා", "පාලම කඩා",
    ],
    "ta": [
        "தாங்கு சுவர் சேதம்", "குழாய் வீழ்ச்சி", "சாலை அரிப்பு",
        "சாலை அடித்துச் சென்றது", "பாலம் சேதம்", "வடிகால் அடைப்பு",
        "சாலை சேதம்", "தாங்கு சுவர்",
    ],
}

REGULATORY_INDICATORS: Dict[str, List[str]] = {
    "en": [
        "slope cutting", "unsafe excavation", "filling drainage path",
        "construction near river", "construction on steep slope",
        "river encroachment", "illegal construction", "digging near slope",
        "blocking water flow", "filling wetland", "illegal digging",
        "excavation near", "cutting hill",
    ],
    "si": [
        "බෑවුම කපා", "ආරක්ෂිත නොවන කැනීම", "නීතිවිරෝධී ඉදිකිරීම",
        "ගං ඉවුර ඉදිකිරීම", "ගං ඉවුර කැනීම", "බෑවුම කැනීම",
    ],
    "ta": [
        "சரிவு வெட்டல்", "பாதுகாப்பற்ற தோண்டல்", "வடிகால் மூடல்",
        "நதி அருகில் கட்டுமானம்", "சட்டவிரோத கட்டுமானம்",
        "சட்டவிரோத தோண்டல்",
    ],
}

EXPOSURE_INDICATORS: Dict[str, List[str]] = {
    "en": [
        "near houses", "school", "hospital", "village", "settlement",
        "main road", "people trapped", "families nearby", "residents",
        "community", "homes", "children", "many people", "populated",
    ],
    "si": [
        "ගෙවල් ළඟ", "පාසල", "රෝහල", "ගම", "ජනාවාස",
        "ප්‍රධාන පාර", "හිරවී", "පවුල්", "ළමයින්",
    ],
    "ta": [
        "வீடுகள் அருகில்", "பள்ளி", "மருத்துவமனை", "கிராமம்",
        "குடியிருப்பு", "பிரதான சாலை", "மக்கள் சிக்கி", "குடும்பங்கள்",
    ],
}

IMMEDIACY_INDICATORS: Dict[str, List[str]] = {
    "en": [
        "now", "currently", "ongoing", "getting worse", "right now",
        "happening now", "water rising rapidly", "urgent", "emergency",
        "danger", "immediately", "still happening", "just now",
    ],
    "si": [
        "දැන්", "දැනට", "නරක් වෙනවා", "හදිසි",
        "ඉක්මනින්", "අනතුර",
    ],
    "ta": [
        "இப்போது", "தற்போது", "நடக்கிறது", "மோசமாகிறது",
        "அவசரம்", "ஆபத்து", "உதவி",
    ],
}

# Groups used for REPORT intent auto-detection (hazard-bearing groups only)
_REPORT_INDICATOR_GROUPS = [
    LANDSLIDE_INDICATORS,
    FLOOD_INDICATORS,
    INFRASTRUCTURE_INDICATORS,
    REGULATORY_INDICATORS,
]

# Minimum distance (km) two reporters must be apart to count as spatially
# independent corroborating evidence (Sybil-resistance threshold).
# Phase-1: we use coarse location-text token matching, so this is applied
# as a logical guard — same location token from same user_hash = not independent.
_MIN_SEPARATION_REPORTS = 2   # need at least this many *independent* contributors
_DEFAULT_RELIABILITY    = 0.5  # prior for new/unknown users (TruthFinder prior)

# Approximate lat/lon centres for Sri Lanka districts used for rainfall lookup.
# Open-Meteo free API requires no key.  Phase-1 uses district-level centres;
# a future phase can replace with user-provided GPS coordinates.
_DISTRICT_COORDS: Dict[str, tuple] = {
    "colombo":      (6.93, 79.85),  "gampaha":   (7.09, 80.01),
    "kalutara":     (6.58, 80.00),  "kandy":     (7.29, 80.63),
    "matale":       (7.47, 80.62),  "nuwara eliya": (6.96, 80.77),
    "galle":        (6.05, 80.22),  "matara":    (5.95, 80.55),
    "hambantota":   (6.12, 81.12),  "ratnapura": (6.68, 80.38),
    "kegalle":      (7.25, 80.34),  "badulla":   (6.99, 81.05),
    "monaragala":   (6.87, 81.35),  "kurunegala":(7.49, 80.36),
    "kelani":       (6.97, 80.01),  "hanwella":  (6.91, 80.08),
    "kelaniya":     (7.00, 79.92),
}

# Lookup sets for Phase-1 plausibility scoring
LANDSLIDE_PRONE_DISTRICTS = {
    "badulla", "ratnapura", "kandy", "kegalle", "nuwara eliya",
    "matale", "kalutara", "galle", "matara", "hambantota",
    "monaragala", "kurunegala", "sabaragamuwa",
    # Sinhala variants
    "බදුල්ල", "රත්නපුර", "මහනුවර", "කෑගල්ල", "නුවරඑළිය",
    "ගාල්ල", "මාතර",
}

FLOOD_PRONE_LOCALITIES = {
    "colombo", "kelani", "kalu", "nilwala", "gin", "attanagalu",
    "hanwella", "welisara", "kaduwela", "kelaniya", "biyagama",
    "gampaha", "kalutara", "panadura", "horana", "avissawella",
    "rathnapura", "kalu ganga", "deduru oya",
    # Sinhala variants
    "කොළඹ", "කැලනිය", "හංවැල්ල", "ගම්පහ",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _hash_phone(phone_number: str) -> str:
    """One-way SHA-256 hash of phone number for anonymized storage."""
    return hashlib.sha256(phone_number.encode("utf-8")).hexdigest()[:16]


def _contains_indicators(text: str, groups: List[Dict[str, List[str]]]) -> bool:
    """Check whether text contains any indicator from the given groups (all languages)."""
    text_lower = text.lower()
    for group in groups:
        for indicators in group.values():
            for phrase in indicators:
                if phrase.lower() in text_lower:
                    return True
    return False


# ── Public intent-detection helper (used by orchestrator) ────────────────────

def detect_report_intent(message: str) -> bool:
    """
    Fast, LLM-free check: does this message look like a hazard/incident report?

    Returns False for questions (ending in '?' or starting with interrogative
    words) even if hazard terms appear in the text.  This prevents advisory
    queries like "What causes landslides?" being mis-routed to the report
    pipeline.
    """
    text = message.strip().lower()

    # Interrogative patterns → almost certainly a question, not a report
    question_starts = (
        "what", "how", "why", "when", "where", "who", "which",
        "is ", "are ", "can ", "could ", "should ", "would ",
        "tell me", "explain", "describe", "does ", "do ",
    )
    if text.endswith("?") or any(text.startswith(q) for q in question_starts):
        return False

    return _contains_indicators(message, _REPORT_INDICATOR_GROUPS)


# ── Main class ────────────────────────────────────────────────────────────────

class CommunityReporter:
    """
    Manages the end-to-end community reporting pipeline:
      extract → confidence/severity score → decide → store → acknowledge

    The community_reports SQLite database is completely separate from the
    authoritative FAISS vectorstore used by RAGSystem.
    """

    def __init__(self):
        self.llm = ChatOpenAI(
            model=Config.MODEL_NAME,
            openai_api_key=Config.OPENAI_API_KEY,
            temperature=0.0,
        )
        self.db_path = Config.COMMUNITY_REPORTS_DB
        # Short-lived in-memory rainfall cache {district: mm_today}
        # Populated per-report by _fetch_rainfall_for_location()
        self._rainfall_cache: Dict[str, float] = {}
        self._init_db()

    # ── Database setup ────────────────────────────────────────────────────

    def _init_db(self) -> None:
        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS community_reports (
                    report_id        TEXT PRIMARY KEY,
                    timestamp        TEXT NOT NULL,
                    user_hash        TEXT NOT NULL,
                    language         TEXT NOT NULL,
                    report_domain    TEXT NOT NULL,
                    hazard_type      TEXT,
                    category         TEXT,
                    location_text    TEXT,
                    description      TEXT,
                    confidence_score REAL NOT NULL,
                    severity_score   REAL NOT NULL,
                    action           TEXT NOT NULL,
                    status           TEXT NOT NULL DEFAULT 'new',
                    people_at_risk   INTEGER DEFAULT 0,
                    ongoing          INTEGER DEFAULT 0,
                    created_at       TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS report_status_log (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    report_id   TEXT NOT NULL,
                    old_status  TEXT,
                    new_status  TEXT NOT NULL,
                    changed_at  TEXT NOT NULL,
                    note        TEXT
                )
            """)
            # Research audit log: every tool call the LLM agent makes is
            # stored here so routing decisions can be evaluated and analysed.
            conn.execute("""
                CREATE TABLE IF NOT EXISTS agent_tool_calls (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_hash  TEXT NOT NULL,
                    tool_name  TEXT NOT NULL,
                    tool_input TEXT,
                    called_at  TEXT NOT NULL
                )
            """)
            # Bayesian source reliability table (TruthFinder model).
            # r_total     = sum of log-odds updates from verified corroborations
            # n_reports   = total reports submitted by this user
            # n_verified  = reports later confirmed by official source or triangulation
            # n_rejected  = reports that expired unvalidated or were marked false
            # reliability = current P(user tells truth), initialised to 0.5
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_reliability (
                    user_hash   TEXT PRIMARY KEY,
                    reliability REAL    NOT NULL DEFAULT 0.5,
                    n_reports   INTEGER NOT NULL DEFAULT 0,
                    n_verified  INTEGER NOT NULL DEFAULT 0,
                    n_rejected  INTEGER NOT NULL DEFAULT 0,
                    updated_at  TEXT    NOT NULL
                )
            """)
            conn.commit()

    # ── Public API ────────────────────────────────────────────────────────

    async def process_report(
        self,
        phone_number: str,
        message: str,
        language: str,
        pending_report: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """
        Main entry point called from the orchestrator.

        Returns a dict:
          {
            "response":             str,        # WhatsApp reply to send
            "report_id":            str | None,
            "needs_clarification":  bool,
            "clarification_field":  str | None,
            "pending_report":       dict | None, # carry forward if clarification needed
            "stored":               bool,
          }
        """
        # If we are receiving a clarification answer for an existing pending report
        if pending_report:
            extracted = dict(pending_report)
            clarification_field = extracted.pop("_clarification_field", None)
            if clarification_field == "location":
                extracted["location_text"] = message.strip()
            elif clarification_field == "description":
                extracted["description"] = message.strip()
        else:
            extracted = await self._extract_report(message, language)

        # Only ask ONE follow-up: location is the most actionable missing field
        if not extracted.get("location_text"):
            extracted["_clarification_field"] = "location"
            return {
                "response": self._clarification_prompt(language, "location"),
                "report_id": None,
                "needs_clarification": True,
                "clarification_field": "location",
                "pending_report": extracted,
                "stored": False,
            }

        # Fetch rainfall context for plausibility scoring (non-blocking — best effort)
        loc = extracted.get("location_text") or ""
        if loc:
            await self._fetch_rainfall_for_location(loc)

        # Score
        confidence = self._score_confidence(extracted, phone_number)
        severity = self._score_severity(extracted)
        action = self._decide_action(confidence, severity)

        # Build record
        report_id = f"RPT-{uuid.uuid4().hex[:8].upper()}"
        now = datetime.now(timezone.utc).isoformat()
        record: Dict[str, Any] = {
            "report_id":        report_id,
            "timestamp":        now,
            "user_hash":        _hash_phone(phone_number),
            "language":         language,
            "report_domain":    extracted.get("report_domain", "unknown"),
            "hazard_type":      extracted.get("hazard_type", "unknown"),
            "category":         extracted.get("category", "general"),
            "location_text":    extracted.get("location_text", ""),
            "description":      extracted.get("description", ""),
            "confidence_score": round(confidence, 3),
            "severity_score":   round(severity, 3),
            "action":           action,
            "status":           "new",
            "people_at_risk":   1 if extracted.get("people_at_risk") else 0,
            "ongoing":          1 if extracted.get("ongoing") else 0,
            "created_at":       now,
        }

        self._store_report(record)

        return {
            "response":             self._acknowledgement(language, report_id, action, severity),
            "report_id":            report_id,
            "needs_clarification":  False,
            "clarification_field":  None,
            "pending_report":       None,
            "stored":               True,
        }

    def log_tool_call(self, phone_number: str, tool_name: str, tool_input: Dict) -> None:
        """
        Persist an agent tool-call record for research evaluation.
        Every routing decision (which tool the LLM chose and why) is recorded
        so tool-selection accuracy can be measured against a labelled test set.
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT INTO agent_tool_calls (user_hash, tool_name, tool_input, called_at)
                    VALUES (?, ?, ?, ?)
                """, (
                    _hash_phone(phone_number),
                    tool_name,
                    json.dumps(tool_input, ensure_ascii=False),
                    datetime.now(timezone.utc).isoformat(),
                ))
                conn.commit()
            print(f"[reporter] tool_call logged: {tool_name}")
        except Exception as exc:
            print(f"[reporter] log_tool_call error: {exc}")

    def get_recent_reports_context(self) -> str:
        """
        Return a brief formatted summary of recent, high-confidence community
        reports suitable for injection into RAG advisory responses as read-only
        supplementary context.

        Only surfaces reports with action in (monitor, flag_review, escalate)
        and confidence >= 0.4, from the last 48 hours.
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute("""
                    SELECT report_domain, hazard_type, location_text,
                           description, confidence_score, severity_score,
                           action, timestamp
                    FROM community_reports
                    WHERE timestamp >= ?
                      AND action IN ('monitor', 'flag_review', 'escalate')
                      AND confidence_score >= 0.4
                      AND status NOT IN ('closed', 'archived', 'stale')
                    ORDER BY severity_score DESC, timestamp DESC
                    LIMIT 5
                """, (cutoff,)).fetchall()
        except Exception as exc:
            print(f"[reporter] get_recent_reports_context error: {exc}")
            return ""

        if not rows:
            return ""

        lines = ["📍 Recent community observations (unverified):"]
        for row in rows:
            ts = row["timestamp"][:16].replace("T", " ")
            lines.append(
                f"• [{row['report_domain'].upper()}] {row['location_text']} — "
                f"{(row['description'] or '')[:120]} "
                f"(conf: {row['confidence_score']:.2f}, sev: {row['severity_score']:.2f}, {ts} UTC)"
            )
        return "\n".join(lines)

    # ── LLM-based extraction ──────────────────────────────────────────────

    async def _extract_report(self, message: str, language: str) -> Dict:
        """Extract structured fields from free-text using the LLM."""
        system_prompt = (
            "You are a disaster report extractor for Sri Lanka.\n"
            "Extract structured information from the user message and return ONLY a valid JSON object.\n"
            "Fields to extract:\n"
            "  report_domain:         one of [hazard, infrastructure, regulatory, safety, unknown]\n"
            "  hazard_type:           one of [landslide, flood, erosion, drainage, mixed, other, unknown]\n"
            "  category:              short normalized English label (e.g. 'slope crack', 'drain blockage')\n"
            "  location_text:         place name from message in English or as written, or null if not mentioned\n"
            "  description:           1-2 sentence English summary of the observation\n"
            "  people_at_risk:        true if message mentions people, houses, schools, roads; false otherwise\n"
            "  ongoing:               true if implies the situation is happening now; false otherwise\n"
            "  hazard_scale:          one of [minor, moderate, major, unknown]\n"
            "  infrastructure_damage: true if road, wall, culvert, or bridge is mentioned as damaged\n"
            "Return ONLY the JSON object. No explanation, no markdown fences."
        )
        try:
            result = await self.llm.ainvoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=message),
            ])
            raw = result.content.strip()
            # Strip markdown code fences if the model added them
            if raw.startswith("```"):
                parts = raw.split("```")
                raw = parts[1] if len(parts) > 1 else parts[0]
                if raw.startswith("json"):
                    raw = raw[4:]
            return json.loads(raw.strip())
        except Exception as exc:
            print(f"[reporter] LLM extraction error: {exc}")
            return self._fallback_extraction(message)

    def _fallback_extraction(self, message: str) -> Dict:
        """Deterministic keyword fallback when LLM extraction fails."""
        domain = "unknown"
        hazard_type = "unknown"

        if _contains_indicators(message, [LANDSLIDE_INDICATORS]):
            domain, hazard_type = "hazard", "landslide"
        elif _contains_indicators(message, [FLOOD_INDICATORS]):
            domain, hazard_type = "hazard", "flood"
        elif _contains_indicators(message, [INFRASTRUCTURE_INDICATORS]):
            domain = "infrastructure"
        elif _contains_indicators(message, [REGULATORY_INDICATORS]):
            domain = "regulatory"

        return {
            "report_domain":    domain,
            "hazard_type":      hazard_type,
            "category":         hazard_type if hazard_type != "unknown" else domain,
            "location_text":    None,
            "description":      message[:200],
            "people_at_risk":   _contains_indicators(message, [EXPOSURE_INDICATORS]),
            "ongoing":          _contains_indicators(message, [IMMEDIACY_INDICATORS]),
            "hazard_scale":     "unknown",
            "infrastructure_damage": _contains_indicators(message, [INFRASTRUCTURE_INDICATORS]),
        }

    # ── Confidence scoring ────────────────────────────────────────────────

    def _score_confidence(self, extracted: Dict, phone_number: str) -> float:
        """
        Dimensions (spec Table 4):
          completeness  0.30
          plausibility  0.20
          triangulation 0.30  ← now Bayesian source-credibility weighted
          (evidence skipped in Phase 1 — text only, no attachment analysis)
        """
        score = 0.0

        # Completeness
        if extracted.get("location_text"):
            score += 0.15
        if extracted.get("hazard_type") and extracted["hazard_type"] != "unknown":
            score += 0.10
        desc = extracted.get("description") or ""
        if len(desc) > 20:
            score += 0.05

        # Plausibility
        score += self._check_plausibility(extracted)

        # Bayesian source-credibility weighted triangulation
        score += self._check_triangulation_bayesian(extracted, phone_number)

        return min(score, 1.0)

    def _check_plausibility(self, extracted: Dict) -> float:
        """Phase-1: district / locality lookup + Open-Meteo rainfall context."""
        loc = (extracted.get("location_text") or "").lower()
        if not loc:
            return 0.0

        hazard = extracted.get("hazard_type", "")
        domain = extracted.get("report_domain", "")

        base = 0.0
        if hazard == "landslide" or domain == "hazard":
            for district in LANDSLIDE_PRONE_DISTRICTS:
                if district in loc:
                    base = 0.15
                    break

        if hazard in ("flood", "drainage") or "flood" in loc:
            for locality in FLOOD_PRONE_LOCALITIES:
                if locality in loc:
                    base = 0.15
                    break

        # Temporal rainfall bonus: if recent heavy rain recorded for this
        # location, raise plausibility by up to 0.05 (capped at 0.20 total).
        # This is a synchronous call that checks a short-lived in-memory cache
        # updated by the async method called during report processing.
        rainfall_bonus = self._get_rainfall_bonus_sync(loc, hazard)
        return min(base + rainfall_bonus, 0.20)

    def _get_rainfall_bonus_sync(self, loc: str, hazard: str) -> float:
        """
        Return a small plausibility bonus (0.0 \u2013 0.05) if the rainfall cache
        shows recent heavy precipitation for the matched district.
        Updated by _fetch_rainfall_for_location() called during extraction.
        """
        if hazard not in ("flood", "landslide", "drainage", "erosion"):
            return 0.0
        for district, mm in self._rainfall_cache.items():
            if district in loc:
                # > 50 mm/day = heavy rain in Sri Lanka context
                if mm >= 50:
                    return 0.05
                if mm >= 20:
                    return 0.02
        return 0.0

    async def _fetch_rainfall_for_location(self, loc: str) -> None:
        """
        Async fetch of today's precipitation from Open-Meteo for the district
        closest to the reported location.  Updates self._rainfall_cache.
        Free API, no key required.
        """
        loc_lower = loc.lower()
        coords = None
        matched_district = None
        for district, latlon in _DISTRICT_COORDS.items():
            if district in loc_lower:
                coords = latlon
                matched_district = district
                break

        if not coords:
            return

        lat, lon = coords
        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            f"&daily=precipitation_sum&timezone=Asia%2FColombo&forecast_days=1"
        )
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        precip_list = data.get("daily", {}).get("precipitation_sum", [0])
                        mm = precip_list[0] if precip_list else 0
                        self._rainfall_cache[matched_district] = mm or 0
                        print(
                            f"[reporter] rainfall {matched_district}: {mm:.1f} mm today"
                        )
        except Exception as exc:
            print(f"[reporter] _fetch_rainfall_for_location error: {exc}")

    def _get_user_reliability(self, user_hash: str) -> float:
        """Return the stored reliability score for a user, or the default prior."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute(
                    "SELECT reliability FROM user_reliability WHERE user_hash = ?",
                    (user_hash,)
                ).fetchone()
            return row[0] if row else _DEFAULT_RELIABILITY
        except Exception as exc:
            print(f"[reporter] _get_user_reliability error: {exc}")
            return _DEFAULT_RELIABILITY

    def _check_spatial_independence(
        self, user_hash: str, user_hash_candidate: str, loc_token: str
    ) -> bool:
        """
        Return True if user_hash_candidate is a spatially independent reporter
        (different identity AND same location cluster).

        Sybil-resistance rule: a single user_hash cannot corroborate their own
        report — repeated self-reports are linked to the same case and excluded
        from triangulation, as per spec Section 11 (edge-case table).
        """
        return user_hash_candidate != user_hash

    def _check_triangulation_bayesian(self, extracted: Dict, phone_number: str) -> float:
        """
        Bayesian source-credibility weighted triangulation (TruthFinder model).

        Algorithm:
          1. Find all recent, independent corroborating reports for this
             (domain, hazard_type, location) cluster within the last 12 hours.
          2. Exclude reports from the same user_hash (Sybil-resistance).
          3. For each independent corroborating reporter, retrieve their
             reliability score r_u.
          4. Combine using the TruthFinder formula:

               P(true) = prod(r_u) / [prod(r_u) + prod(1-r_u)]

          5. Scale to the [0, 0.30] contribution band for the triangulation
             dimension.

        With no corroborators: returns 0.0.
        With 1 corroborator at default reliability (0.5): returns ~0.15.
        With 2+ corroborators at high reliability: approaches 0.30.

        References:
          Yin et al. (2008) TruthFinder, VLDB.
          Li et al. (2016) Survey on Truth Discovery, ACM SIGKDD.
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=12)).isoformat()
        loc = (extracted.get("location_text") or "").lower()
        domain = extracted.get("report_domain", "unknown")
        hazard = extracted.get("hazard_type", "unknown")
        current_user_hash = _hash_phone(phone_number)

        if not loc or domain == "unknown":
            return 0.0

        loc_token = next((w for w in loc.split() if len(w) > 2), "")
        if not loc_token:
            return 0.0

        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute("""
                    SELECT DISTINCT user_hash FROM community_reports
                    WHERE timestamp >= ?
                      AND report_domain = ?
                      AND (hazard_type = ? OR ? = 'unknown')
                      AND location_text LIKE ?
                      AND status NOT IN ('closed', 'archived')
                """, (cutoff, domain, hazard, hazard, f"%{loc_token}%")).fetchall()
        except Exception as exc:
            print(f"[reporter] triangulation_bayesian query error: {exc}")
            return 0.0

        # Filter to spatially independent reporters (exclude self)
        independent_hashes = [
            r["user_hash"] for r in rows
            if self._check_spatial_independence(current_user_hash, r["user_hash"], loc_token)
        ]

        if not independent_hashes:
            return 0.0

        # TruthFinder combination: P(true) = Π r_u / [Π r_u + Π (1-r_u)]
        prod_r   = 1.0
        prod_1_r = 1.0
        for uh in independent_hashes:
            r = self._get_user_reliability(uh)
            # Clamp to avoid log(0) instability at extremes
            r = max(0.05, min(0.95, r))
            prod_r   *= r
            prod_1_r *= (1.0 - r)

        denom = prod_r + prod_1_r
        p_true = prod_r / denom if denom > 0 else 0.0

        # Scale p_true (0→1) to the [0, 0.30] triangulation band
        triangulation_score = round(p_true * 0.30, 4)
        print(
            f"[reporter] triangulation_bayesian: {len(independent_hashes)} independent "
            f"reporters → p_true={p_true:.3f} → tri_score={triangulation_score:.3f}"
        )
        return triangulation_score

    def update_user_reliability(
        self, user_hash: str, verified: bool, note: str = ""
    ) -> None:
        """
        Update a user's Bayesian reliability score after a report outcome is known.

        Called from:
          - Admin panel when a report is manually verified or rejected.
          - Scheduler when a report reaches its retention expiry unvalidated
            (treated as weak rejection, weight 0.5).

        Update rule (TruthFinder log-odds update):
          If verified:  reliability = reliability + α*(1 - reliability)
          If rejected:  reliability = reliability - α*reliability
          where α = 0.3 (learning rate — tunable for thesis evaluation).

        The score is clamped to [0.05, 0.95] to prevent lock-in.
        """
        ALPHA = 0.3
        now = datetime.now(timezone.utc).isoformat()
        try:
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute(
                    "SELECT reliability, n_reports, n_verified, n_rejected "
                    "FROM user_reliability WHERE user_hash = ?",
                    (user_hash,)
                ).fetchone()

                if row:
                    r, n_rep, n_ver, n_rej = row
                else:
                    r, n_rep, n_ver, n_rej = _DEFAULT_RELIABILITY, 0, 0, 0

                if verified:
                    r = r + ALPHA * (1.0 - r)
                    n_ver += 1
                else:
                    r = r - ALPHA * r
                    n_rej += 1

                r = max(0.05, min(0.95, r))

                conn.execute("""
                    INSERT INTO user_reliability
                        (user_hash, reliability, n_reports, n_verified, n_rejected, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(user_hash) DO UPDATE SET
                        reliability = excluded.reliability,
                        n_verified  = excluded.n_verified,
                        n_rejected  = excluded.n_rejected,
                        updated_at  = excluded.updated_at
                """, (user_hash, round(r, 4), n_rep, n_ver, n_rej, now))
                conn.commit()
            print(
                f"[reporter] reliability updated: {user_hash[:8]}… "
                f"{'verified' if verified else 'rejected'} → r={r:.3f} "
                f"({note})"
            )
        except Exception as exc:
            print(f"[reporter] update_user_reliability error: {exc}")

    def _upsert_user_report_count(self, user_hash: str) -> None:
        """Increment n_reports for a user when a new report is stored."""
        now = datetime.now(timezone.utc).isoformat()
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT INTO user_reliability
                        (user_hash, reliability, n_reports, n_verified, n_rejected, updated_at)
                    VALUES (?, ?, 1, 0, 0, ?)
                    ON CONFLICT(user_hash) DO UPDATE SET
                        n_reports  = n_reports + 1,
                        updated_at = excluded.updated_at
                """, (user_hash, _DEFAULT_RELIABILITY, now))
                conn.commit()
        except Exception as exc:
            print(f"[reporter] _upsert_user_report_count error: {exc}")

    # ── Severity scoring ──────────────────────────────────────────────────

    def _score_severity(self, extracted: Dict) -> float:
        """
        Dimensions (spec Table 5):
          exposure              0.40
          infrastructure impact 0.20
          hazard scale          0.30
          immediacy             0.10
        """
        score = 0.0

        if extracted.get("people_at_risk"):
            score += 0.40

        if extracted.get("infrastructure_damage"):
            score += 0.20

        scale = extracted.get("hazard_scale", "unknown")
        if scale == "major":
            score += 0.30
        elif scale == "moderate":
            score += 0.15
        elif scale == "minor":
            score += 0.05

        if extracted.get("ongoing"):
            score += 0.10

        return min(score, 1.0)

    # ── Decision engine ───────────────────────────────────────────────────

    @staticmethod
    def _decide_action(confidence: float, severity: float) -> str:
        """
        Confidence × Severity matrix (spec Table 6).

        confidence < 0.40                     → store_only
        0.40 <= confidence < 0.70, sev < 0.30 → monitor
        0.40 <= confidence < 0.70, sev >= 0.30 → flag_review
        confidence >= 0.70, sev < 0.70        → monitor
        confidence >= 0.70, sev >= 0.70       → escalate
        """
        if confidence < 0.40:
            return "store_only"
        if confidence < 0.70:
            return "flag_review" if severity >= 0.30 else "monitor"
        return "escalate" if severity >= 0.70 else "monitor"

    # ── Storage ───────────────────────────────────────────────────────────

    def _store_report(self, record: Dict) -> None:
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT INTO community_reports
                        (report_id, timestamp, user_hash, language, report_domain,
                         hazard_type, category, location_text, description,
                         confidence_score, severity_score, action, status,
                         people_at_risk, ongoing, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    record["report_id"],   record["timestamp"],    record["user_hash"],
                    record["language"],    record["report_domain"], record["hazard_type"],
                    record["category"],    record["location_text"], record["description"],
                    record["confidence_score"], record["severity_score"],
                    record["action"],      record["status"],
                    record["people_at_risk"], record["ongoing"], record["created_at"],
                ))
                conn.execute("""
                    INSERT INTO report_status_log
                        (report_id, old_status, new_status, changed_at, note)
                    VALUES (?, ?, ?, ?, ?)
                """, (record["report_id"], None, "new", record["created_at"], "initial"))
                conn.commit()
            print(
                f"[reporter] stored {record['report_id']} "
                f"domain={record['report_domain']} action={record['action']} "
                f"conf={record['confidence_score']:.2f} sev={record['severity_score']:.2f}"
            )
            # Increment report count in user_reliability table
            self._upsert_user_report_count(record["user_hash"])
        except Exception as exc:
            print(f"[reporter] store error: {exc}")

    # ── User-facing messages ──────────────────────────────────────────────

    @staticmethod
    def _clarification_prompt(language: str, field: str) -> str:
        """Single targeted follow-up when a critical field is absent."""
        msgs = {
            "en": (
                "📍 Thank you for the report. Could you share the location or nearest "
                "landmark? (e.g. village name, road name — or tap 📎 and choose Location)"
            ),
            "si": (
                "📍 වාර්තාව ස්තූතියි. ස්ථානය හෝ ළඟම ස්ථලය බෙදාගත හැකිද? "
                "(උදා: ගමේ නම, පාරේ නම — හෝ 📎 ඔබා ස්ථානය යවන්න)"
            ),
            "ta": (
                "📍 அறிக்கைக்கு நன்றி. இடம் அல்லது அருகிலுள்ள இடத்தின் பெயரை "
                "தெரிவிக்க முடியுமா? (எ.கா: கிராமம், சாலை — அல்லது 📎 அழுத்தி இடம் அனுப்பவும்)"
            ),
        }
        return msgs.get(language, msgs["en"])

    @staticmethod
    def _acknowledgement(language: str, report_id: str, action: str, severity: float) -> str:
        """User-facing acknowledgement based on decision action."""
        if action == "escalate":
            return {
                "en": (
                    f"🚨 *Report received* (ID: {report_id})\n\n"
                    "This has been flagged as urgent and the monitoring team has been notified. "
                    "If you are in immediate danger, please move to safety now.\n\n"
                    "Your report helps protect your community."
                ),
                "si": (
                    f"🚨 *වාර්තාව ලැබුණි* (ID: {report_id})\n\n"
                    "මෙය හදිසි ලෙස සලකා නිරීක්ෂණ කණ්ඩායම දැනුම් දී ඇත. "
                    "ඔබ අනතුරේ සිටී නම් ඉක්මනින් ආරක්ෂිත ස්ථානයකට යන්න."
                ),
                "ta": (
                    f"🚨 *அறிக்கை பெறப்பட்டது* (ID: {report_id})\n\n"
                    "இது அவசரமாக கொடியிடப்பட்டு கண்காணிப்பு குழுவிற்கு தெரிவிக்கப்பட்டது. "
                    "நீங்கள் ஆபத்தில் இருந்தால் உடனடியாக பாதுகாப்பான இடத்திற்கு செல்லுங்கள்."
                ),
            }.get(language, "")  # falls through to default below if language missing

        if action in ("flag_review", "monitor"):
            return {
                "en": (
                    f"✅ *Report received* (ID: {report_id})\n\n"
                    "Thank you. Your observation has been recorded and added to our "
                    "monitoring queue. If the situation worsens, please send another update."
                ),
                "si": (
                    f"✅ *වාර්තාව ලැබුණි* (ID: {report_id})\n\n"
                    "ස්තූතියි. ඔබේ නිරීක්ෂණය වාර්තා කර නිරීක්ෂණ පෝලිමට "
                    "එකතු කරන ලදී. තත්ත්වය නරක් වුවහොත් නැවත යවන්න."
                ),
                "ta": (
                    f"✅ *அறிக்கை பெறப்பட்டது* (ID: {report_id})\n\n"
                    "நன்றி. உங்கள் கவனிப்பு பதிவு செய்யப்பட்டு கண்காணிப்பு "
                    "வரிசையில் சேர்க்கப்பட்டது. நிலைமை மோசமானால் மீண்டும் அனுப்பவும்."
                ),
            }.get(language, "")

        # store_only
        return {
            "en": (
                f"✅ *Report noted* (ID: {report_id})\n\n"
                "Thank you for letting us know. Your report has been stored. "
                "Sharing more details (exact location, what you observe) helps us respond better."
            ),
            "si": (
                f"✅ *වාර්තාව සටහන් කරන ලදී* (ID: {report_id})\n\n"
                "ස්තූතියි. ඔබේ වාර්තාව ගබඩා කරන ලදී. "
                "ස්ථානය, දකින දේ ගැන වැඩිදුර තොරතුරු ලබාදිය හැකිනම් ඉතා ඉදිරිගාමී වේ."
            ),
            "ta": (
                f"✅ *அறிக்கை குறிப்பிடப்பட்டது* (ID: {report_id})\n\n"
                "தகவலுக்கு நன்றி. உங்கள் அறிக்கை சேமிக்கப்பட்டது. "
                "இடம் மற்றும் கண்ட விவரங்கள் தர முடியுமா?"
            ),
        }.get(language, f"✅ Report noted (ID: {report_id}). Thank you.")
