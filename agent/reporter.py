"""
Community Reporting Module
--------------------------
Converts unstructured citizen observations sent via WhatsApp into structured,
governed mitigation intelligence stored in a separate SQLite database.

Pipeline:  text (+ photo) → schema-validated LLM extraction / vision assessment
           → visual evidence policy → confidence/severity scoring
           → decision policy → SQLite store with scoring provenance → acknowledgement

Contributor reputation ("reliability") is a bounded exponential moving average
of human review outcomes; corroboration combines other contributors'
reputations by product-of-odds aggregation. Both are heuristics: neither is a
Beta posterior, the TruthFinder algorithm, or a calibrated incident probability.

The community report store is ALWAYS separate from the authoritative RAG
vectorstore. Community observations only feed the advisory pipeline as
read-only supplementary context with explicit source labelling.
"""

import asyncio
import base64
import hashlib
import hmac
import json
import math
import mimetypes
import os
import sqlite3
import time
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

_DEFAULT_RELIABILITY = 0.5  # starting reputation for contributors with no reviewed reports

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

def _legacy_hash_phone(phone_number: str) -> str:
    """Unkeyed SHA-256 prefix used before keyed pseudonyms existed."""
    return hashlib.sha256(phone_number.encode("utf-8")).hexdigest()[:16]


def _hash_phone(phone_number: str) -> str:
    """
    Contributor pseudonym. With REPORTER_ID_KEY set this is a keyed HMAC, so
    the identifier cannot be reversed by enumerating the phone-number space;
    without it, the legacy unkeyed prefix is returned.
    """
    key = Config.REPORTER_ID_KEY
    if not key:
        return _legacy_hash_phone(phone_number)
    digest = hmac.new(key.encode("utf-8"), phone_number.encode("utf-8"), hashlib.sha256)
    return "k1_" + digest.hexdigest()[:32]


# ── Versioned policies and pure scoring functions ────────────────────────────

POLICY_BASELINE = "baseline-v1"
POLICY_CANDIDATE = "candidate-v2"
VISUAL_POLICY_VERSION = "visual-v2"
PROVENANCE_SCHEMA = "scoring-provenance-v1"

RELIABILITY_ALPHA = 0.3
RELIABILITY_MIN, RELIABILITY_MAX = 0.05, 0.95
CORROBORATION_WEIGHT = 0.30
CORROBORATION_WINDOW_HOURS = 12

# Highest priority first. A report never receives a lower-priority action
# because one of its scores increased (checked in tests/test_reporting.py).
ACTION_PRIORITY = ["escalate", "expedited_review", "flag_review", "monitor", "store_only"]

SUPPORTED_IMAGE_MIMES = {"image/jpeg", "image/png", "image/webp", "image/gif"}


class SchemaError(ValueError):
    """Model output is not a JSON object of the expected shape."""


def parse_model_json(raw: Any) -> Dict[str, Any]:
    """Parse a model reply into a dict, tolerating a markdown code fence."""
    if not isinstance(raw, str):
        raise SchemaError("reply is not text")
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.lower().startswith("json"):
            text = text[4:]
    try:
        value = json.loads(text.strip())
    except (json.JSONDecodeError, ValueError) as exc:
        raise SchemaError(f"malformed JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise SchemaError("JSON value is not an object")
    return value


# field -> (kind, allowed values or (lo, hi) bounds, default)
TEXT_SCHEMA: Dict[str, Tuple[str, Any, Any]] = {
    "report_domain": ("enum", {"hazard", "infrastructure", "regulatory", "safety", "unknown"}, "unknown"),
    "hazard_type": ("enum", {"landslide", "flood", "erosion", "drainage", "mixed", "other", "unknown"}, "unknown"),
    "category": ("str", None, None),
    "location_text": ("str_or_null", None, None),
    "location_specific": ("bool", None, False),
    "clarification_question": ("str_or_null", None, None),
    "description": ("str", None, ""),
    "people_at_risk": ("bool", None, False),
    "ongoing": ("bool", None, False),
    "hazard_scale": ("enum", {"minor", "moderate", "major", "unknown"}, "unknown"),
    "infrastructure_damage": ("bool", None, False),
}

IMAGE_SCHEMA: Dict[str, Tuple[str, Any, Any]] = {
    "hazard_detected": ("bool", None, None),
    "hazard_category": ("enum", {"drainage_issue", "slope_instability", "ground_cracking",
                                  "localised_flooding", "access_obstruction", "other", "none"}, None),
    "possible_condition": ("str", None, ""),
    "severity_from_image": ("enum", {"none", "low", "moderate", "high"}, "none"),
    "report_image_consistency": ("enum", {"high", "moderate", "low", "contradiction"}, None),
    "evidence_score": ("number", (0.0, 0.20), None),
    "summary": ("str", None, ""),
}
# A missing/invalid core field makes the whole visual assessment unusable.
IMAGE_CORE_FIELDS = ("hazard_detected", "hazard_category", "report_image_consistency", "evidence_score")
EVIDENCE_TIERS = [0.00, 0.05, 0.10, 0.15, 0.20]


def validate_against_schema(raw: Dict[str, Any], schema: Dict[str, Tuple[str, Any, Any]]
                            ) -> Tuple[Dict[str, Any], List[str]]:
    """
    Coerce a parsed model reply to the schema. Invalid or missing fields take
    the schema default and are reported in `issues` as "<problem>:<field>".
    Strings "true"/"false" and numeric strings are accepted but reported.
    """
    clean: Dict[str, Any] = {}
    issues: List[str] = []
    for field, (kind, spec, default) in schema.items():
        if field not in raw or raw[field] is None and kind != "str_or_null":
            clean[field] = default
            issues.append(f"missing:{field}")
            continue
        value = raw[field]
        if kind == "bool":
            if isinstance(value, bool):
                clean[field] = value
            elif isinstance(value, str) and value.strip().lower() in ("true", "false"):
                clean[field] = value.strip().lower() == "true"
                issues.append(f"coerced:{field}")
            else:
                clean[field] = default
                issues.append(f"invalid:{field}")
        elif kind == "enum":
            norm = value.strip().lower() if isinstance(value, str) else None
            if norm in spec:
                clean[field] = norm
            else:
                clean[field] = default
                issues.append(f"invalid:{field}")
        elif kind == "number":
            number: Optional[float] = None
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                number = float(value)
            elif isinstance(value, str):
                try:
                    number = float(value.strip())
                    issues.append(f"coerced:{field}")
                except ValueError:
                    number = None
            lo, hi = spec
            if number is None or not math.isfinite(number) or not lo <= number <= hi:
                clean[field] = default
                issues.append(f"invalid:{field}")
            else:
                clean[field] = number
        else:  # str / str_or_null
            if isinstance(value, str):
                stripped = value.strip()
                clean[field] = stripped if stripped or kind == "str" else None
            elif value is None:
                clean[field] = None
            else:
                clean[field] = default
                issues.append(f"invalid:{field}")
    return clean, issues


def _logit(p: float) -> float:
    return math.log(p) - math.log1p(-p)


def stable_sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    z = math.exp(x)
    return z / (1.0 + z)


def aggregate_reliabilities(reliabilities: List[float]) -> Optional[float]:
    """
    Product-of-odds aggregation  prod(r) / [prod(r) + prod(1-r)], computed as
    sigmoid(sum(logit(r))) so it neither underflows nor overflows for large
    contributor sets. Each r is clipped to [0.05, 0.95]. None for an empty set.
    This is an agreement score, not a calibrated probability.
    """
    if not reliabilities:
        return None
    total = sum(_logit(min(RELIABILITY_MAX, max(RELIABILITY_MIN, r))) for r in reliabilities)
    return stable_sigmoid(total)


def reliability_update(r: float, verified: bool) -> float:
    """Bounded EMA: round4(clip(0.7*r + 0.3*y, 0.05, 0.95)), y = 1 if verified else 0."""
    y = 1.0 if verified else 0.0
    return round(min(RELIABILITY_MAX, max(RELIABILITY_MIN, (1 - RELIABILITY_ALPHA) * r + RELIABILITY_ALPHA * y)), 4)


def quantize_score(x: float) -> float:
    """Remove binary floating-point residue from sums of decimal weights."""
    return round(x, 6)


def decide_action_baseline(confidence: float, severity: float) -> str:
    """Original confidence × severity matrix (spec Table 6), kept unchanged."""
    if confidence < 0.40:
        return "store_only"
    if confidence < 0.70:
        return "flag_review" if severity >= 0.30 else "monitor"
    return "escalate" if severity >= 0.70 else "monitor"


def decide_action_candidate(confidence: float, severity: float) -> str:
    """
    Candidate policy, evaluated in shadow mode unless ACTIVE_DECISION_POLICY
    selects it. Rules are checked in ACTION_PRIORITY order:
      escalate          severity >= 0.70 and confidence >= 0.70
      expedited_review  severity >= 0.70 and confidence <  0.70
      flag_review       severity >= 0.30 and confidence >= 0.40
      monitor           confidence >= 0.40
      store_only        otherwise
    Unlike the baseline, a high-severity report is never store_only, and raising
    confidence never moves a report out of human review into monitoring.
    """
    if severity >= 0.70:
        return "escalate" if confidence >= 0.70 else "expedited_review"
    if confidence >= 0.40:
        return "flag_review" if severity >= 0.30 else "monitor"
    return "store_only"


DECISION_POLICIES = {POLICY_BASELINE: decide_action_baseline, POLICY_CANDIDATE: decide_action_candidate}

# hazard_category (vision) -> (report_domain, hazard_type)
IMAGE_HAZARD_MAPPING: Dict[str, Tuple[str, str]] = {
    "drainage_issue":     ("infrastructure", "drainage"),
    "slope_instability":  ("hazard", "landslide"),
    "ground_cracking":    ("hazard", "landslide"),
    "localised_flooding": ("hazard", "flood"),
    "access_obstruction": ("infrastructure", "other"),
}
_SEVERITY_TO_SCALE = {"low": "minor", "moderate": "moderate", "high": "major"}

# Ablation conditions for the visual channel (production uses VISUAL_FULL).
VISUAL_TEXT_ONLY = "text_only"        # A: image ignored
VISUAL_SCORE_ONLY = "score_only"      # B: evidence score, no field backfill
VISUAL_FULL = "score_backfill"        # C: evidence score + backfill
VISUAL_LEGACY = "legacy_v1"           # pre-visual-v2 behaviour, for comparison only


def classify_visual_outcome(analysis: Dict[str, Any]) -> str:
    """unavailable | unusable | no_hazard | contradiction | supporting"""
    if analysis.get("status") != "ok":
        return "unavailable"
    if analysis.get("evidence_score", 0.0) <= 0.0:
        return "unusable"
    if not analysis.get("hazard_detected") or analysis.get("hazard_category") == "none":
        return "no_hazard"
    if analysis.get("report_image_consistency") == "contradiction":
        return "contradiction"
    return "supporting"


def apply_visual_policy(extracted: Dict[str, Any], analysis: Optional[Dict[str, Any]],
                        mode: str = VISUAL_FULL) -> Tuple[Dict[str, Any], float, List[Dict[str, Any]]]:
    """
    Return (updated copy of extracted fields, visual confidence contribution,
    backfill decisions). Policy visual-v2: only a "supporting" image adds its
    evidence score; hazard type is backfilled only when the text left it
    unknown and the image is supporting with high/moderate consistency;
    hazard scale likewise. Text-derived values are never overwritten.
    """
    out = dict(extracted)
    decisions: List[Dict[str, Any]] = []
    if not analysis or mode == VISUAL_TEXT_ONLY:
        return out, 0.0, decisions

    if mode == VISUAL_LEGACY:
        failed = analysis.get("status") != "ok"
        contribution = 0.05 if failed else analysis.get("evidence_score", 0.0)
        mapped = IMAGE_HAZARD_MAPPING.get(analysis.get("hazard_category"))
        if not failed and mapped and out.get("hazard_type") in (None, "unknown"):
            out["report_domain"], out["hazard_type"] = mapped
            out["category"] = analysis.get("possible_condition") or analysis.get("hazard_category")
        sev = analysis.get("severity_from_image", "none")
        if not failed and out.get("hazard_scale", "unknown") == "unknown" and sev != "none":
            out["hazard_scale"] = _SEVERITY_TO_SCALE.get(sev, "unknown")
        return out, contribution, decisions

    outcome = classify_visual_outcome(analysis)
    contribution = analysis["evidence_score"] if outcome == "supporting" else 0.0
    eligible = outcome == "supporting" and analysis.get("report_image_consistency") in ("high", "moderate")

    def decide(field: str, text_value: Any, image_value: Any, text_missing: bool) -> bool:
        if mode != VISUAL_FULL:
            reason, accepted = "backfill disabled (score-only condition)", False
        elif not text_missing:
            reason, accepted = "text value present; text takes precedence", False
        elif image_value in (None, "unknown", "none"):
            reason, accepted = "image provides no value for this field", False
        elif outcome != "supporting":
            reason, accepted = f"image outcome is {outcome}", False
        elif not eligible:
            reason, accepted = f"report/image consistency is {analysis.get('report_image_consistency')}", False
        else:
            reason, accepted = "text unknown; supporting image with high/moderate consistency", True
        decisions.append({"field": field, "accepted": accepted, "reason": reason,
                          "text_value": text_value, "image_value": image_value})
        return accepted

    mapped = IMAGE_HAZARD_MAPPING.get(analysis.get("hazard_category"))
    if decide("hazard_type", out.get("hazard_type"), mapped[1] if mapped else None,
              out.get("hazard_type") in (None, "unknown")):
        if out.get("report_domain") in (None, "unknown"):
            out["report_domain"] = mapped[0]
        out["hazard_type"] = mapped[1]
        if out.get("category") in (None, "", "unknown", "general"):
            out["category"] = analysis.get("possible_condition") or analysis.get("hazard_category")

    image_scale = _SEVERITY_TO_SCALE.get(analysis.get("severity_from_image"))
    if decide("hazard_scale", out.get("hazard_scale"), image_scale,
              out.get("hazard_scale", "unknown") in (None, "unknown")):
        out["hazard_scale"] = image_scale

    return out, contribution, decisions


def severity_components(extracted: Dict[str, Any]) -> Dict[str, float]:
    """Spec Table 5: exposure 0.40, infrastructure 0.20, hazard scale 0.30, immediacy 0.10."""
    scale = extracted.get("hazard_scale", "unknown")
    return {
        "exposure": 0.40 if extracted.get("people_at_risk") else 0.0,
        "infrastructure": 0.20 if extracted.get("infrastructure_damage") else 0.0,
        "hazard_scale": {"major": 0.30, "moderate": 0.15, "minor": 0.05}.get(scale, 0.0),
        "immediacy": 0.10 if extracted.get("ongoing") else 0.0,
    }


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
      extract → validate → visual policy → confidence/severity score → decide
      → store (with scoring provenance) → acknowledge

    The community_reports SQLite database is completely separate from the
    authoritative FAISS vectorstore used by RAGSystem.
    """

    EXTRACTION_PROMPT = (
        "You are a disaster report extractor for Sri Lanka.\n"
        "Extract structured information from the user message and return ONLY a valid JSON object.\n"
        "Fields to extract:\n"
        "  report_domain:         one of [hazard, infrastructure, regulatory, safety, unknown]\n"
        "  hazard_type:           one of [landslide, flood, erosion, drainage, mixed, other, unknown]\n"
        "  category:              short normalized English label (e.g. 'slope crack', 'drain blockage')\n"
        "  location_text:         place name from message in English or as written, or null if not mentioned\n"
        "  location_specific:     true only if location_text names something a responder could actually\n"
        "                         navigate to (a village/town/city, road, junction, landmark, or GPS\n"
        "                         coordinates). false if location_text is null, or is only a vague/generic\n"
        "                         self-reference such as 'my hometown', 'my home city', 'here', 'nearby',\n"
        "                         'this area' with no actual place name attached.\n"
        "  clarification_question: if location_specific is false, write ONE short, friendly follow-up\n"
        "                         question — in the SAME language as the user's message — asking them to\n"
        "                         name the specific village/town, road, or nearest landmark (they may also\n"
        "                         share a WhatsApp location pin). null if location_specific is true.\n"
        "  description:           1-2 sentence English summary of the observation\n"
        "  people_at_risk:        true if message mentions people, houses, schools, roads; false otherwise\n"
        "  ongoing:               true if implies the situation is happening now; false otherwise\n"
        "  hazard_scale:          one of [minor, moderate, major, unknown]\n"
        "  infrastructure_damage: true if road, wall, culvert, or bridge is mentioned as damaged\n"
        "Return ONLY the JSON object. No explanation, no markdown fences."
    )

    VISION_PROMPT_TEMPLATE = (
        "You are assessing a photo attached to a disaster/hazard community report.\n"
        "Report description: {description}\n\n"
        "Return ONLY a JSON object with this exact shape:\n"
        "{{\n"
        '  "hazard_detected": <true/false>,\n'
        '  "hazard_category": <one of "drainage_issue", "slope_instability", '
        '"ground_cracking", "localised_flooding", "access_obstruction", "other", "none">,\n'
        '  "possible_condition": "<short phrase, e.g. poor_drainage_or_possible_blockage>",\n'
        '  "severity_from_image": <one of "none", "low", "moderate", "high">,\n'
        '  "report_image_consistency": <one of "high", "moderate", "low", "contradiction">,\n'
        '  "evidence_score": <one of 0.00, 0.05, 0.10, 0.15, 0.20 - see rubric below>,\n'
        '  "summary": "<one short sentence>"\n'
        "}}\n\n"
        "evidence_score rubric:\n"
        "0.00 - No image / unusable image\n"
        "0.05 - Image visible but does not clearly support the report\n"
        "0.10 - Partially consistent evidence\n"
        "0.15 - Clear evidence consistent with the report\n"
        "0.20 - Strong, clear evidence directly supporting the report"
    )

    # Kept for callers that referenced the class attributes.
    _EVIDENCE_TIERS = EVIDENCE_TIERS
    _IMAGE_HAZARD_MAPPING = IMAGE_HAZARD_MAPPING

    # Short, human-readable label for each hazard_category, per language —
    # used to tell the user what the photo itself showed.
    _HAZARD_CATEGORY_LABELS: Dict[str, Dict[str, str]] = {
        "drainage_issue":     {"en": "a drainage issue", "si": "ජල බැස්සීමේ ගැටළුවක්", "ta": "வடிகால் சிக்கல்"},
        "slope_instability":  {"en": "slope instability", "si": "බෑවුම අස්ථාවර වීමක්", "ta": "சரிவு உறுதியற்ற தன்மை"},
        "ground_cracking":    {"en": "ground cracking", "si": "බිම් ඉරිතැලීම්", "ta": "தரை விரிசல்"},
        "localised_flooding": {"en": "localised flooding", "si": "ප්‍රාදේශීය ගංවතුර", "ta": "உள்ளூர் வெள்ளம்"},
        "access_obstruction": {"en": "a road obstruction", "si": "මාර්ග අවහිරයක්", "ta": "சாலை தடை"},
    }

    def __init__(self):
        self.llm = ChatOpenAI(
            model=Config.MODEL_NAME,
            openai_api_key=Config.OPENAI_API_KEY,
            temperature=0.0,
        )
        self.db_path = Config.COMMUNITY_REPORTS_DB
        # {district: {"mm", "forecast_date", "fetched_at", ...}}; see _rainfall_context
        self._rainfall_cache: Dict[str, Dict[str, Any]] = {}
        self._migrated_legacy_ids: set = set()
        self._init_db()

    @staticmethod
    def prompt_digest(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]

    # ── Database setup ────────────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        """Autocommit connection; writers open explicit BEGIN IMMEDIATE transactions."""
        conn = sqlite3.connect(self.db_path, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        return conn

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
                    image_path       TEXT,
                    image_evidence_score REAL DEFAULT 0.0,
                    image_hazard_category TEXT,
                    created_at       TEXT NOT NULL
                )
            """)
            existing_cols = {
                row[1] for row in conn.execute("PRAGMA table_info(community_reports)").fetchall()
            }
            # image_evidence_score holds the visual contribution that counted
            # towards confidence (0 unless the image outcome was "supporting").
            for col, ddl in [
                ("image_path", "TEXT"),
                ("image_evidence_score", "REAL DEFAULT 0.0"),
                ("image_hazard_category", "TEXT"),
                ("source_message_id", "TEXT"),
                ("policy_version", "TEXT"),
                ("shadow_action", "TEXT"),
                ("review_outcome", "TEXT"),
                ("scoring_provenance", "TEXT"),
            ]:
                if col not in existing_cols:
                    conn.execute(f"ALTER TABLE community_reports ADD COLUMN {col} {ddl}")
            conn.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS uq_reports_source_message
                ON community_reports(source_message_id) WHERE source_message_id IS NOT NULL
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
            # Research audit log of agent tool calls (routing evaluation).
            conn.execute("""
                CREATE TABLE IF NOT EXISTS agent_tool_calls (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_hash  TEXT NOT NULL,
                    tool_name  TEXT NOT NULL,
                    tool_input TEXT,
                    called_at  TEXT NOT NULL
                )
            """)
            # Contributor reputation. reliability is a bounded EMA of review
            # outcomes, replayed from replay_base over review_events (see
            # _replay_reliability). replay_base carries forward any score that
            # existed before review events were recorded.
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
            rel_cols = {row[1] for row in conn.execute("PRAGMA table_info(user_reliability)").fetchall()}
            if "replay_base" not in rel_cols:
                conn.execute("ALTER TABLE user_reliability ADD COLUMN replay_base REAL")
                conn.execute("UPDATE user_reliability SET replay_base = reliability")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS review_events (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    report_id   TEXT NOT NULL,
                    user_hash   TEXT NOT NULL,
                    decision    TEXT NOT NULL CHECK (decision IN ('verified', 'false', 'retracted')),
                    reviewer    TEXT,
                    note        TEXT,
                    created_at  TEXT NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS ix_review_events_user ON review_events(user_hash)")
            conn.commit()

    # ── Contributor pseudonyms ────────────────────────────────────────────

    def _resolve_user_hash(self, phone_number: str) -> str:
        """
        Keyed pseudonym for this contributor. The first time a contributor is
        seen after REPORTER_ID_KEY is configured, rows stored under their
        legacy unkeyed hash are re-keyed in one transaction, so reliability
        histories and corroboration self-exclusion carry over.
        """
        new_id = _hash_phone(phone_number)
        legacy = _legacy_hash_phone(phone_number)
        if new_id == legacy or legacy in self._migrated_legacy_ids:
            return new_id
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            has_new_rel = conn.execute(
                "SELECT 1 FROM user_reliability WHERE user_hash = ?", (new_id,)).fetchone()
            for table in ("community_reports", "review_events", "agent_tool_calls"):
                conn.execute(f"UPDATE {table} SET user_hash = ? WHERE user_hash = ?", (new_id, legacy))
            if not has_new_rel:
                conn.execute("UPDATE user_reliability SET user_hash = ? WHERE user_hash = ?", (new_id, legacy))
            conn.execute("COMMIT")
            self._migrated_legacy_ids.add(legacy)
        except Exception as exc:
            conn.execute("ROLLBACK")
            print(f"[reporter] pseudonym migration error: {exc}")
        finally:
            conn.close()
        return new_id

    # ── Public API ────────────────────────────────────────────────────────

    async def process_report(
        self,
        phone_number: str,
        message: str,
        language: str,
        pending_report: Optional[Dict] = None,
        image_bytes: Optional[bytes] = None,
        image_mime: Optional[str] = None,
        message_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Main entry point called from the orchestrator and the agent tool.

        Returns a dict:
          {
            "response":             str,        # WhatsApp reply to send
            "report_id":            str | None,
            "needs_clarification":  bool,
            "clarification_field":  str | None,
            "pending_report":       dict | None, # carry forward if clarification needed
            "stored":               bool,        # True only after a committed write
          }
        """
        user_hash = self._resolve_user_hash(phone_number)
        if message_id:
            existing = self.find_report_by_message_id(message_id)
            if existing:
                return self._already_stored_result(existing, language)

        if pending_report:
            extracted = dict(pending_report)
            clarification_field = extracted.pop("_clarification_field", None)
            answer = message.strip()
            if clarification_field == "location" and answer:
                extracted["location_text"] = answer
                extracted["location_specific"] = True  # trust the user's direct answer, don't loop
                extracted["_location_source"] = "clarification_reply"
            elif clarification_field == "description" and answer:
                extracted["description"] = answer
        else:
            extracted = await self._extract_report(message, language)

        if image_bytes:
            if extracted.get("_image_analysis"):
                # One assessed image per report; a second photo during
                # clarification is not re-sent to the vision model.
                extracted["_images_not_analysed"] = extracted.get("_images_not_analysed", 0) + 1
            else:
                extracted["_image_analysis"] = await self._analyze_image_evidence(
                    image_bytes, image_mime, extracted.get("description") or message, language,
                )

        analysis = extracted.get("_image_analysis")
        fields, visual_contribution, backfill = apply_visual_policy(
            self._public_fields(extracted), analysis, VISUAL_FULL)

        # Only ask ONE follow-up: location is the most actionable missing field.
        if not fields.get("location_text") or not fields.get("location_specific", False):
            extracted["_clarification_field"] = "location"
            question = fields.get("clarification_question") or self._clarification_prompt(language, "location")
            return {
                "response": question,
                "report_id": None,
                "needs_clarification": True,
                "clarification_field": "location",
                "pending_report": extracted,
                "stored": False,
            }

        now = datetime.now(timezone.utc)
        rainfall = await self._fetch_rainfall_for_location(fields.get("location_text") or "")
        scoring = self.score_report(fields, user_hash, visual_contribution, now=now)

        report_id = f"RPT-{uuid.uuid4().hex[:8].upper()}"
        visual_outcome = classify_visual_outcome(analysis) if analysis else None
        provenance = {
            "schema": PROVENANCE_SCHEMA,
            "scored_at": now.isoformat(),
            "model_alias": Config.MODEL_NAME,
            "prompts": {
                "extraction": self.prompt_digest(self.EXTRACTION_PROMPT),
                "vision": self.prompt_digest(self.VISION_PROMPT_TEMPLATE),
            },
            "extraction": extracted.get("_extraction_meta"),
            "location_source": extracted.get("_location_source", "initial_message"),
            "visual": None if not analysis else {
                "policy": VISUAL_POLICY_VERSION,
                "outcome": visual_outcome,
                "contribution": visual_contribution,
                "analysis": {k: v for k, v in analysis.items() if k != "image_path"},
                "backfill": backfill,
                "images_not_analysed": extracted.get("_images_not_analysed", 0),
            },
            "rainfall_context": rainfall,
            **scoring["provenance"],
        }
        record: Dict[str, Any] = {
            "report_id":        report_id,
            "timestamp":        now.isoformat(),
            "user_hash":        user_hash,
            "language":         language,
            "report_domain":    fields.get("report_domain") or "unknown",
            "hazard_type":      fields.get("hazard_type") or "unknown",
            "category":         fields.get("category") or "general",
            "location_text":    fields.get("location_text") or "",
            "description":      fields.get("description") or "",
            "confidence_score": round(scoring["confidence"], 3),
            "severity_score":   round(scoring["severity"], 3),
            "action":           scoring["action"],
            "status":           "new",
            "people_at_risk":   1 if fields.get("people_at_risk") else 0,
            "ongoing":          1 if fields.get("ongoing") else 0,
            "image_path":       analysis.get("image_path") if analysis else None,
            "image_evidence_score": round(visual_contribution, 3),
            "image_hazard_category": analysis.get("hazard_category") if visual_outcome == "supporting" else None,
            "created_at":       now.isoformat(),
            "source_message_id": message_id,
            "policy_version":   scoring["policy_version"],
            "shadow_action":    scoring["shadow_action"],
            "scoring_provenance": json.dumps(provenance, ensure_ascii=False, default=str),
        }

        try:
            self._store_report(record)
        except sqlite3.IntegrityError:
            existing = self.find_report_by_message_id(message_id) if message_id else None
            if existing:
                return self._already_stored_result(existing, language)
            return self._storage_failure_result(language)
        except Exception as exc:
            print(f"[reporter] store error: {exc}")
            return self._storage_failure_result(language)

        return {
            "response":             self._acknowledgement(
                language, report_id, scoring["action"], scoring["severity"],
                image_hazard_category=record["image_hazard_category"],
            ),
            "report_id":            report_id,
            "needs_clarification":  False,
            "clarification_field":  None,
            "pending_report":       None,
            "stored":               True,
        }

    @staticmethod
    def _public_fields(extracted: Dict[str, Any]) -> Dict[str, Any]:
        return {k: v for k, v in extracted.items() if not k.startswith("_")}

    def find_report_by_message_id(self, message_id: str) -> Optional[Dict[str, Any]]:
        if not message_id:
            return None
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT report_id, action FROM community_reports WHERE source_message_id = ?",
                (message_id,)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    @staticmethod
    def _already_stored_result(existing: Dict[str, Any], language: str) -> Dict[str, Any]:
        msg = {
            "en": f"✅ This report was already received (ID: {existing['report_id']}).",
            "si": f"✅ මෙම වාර්තාව දැනටමත් ලැබී ඇත (ID: {existing['report_id']}).",
            "ta": f"✅ இந்த அறிக்கை ஏற்கனவே பெறப்பட்டது (ID: {existing['report_id']}).",
        }
        return {"response": msg.get(language, msg["en"]), "report_id": existing["report_id"],
                "needs_clarification": False, "clarification_field": None,
                "pending_report": None, "stored": True, "duplicate": True}

    @staticmethod
    def _storage_failure_result(language: str) -> Dict[str, Any]:
        msg = {
            "en": "⚠️ Sorry, your report could not be saved right now. Please send it again in a few minutes.",
            "si": "⚠️ කණගාටුයි, ඔබේ වාර්තාව දැන් සුරැකීමට නොහැකි විය. මිනිත්තු කිහිපයකින් නැවත යවන්න.",
            "ta": "⚠️ மன்னிக்கவும், உங்கள் அறிக்கையை இப்போது சேமிக்க முடியவில்லை. சில நிமிடங்களில் மீண்டும் அனுப்பவும்.",
        }
        return {"response": msg.get(language, msg["en"]), "report_id": None,
                "needs_clarification": False, "clarification_field": None,
                "pending_report": None, "stored": False}

    def log_tool_call(self, phone_number: str, tool_name: str, tool_input: Dict) -> None:
        """Persist an agent tool-call record for routing evaluation."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT INTO agent_tool_calls (user_hash, tool_name, tool_input, called_at)
                    VALUES (?, ?, ?, ?)
                """, (
                    self._resolve_user_hash(phone_number),
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
        Return a brief formatted summary of recent community reports for RAG
        injection. Verified reports are labelled as confirmed; others as unverified.
        Only surfaces reports with confidence >= 0.4 from the last 48 hours.
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute("""
                    SELECT report_domain, hazard_type, location_text,
                           description, confidence_score, severity_score,
                           action, status, timestamp
                    FROM community_reports
                    WHERE timestamp >= ?
                      AND action IN ('monitor', 'flag_review', 'expedited_review', 'escalate')
                      AND confidence_score >= 0.4
                      AND status NOT IN ('closed', 'archived', 'stale')
                    ORDER BY
                      CASE WHEN status = 'verified' THEN 0 ELSE 1 END,
                      severity_score DESC, timestamp DESC
                    LIMIT 5
                """, (cutoff,)).fetchall()
        except Exception as exc:
            print(f"[reporter] get_recent_reports_context error: {exc}")
            return ""

        if not rows:
            return ""

        lines = ["📍 Recent community observations:"]
        for row in rows:
            ts     = row["timestamp"][:16].replace("T", " ")
            label  = "✅ CONFIRMED" if row["status"] == "verified" else "⚠ unverified"
            lines.append(
                f"• [{row['report_domain'].upper()} — {label}] {row['location_text']} — "
                f"{(row['description'] or '')[:120]} "
                f"(conf: {row['confidence_score']:.2f}, sev: {row['severity_score']:.2f}, {ts} UTC)"
            )
        return "\n".join(lines)

    # ── Model calls ───────────────────────────────────────────────────────

    async def _invoke_llm(self, messages: List[Any], timeout_s: float) -> Tuple[str, Dict[str, Any]]:
        """Call the model with a hard timeout; return (text, call metadata)."""
        t0 = time.perf_counter()
        result = await asyncio.wait_for(self.llm.ainvoke(messages), timeout=timeout_s)
        meta = getattr(result, "response_metadata", None) or {}
        return result.content, {
            "model_snapshot": meta.get("model_name"),
            "token_usage": meta.get("token_usage"),
            "finish_reason": meta.get("finish_reason"),
            "latency_s": time.perf_counter() - t0,
        }

    async def _extract_report(self, message: str, language: str) -> Dict:
        """
        Extract structured fields from free text and validate them against
        TEXT_SCHEMA. Any failure (timeout, API error, malformed JSON, non-object)
        falls back to the deterministic keyword extractor; the reason is kept in
        `_extraction_meta`.
        """
        if not message.strip():
            fallback = self._fallback_extraction(message)
            fallback["_extraction_meta"] = {"status": "fallback", "reason": "empty_text", "issues": []}
            return fallback
        call_meta: Dict[str, Any] = {}
        try:
            raw, call_meta = await self._invoke_llm(
                [SystemMessage(content=self.EXTRACTION_PROMPT), HumanMessage(content=message)],
                Config.EXTRACTION_TIMEOUT_S,
            )
            parsed = parse_model_json(raw)
        except asyncio.TimeoutError:
            reason = "timeout"
        except SchemaError as exc:
            reason = f"schema: {exc}"
        except Exception as exc:
            reason = f"api_error: {type(exc).__name__}"
        else:
            fields, issues = validate_against_schema(parsed, TEXT_SCHEMA)
            if not fields.get("location_text"):
                fields["location_specific"] = False
            fields["_extraction_meta"] = {"status": "ok", "issues": issues, **call_meta}
            return fields
        print(f"[reporter] LLM extraction fallback: {reason}")
        fallback = self._fallback_extraction(message)
        fallback["_extraction_meta"] = {"status": "fallback", "reason": reason, "issues": [], **call_meta}
        return fallback

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
            "location_specific": False,
            "clarification_question": None,  # process_report falls back to the static prompt
            "description":      message[:200],
            "people_at_risk":   _contains_indicators(message, [EXPOSURE_INDICATORS]),
            "ongoing":          _contains_indicators(message, [IMMEDIACY_INDICATORS]),
            "hazard_scale":     "unknown",
            "infrastructure_damage": _contains_indicators(message, [INFRASTRUCTURE_INDICATORS]),
        }

    # ── Photo evidence (vision model) ─────────────────────────────────────

    @staticmethod
    def sniff_image_mime(data: bytes) -> Optional[str]:
        if data.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            return "image/webp"
        if data[:6] in (b"GIF87a", b"GIF89a"):
            return "image/gif"
        return None

    async def _analyze_image_evidence(
        self,
        image_bytes: bytes,
        image_mime: Optional[str],
        description: str,
        language: str,
    ) -> Dict[str, Any]:
        """
        Structured vision assessment of an attached photo. Returns the
        validated fields plus a `status`:
          ok          all core fields valid; evidence_score snapped to a tier
          unsupported empty, oversized or non-image payload (no model call)
          error       timeout, API error, malformed JSON or invalid core field
        Only status "ok" can contribute to confidence (see apply_visual_policy).
        """
        sniffed = self.sniff_image_mime(image_bytes or b"")
        result: Dict[str, Any] = {
            "status": "ok", "error": None, "issues": [],
            "declared_mime": image_mime, "mime": sniffed,
            "image_sha256": hashlib.sha256(image_bytes or b"").hexdigest(),
            "image_bytes": len(image_bytes or b""),
            "image_path": None,
        }
        if not image_bytes or sniffed not in SUPPORTED_IMAGE_MIMES or len(image_bytes) > Config.MAX_IMAGE_BYTES:
            result.update(status="unsupported", error="empty, oversized or unsupported image type")
            return result

        result["image_path"] = self._save_image(image_bytes, sniffed)
        prompt = self.VISION_PROMPT_TEMPLATE.format(description=description or "(no description provided)")
        try:
            b64 = base64.b64encode(image_bytes).decode("ascii")
            raw, call_meta = await self._invoke_llm([
                HumanMessage(content=[
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:{sniffed};base64,{b64}"}},
                ])
            ], Config.VISION_TIMEOUT_S)
            result.update(call_meta)
            fields, issues = validate_against_schema(parse_model_json(raw), IMAGE_SCHEMA)
        except asyncio.TimeoutError:
            result.update(status="error", error="timeout")
            return result
        except SchemaError as exc:
            result.update(status="error", error=f"schema: {exc}")
            return result
        except Exception as exc:
            result.update(status="error", error=f"api_error: {type(exc).__name__}")
            print(f"[reporter] image evidence scoring error: {type(exc).__name__}")
            return result

        result.update(fields)
        result["issues"] = issues
        bad_core = [f for f in IMAGE_CORE_FIELDS if f"missing:{f}" in issues or f"invalid:{f}" in issues]
        if bad_core:
            result.update(status="error", error=f"invalid core fields: {', '.join(bad_core)}")
            return result
        result["evidence_score"] = min(EVIDENCE_TIERS, key=lambda t: abs(t - fields["evidence_score"]))
        return result

    @staticmethod
    def _save_image(image_bytes: bytes, mime_type: str) -> str:
        """Persist the raw photo to local disk so admins can review evidence."""
        ext = mimetypes.guess_extension(mime_type) or ".jpg"
        images_dir = Config.REPORT_IMAGES_DIR
        os.makedirs(images_dir, exist_ok=True)
        path = os.path.join(images_dir, f"{uuid.uuid4().hex}{ext}")
        with open(path, "wb") as f:
            f.write(image_bytes)
        return path

    # ── Confidence scoring ────────────────────────────────────────────────

    def score_report(self, fields: Dict[str, Any], user_hash: str, visual_contribution: float,
                     now: Optional[datetime] = None) -> Dict[str, Any]:
        """
        Confidence (completeness 0.30, plausibility 0.20, corroboration 0.30,
        image evidence 0.20), severity (spec Table 5) and both decision
        policies. Scores are additive heuristics, not calibrated probabilities.
        """
        now = now or datetime.now(timezone.utc)
        completeness = {
            "location": 0.15 if fields.get("location_text") else 0.0,
            "hazard_type": 0.10 if fields.get("hazard_type") not in (None, "unknown") else 0.0,
            "description": 0.05 if len(fields.get("description") or "") > 20 else 0.0,
        }
        plausibility = self._check_plausibility(fields, now=now)
        corroboration = self._corroboration_details(fields, user_hash, now=now)
        conf_parts = {
            "completeness": sum(completeness.values()),
            "plausibility": plausibility,
            "corroboration": corroboration["score"],
            "image_evidence": visual_contribution,
        }
        confidence = quantize_score(min(sum(conf_parts.values()), 1.0))
        sev_parts = severity_components(fields)
        severity = quantize_score(min(sum(sev_parts.values()), 1.0))

        active = Config.ACTIVE_DECISION_POLICY if Config.ACTIVE_DECISION_POLICY in DECISION_POLICIES else POLICY_BASELINE
        shadow = POLICY_CANDIDATE if active == POLICY_BASELINE else POLICY_BASELINE
        action = DECISION_POLICIES[active](confidence, severity)
        shadow_action = DECISION_POLICIES[shadow](confidence, severity)
        return {
            "confidence": confidence,
            "severity": severity,
            "action": action,
            "policy_version": active,
            "shadow_action": shadow_action,
            "provenance": {
                "confidence_components": {**conf_parts, "completeness_detail": completeness},
                "confidence": confidence,
                "severity_components": sev_parts,
                "severity": severity,
                "corroboration": corroboration,
                "policy": {"active": active, "action": action, "shadow": shadow, "shadow_action": shadow_action},
            },
        }

    def _score_confidence(self, extracted: Dict, phone_number: str) -> float:
        """Confidence for already-merged fields (image contribution taken from the dict)."""
        return self.score_report(
            extracted, self._resolve_user_hash(phone_number), extracted.get("image_evidence_score") or 0.0,
        )["confidence"]

    def _check_plausibility(self, extracted: Dict, now: Optional[datetime] = None) -> float:
        """District / locality lookup (0.15) + fresh forecast-precipitation bonus, capped at 0.20."""
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

        return min(base + self._get_rainfall_bonus_sync(loc, hazard, now=now), 0.20)

    @staticmethod
    def _colombo_today(now: datetime) -> str:
        return (now.astimezone(timezone(timedelta(hours=5, minutes=30)))).date().isoformat()

    def _rainfall_context(self, loc: str, now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
        """Cached forecast entry for the district named in loc, with a freshness verdict."""
        now = now or datetime.now(timezone.utc)
        loc = loc.lower()
        for district, entry in self._rainfall_cache.items():
            if district in loc:
                age_min = (now - datetime.fromisoformat(entry["fetched_at"])).total_seconds() / 60
                fresh = (age_min <= Config.RAINFALL_CACHE_TTL_MINUTES
                         and entry.get("forecast_date") == self._colombo_today(now))
                return {**entry, "district": district, "age_minutes": round(age_min, 1), "fresh": fresh}
        return None

    def _get_rainfall_bonus_sync(self, loc: str, hazard: str, now: Optional[datetime] = None) -> float:
        """
        0.05 for >= 50 mm, 0.02 for >= 20 mm of forecast precipitation for the
        matched district today. Stale or missing context gives no bonus. This
        is a district-centroid forecast, not rainfall measured at the site.
        """
        if hazard not in ("flood", "landslide", "drainage", "erosion"):
            return 0.0
        ctx = self._rainfall_context(loc, now=now)
        if not ctx or not ctx["fresh"] or ctx.get("mm") is None:
            return 0.0
        if ctx["mm"] >= 50:
            return 0.05
        if ctx["mm"] >= 20:
            return 0.02
        return 0.0

    async def _fetch_rainfall_for_location(self, loc: str) -> Optional[Dict[str, Any]]:
        """
        Fetch today's Open-Meteo daily precipitation_sum forecast for the
        district centroid matched in loc, unless a fresh entry is cached.
        Returns the context entry (or None if no district matches).
        """
        loc_lower = loc.lower()
        match = next(((d, ll) for d, ll in _DISTRICT_COORDS.items() if d in loc_lower), None)
        if not match:
            return None
        ctx = self._rainfall_context(loc_lower)
        if ctx and ctx["fresh"]:
            return ctx

        district, (lat, lon) = match
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
                        daily = data.get("daily", {})
                        mm = (daily.get("precipitation_sum") or [None])[0]
                        self._rainfall_cache[district] = {
                            "kind": "forecast_precipitation_sum_mm",
                            "source": "Open-Meteo daily forecast, district centroid (not measured at the site)",
                            "mm": float(mm) if isinstance(mm, (int, float)) else None,
                            "forecast_date": (daily.get("time") or [None])[0],
                            "fetched_at": datetime.now(timezone.utc).isoformat(),
                            "lat": lat, "lon": lon,
                        }
        except Exception as exc:
            print(f"[reporter] _fetch_rainfall_for_location error: {type(exc).__name__}")
        return self._rainfall_context(loc_lower)

    # Words that describe position rather than name a place; skipped when
    # choosing the token used to group reports by location.
    _LOCATION_STOPWORDS = {
        "near", "the", "behind", "next", "close", "beside", "opposite", "road", "area",
        "town", "village", "junction", "side", "front", "from", "and", "our", "my",
    }

    def _location_token(self, loc: str) -> str:
        loc = loc.lower()
        for place in sorted(_DISTRICT_COORDS.keys() | LANDSLIDE_PRONE_DISTRICTS | FLOOD_PRONE_LOCALITIES,
                            key=len, reverse=True):
            if place in loc:
                return place
        return next((w.strip(",.") for w in loc.split()
                     if len(w.strip(",.")) > 2 and w.strip(",.") not in self._LOCATION_STOPWORDS), "")

    def _corroboration_details(self, extracted: Dict, user_hash: str,
                               now: Optional[datetime] = None) -> Dict[str, Any]:
        """
        Corroboration from other contributors' recent reports in the same
        (domain, hazard type, location token) cluster. Each distinct other
        contributor counts once; the submitter is excluded. Their reliabilities
        are combined by aggregate_reliabilities and scaled to [0, 0.30].
        Distinct contributor pseudonyms are not proof of independent observations.
        """
        now = now or datetime.now(timezone.utc)
        loc = (extracted.get("location_text") or "").lower()
        domain = extracted.get("report_domain", "unknown")
        hazard = extracted.get("hazard_type", "unknown")
        details: Dict[str, Any] = {"score": 0.0, "agreement": None, "contributors": [],
                                   "window_hours": CORROBORATION_WINDOW_HOURS, "location_token": None}
        if not loc or domain == "unknown":
            return details
        token = self._location_token(loc)
        details["location_token"] = token
        if not token:
            return details

        cutoff = (now - timedelta(hours=CORROBORATION_WINDOW_HOURS)).isoformat()
        like = "%" + token.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        conn = self._connect()
        try:
            rows = conn.execute("""
                SELECT r.user_hash, r.report_id, u.reliability
                FROM community_reports r
                LEFT JOIN user_reliability u ON u.user_hash = r.user_hash
                WHERE r.timestamp >= ?
                  AND r.report_domain = ?
                  AND (r.hazard_type = ? OR ? = 'unknown')
                  AND lower(r.location_text) LIKE ? ESCAPE '\\'
                  AND r.status NOT IN ('closed', 'archived')
                  AND r.user_hash != ?
                ORDER BY r.timestamp
            """, (cutoff, domain, hazard, hazard, like, user_hash)).fetchall()
        except Exception as exc:
            print(f"[reporter] corroboration query error: {exc}")
            return details
        finally:
            conn.close()

        by_user: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            entry = by_user.setdefault(row["user_hash"], {
                "user_hash": row["user_hash"],
                "reliability": row["reliability"] if row["reliability"] is not None else _DEFAULT_RELIABILITY,
                "report_ids": [],
            })
            entry["report_ids"].append(row["report_id"])
        contributors = list(by_user.values())
        agreement = aggregate_reliabilities([c["reliability"] for c in contributors])
        details.update(contributors=contributors, agreement=agreement,
                       score=0.0 if agreement is None else CORROBORATION_WEIGHT * agreement)
        return details

    def _check_triangulation_bayesian(self, extracted: Dict, phone_number: str) -> float:
        """Corroboration contribution in [0, 0.30] (see _corroboration_details)."""
        return self._corroboration_details(extracted, self._resolve_user_hash(phone_number))["score"]

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

    # ── Human review and reliability replay ───────────────────────────────

    REVIEW_STATUS = {"verified": "verified", "false": "closed", "retracted": "new"}

    def review_report(self, report_id: str, decision: str, reviewer: str = "admin",
                      note: str = "") -> Dict[str, Any]:
        """
        Record a human review decision ("verified", "false" = verified false
        report, "retracted" = withdraw the previous decision) and recompute the
        contributor's reliability, all in one transaction.

        Idempotent: repeating the report's current effective decision changes
        nothing. A wrong review is corrected by submitting the right decision
        (or "retracted"); reliability is then replayed from scratch, so the
        result equals what it would be had the wrong decision never been made.
        Raises KeyError for an unknown report_id, ValueError for a bad decision.
        """
        if decision not in self.REVIEW_STATUS:
            raise ValueError(f"unknown review decision: {decision}")
        now = datetime.now(timezone.utc).isoformat()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT user_hash, status, review_outcome FROM community_reports WHERE report_id = ?",
                (report_id,)).fetchone()
            if not row:
                conn.execute("ROLLBACK")
                raise KeyError(report_id)
            user_hash, old_status, current = row["user_hash"], row["status"], row["review_outcome"]
            target = None if decision == "retracted" else decision
            if current == target:
                conn.execute("COMMIT")
                return {"changed": False, "report_id": report_id, "status": old_status,
                        "review_outcome": current}

            before = self._stored_reliability(conn, user_hash)
            new_status = self.REVIEW_STATUS[decision]
            conn.execute(
                "INSERT INTO review_events (report_id, user_hash, decision, reviewer, note, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)", (report_id, user_hash, decision, reviewer, note, now))
            conn.execute(
                "UPDATE community_reports SET status = ?, review_outcome = ? WHERE report_id = ?",
                (new_status, target, report_id))
            conn.execute(
                "INSERT INTO report_status_log (report_id, old_status, new_status, changed_at, note) "
                "VALUES (?, ?, ?, ?, ?)", (report_id, old_status, new_status, now, f"review: {decision}"))
            after = self._replay_reliability(conn, user_hash, now)
            conn.execute("COMMIT")
        except KeyError:
            raise
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()
        print(f"[reporter] review {report_id}: {decision} → r {before:.4f}→{after:.4f}")
        return {"changed": True, "report_id": report_id, "status": new_status,
                "review_outcome": target, "reliability_before": before, "reliability_after": after}

    @staticmethod
    def _stored_reliability(conn: sqlite3.Connection, user_hash: str) -> float:
        row = conn.execute("SELECT reliability FROM user_reliability WHERE user_hash = ?", (user_hash,)).fetchone()
        return row[0] if row else _DEFAULT_RELIABILITY

    @staticmethod
    def _replay_reliability(conn: sqlite3.Connection, user_hash: str, now: str) -> float:
        """
        Reliability = bounded EMA over this contributor's effective review
        decisions (the latest event per report, excluding retractions), applied
        in the order those effective events were recorded, starting from
        replay_base (0.5 for contributors with no pre-existing score).
        Must run inside the caller's write transaction.
        """
        base_row = conn.execute(
            "SELECT replay_base FROM user_reliability WHERE user_hash = ?", (user_hash,)).fetchone()
        base = base_row[0] if base_row and base_row[0] is not None else _DEFAULT_RELIABILITY
        effective = conn.execute("""
            SELECT e.decision FROM review_events e
            WHERE e.user_hash = ?
              AND e.id = (SELECT MAX(id) FROM review_events WHERE report_id = e.report_id)
              AND e.decision != 'retracted'
            ORDER BY e.id
        """, (user_hash,)).fetchall()
        r = base
        for (decision,) in effective:
            r = reliability_update(r, decision == "verified")
        n_ver = sum(1 for (d,) in effective if d == "verified")
        n_rej = len(effective) - n_ver
        conn.execute("""
            INSERT INTO user_reliability
                (user_hash, reliability, n_reports, n_verified, n_rejected, updated_at, replay_base)
            VALUES (?, ?, 0, ?, ?, ?, ?)
            ON CONFLICT(user_hash) DO UPDATE SET
                reliability = excluded.reliability,
                n_verified  = excluded.n_verified,
                n_rejected  = excluded.n_rejected,
                updated_at  = excluded.updated_at
        """, (user_hash, r, n_ver, n_rej, now, base))
        return r

    # ── Severity scoring / decision engine ────────────────────────────────

    def _score_severity(self, extracted: Dict) -> float:
        """Severity per spec Table 5 (see severity_components)."""
        return quantize_score(min(sum(severity_components(extracted).values()), 1.0))

    @staticmethod
    def _decide_action(confidence: float, severity: float) -> str:
        """Baseline confidence × severity matrix (decide_action_baseline)."""
        return decide_action_baseline(confidence, severity)

    # ── Storage ───────────────────────────────────────────────────────────

    _REPORT_COLUMNS = (
        "report_id", "timestamp", "user_hash", "language", "report_domain", "hazard_type",
        "category", "location_text", "description", "confidence_score", "severity_score",
        "action", "status", "people_at_risk", "ongoing", "image_path", "image_evidence_score",
        "image_hazard_category", "created_at", "source_message_id", "policy_version",
        "shadow_action", "scoring_provenance",
    )

    def _store_report(self, record: Dict) -> None:
        """Insert the report, its status-log entry and the contributor's report
        count in one transaction. Raises on failure (nothing is written)."""
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                f"INSERT INTO community_reports ({', '.join(self._REPORT_COLUMNS)}) "
                f"VALUES ({', '.join('?' * len(self._REPORT_COLUMNS))})",
                tuple(record.get(c) for c in self._REPORT_COLUMNS))
            conn.execute("""
                INSERT INTO report_status_log (report_id, old_status, new_status, changed_at, note)
                VALUES (?, ?, ?, ?, ?)
            """, (record["report_id"], None, "new", record["created_at"], "initial"))
            conn.execute("""
                INSERT INTO user_reliability
                    (user_hash, reliability, n_reports, n_verified, n_rejected, updated_at, replay_base)
                VALUES (?, ?, 1, 0, 0, ?, ?)
                ON CONFLICT(user_hash) DO UPDATE SET
                    n_reports  = n_reports + 1,
                    updated_at = excluded.updated_at
            """, (record["user_hash"], _DEFAULT_RELIABILITY, record["created_at"], _DEFAULT_RELIABILITY))
            conn.execute("COMMIT")
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()
        print(
            f"[reporter] stored {record['report_id']} "
            f"domain={record['report_domain']} action={record['action']} "
            f"conf={record['confidence_score']:.2f} sev={record['severity_score']:.2f}"
        )

    # ── Retention ─────────────────────────────────────────────────────────

    # (report_domain, max_age_days, action) for unreviewed reports — spec Table 8
    RETENTION_RULES = [
        ("hazard",          7,   "archive"),
        ("infrastructure",  30,  "archive"),
        ("regulatory",      180, "archive"),
        ("safety",          14,  "archive"),
        ("unknown",         14,  "delete"),
    ]

    def apply_retention(self, now: Optional[datetime] = None) -> Dict[str, int]:
        """
        Expire unreviewed reports and old images in one write transaction.

        - Unreviewed reports past their domain's age limit are archived
          (unknown-domain reports with confidence < 0.40 are deleted). Expiry
          is not a review outcome: it never changes contributor reliability,
          and archived reports keep review_outcome NULL, unlike reports
          reviewed as false (status 'closed', review_outcome 'false').
        - Photos older than IMAGE_RETENTION_DAYS are deleted from disk for
          every report (derived fields and the image hash are kept).
        - Photos on disk referenced by no report (e.g. from clarifications
          that were never completed) are deleted once older than twice the
          pending-report TTL.
        Files are removed only after the transaction commits.
        """
        now = now or datetime.now(timezone.utc)
        stamp = now.isoformat()
        stats = {"archived": 0, "deleted": 0, "images_deleted": 0, "orphan_images_deleted": 0}
        files_to_delete: List[str] = []
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            for domain, max_days, action in self.RETENTION_RULES:
                cutoff = (now - timedelta(days=max_days)).isoformat()
                rows = conn.execute("""
                    SELECT report_id, confidence_score, status, image_path
                    FROM community_reports
                    WHERE report_domain = ? AND created_at < ?
                      AND status IN ('new', 'monitored', 'under_review')
                      AND review_outcome IS NULL
                """, (domain, cutoff)).fetchall()
                for row in rows:
                    if action == "delete" and row["confidence_score"] < 0.40:
                        conn.execute("DELETE FROM community_reports WHERE report_id = ?", (row["report_id"],))
                        new_status, note = "deleted", "retention: unreviewed low-confidence expiry"
                        if row["image_path"]:
                            files_to_delete.append(row["image_path"])
                        stats["deleted"] += 1
                    else:
                        conn.execute("UPDATE community_reports SET status = 'archived' WHERE report_id = ?",
                                     (row["report_id"],))
                        new_status, note = "archived", "retention: unreviewed expiry"
                        stats["archived"] += 1
                    conn.execute(
                        "INSERT INTO report_status_log (report_id, old_status, new_status, changed_at, note) "
                        "VALUES (?, ?, ?, ?, ?)", (row["report_id"], row["status"], new_status, stamp, note))

            image_cutoff = (now - timedelta(days=Config.IMAGE_RETENTION_DAYS)).isoformat()
            for row in conn.execute("""
                SELECT report_id, image_path FROM community_reports
                WHERE image_path IS NOT NULL AND created_at < ?
            """, (image_cutoff,)).fetchall():
                files_to_delete.append(row["image_path"])
                conn.execute("UPDATE community_reports SET image_path = NULL WHERE report_id = ?",
                             (row["report_id"],))
                stats["images_deleted"] += 1
            referenced = {r[0] for r in conn.execute(
                "SELECT image_path FROM community_reports WHERE image_path IS NOT NULL")}
            conn.execute("COMMIT")
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

        for path in files_to_delete:
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
        images_dir = Config.REPORT_IMAGES_DIR
        orphan_cutoff = now.timestamp() - 2 * Config.PENDING_REPORT_TTL_MINUTES * 60
        if os.path.isdir(images_dir):
            for name in os.listdir(images_dir):
                path = os.path.join(images_dir, name)
                if path not in referenced and os.path.getmtime(path) < orphan_cutoff:
                    os.remove(path)
                    stats["orphan_images_deleted"] += 1
        return stats

    # ── User-facing messages ──────────────────────────────────────────────

    @staticmethod
    def _clarification_prompt(language: str, field: str) -> str:
        """Static fallback follow-up, used only if the LLM didn't supply one."""
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
    def _acknowledgement(
        language: str,
        report_id: str,
        action: str,
        severity: float,
        image_hazard_category: Optional[str] = None,
    ) -> str:
        """User-facing acknowledgement based on decision action."""
        photo_note = ""
        labels = CommunityReporter._HAZARD_CATEGORY_LABELS.get(image_hazard_category or "")
        if labels:
            label = labels.get(language, labels["en"])
            photo_note = {
                "en": f"\n\n📷 Your photo shows signs of {label}.",
                "si": f"\n\n📷 ඔබේ ඡායාරූපයේ {label} පෙන්නුම් කරයි.",
                "ta": f"\n\n📷 உங்கள் புகைப்படத்தில் {label} தென்படுகிறது.",
            }.get(language, f"\n\n📷 Your photo shows signs of {label}.")

        if action == "escalate":
            msg = {
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
            return msg + photo_note

        if action in ("expedited_review", "flag_review", "monitor"):
            msg = {
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
            return msg + photo_note

        # store_only
        msg = {
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
        return msg + photo_note
