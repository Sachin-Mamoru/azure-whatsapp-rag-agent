"""
Regression tests for the community-reporting subsystem.

Run:  python -m unittest discover -s tests -v
No network or API key is needed: the model is replaced by a scripted fake.
"""
import asyncio
import contextlib
import io
import json
import math
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-test-not-used")
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:1/0")

from config import Config  # noqa: E402
from agent import reporter as rep  # noqa: E402
from agent.reporter import (  # noqa: E402
    CommunityReporter, SchemaError, aggregate_reliabilities, apply_visual_policy,
    decide_action_baseline, decide_action_candidate, parse_model_json, reliability_update,
    validate_against_schema, ACTION_PRIORITY, IMAGE_SCHEMA, TEXT_SCHEMA,
    VISUAL_FULL, VISUAL_LEGACY, VISUAL_SCORE_ONLY, VISUAL_TEXT_ONLY,
)
from agent.agent_tools import build_tools  # noqa: E402
from agent.memory import ConversationMemory  # noqa: E402
from agent.orchestrator import WhatsAppOrchestrator  # noqa: E402

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
PHONE_A, PHONE_B = "94771234567", "94779876543"


def text_reply(**overrides):
    base = {
        "report_domain": "hazard", "hazard_type": "landslide", "category": "slope crack",
        "location_text": "Ratnapura", "location_specific": True, "clarification_question": None,
        "description": "Large crack on the slope behind houses, ground moving.",
        "people_at_risk": True, "ongoing": True, "hazard_scale": "moderate",
        "infrastructure_damage": False,
    }
    base.update(overrides)
    return json.dumps(base)


def vision_reply(**overrides):
    base = {
        "hazard_detected": True, "hazard_category": "localised_flooding",
        "possible_condition": "road_flooding", "severity_from_image": "moderate",
        "report_image_consistency": "high", "evidence_score": 0.15, "summary": "Flooded road.",
    }
    base.update(overrides)
    return json.dumps(base)


class _Msg:
    def __init__(self, content):
        self.content = content
        self.response_metadata = {"model_name": "gpt-4o-mini-fake", "token_usage": {"total_tokens": 1}}


class FakeLLM:
    """Returns scripted replies in order. A reply may be an Exception (raised)
    or ("sleep", seconds) to simulate a hung call."""

    def __init__(self, replies=None):
        self.replies = list(replies or [])
        self.calls = []

    async def ainvoke(self, messages):
        self.calls.append(messages)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        if isinstance(reply, tuple) and reply[0] == "sleep":
            await asyncio.sleep(reply[1])
            return _Msg("{}")
        return _Msg(reply)

    def is_vision(self, i):
        content = self.calls[i][0].content
        return isinstance(content, list)


class ReporterTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = {k: getattr(Config, k) for k in (
            "COMMUNITY_REPORTS_DB", "REPORT_IMAGES_DIR", "REPORTER_ID_KEY", "VISION_TIMEOUT_S",
            "ACTIVE_DECISION_POLICY", "IMAGE_RETENTION_DAYS", "PENDING_REPORT_TTL_MINUTES")}
        Config.COMMUNITY_REPORTS_DB = os.path.join(self.tmp.name, "reports.db")
        Config.REPORT_IMAGES_DIR = os.path.join(self.tmp.name, "images")
        Config.REPORTER_ID_KEY = ""
        Config.ACTIVE_DECISION_POLICY = rep.POLICY_BASELINE
        self.reporter = CommunityReporter()
        self.llm = FakeLLM()
        self.reporter.llm = self.llm

        async def no_rain(loc):
            return None
        self.reporter._fetch_rainfall_for_location = no_rain

    def tearDown(self):
        for k, v in self.saved.items():
            setattr(Config, k, v)
        self.tmp.cleanup()

    def rows(self, sql, args=()):
        with sqlite3.connect(Config.COMMUNITY_REPORTS_DB) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(r) for r in conn.execute(sql, args).fetchall()]

    def insert_report(self, report_id, user_hash, created_at=None, status="new", domain="hazard",
                      hazard="landslide", loc="Ratnapura", conf=0.5, image_path=None):
        ts = (created_at or datetime.now(timezone.utc)).isoformat()
        record = {c: None for c in CommunityReporter._REPORT_COLUMNS}
        record.update(report_id=report_id, timestamp=ts, user_hash=user_hash, language="en",
                      report_domain=domain, hazard_type=hazard, category=hazard, location_text=loc,
                      description="seeded", confidence_score=conf, severity_score=0.5,
                      action="monitor", status=status, people_at_risk=0, ongoing=0,
                      image_path=image_path, image_evidence_score=0.0, created_at=ts)
        self.reporter._store_report(record)


# ── Model output validation ──────────────────────────────────────────────────

class TestModelOutputValidation(unittest.TestCase):
    def test_parse_model_json_fenced_and_bare(self):
        self.assertEqual(parse_model_json('```json\n{"a": 1}\n```'), {"a": 1})
        self.assertEqual(parse_model_json('{"a": 1}'), {"a": 1})

    def test_parse_model_json_rejects_malformed_and_non_objects(self):
        for bad in ["not json", "[1, 2]", "", None, '{"a": 1'] :
            with self.assertRaises(SchemaError):
                parse_model_json(bad)

    def test_text_schema_enum_bool_missing(self):
        clean, issues = validate_against_schema(
            {"report_domain": "Hazard", "hazard_type": "tsunami", "people_at_risk": "true",
             "ongoing": 1, "hazard_scale": "major"}, TEXT_SCHEMA)
        self.assertEqual(clean["report_domain"], "hazard")
        self.assertEqual(clean["hazard_type"], "unknown")
        self.assertTrue(clean["people_at_risk"])
        self.assertFalse(clean["ongoing"])  # integer 1 is not accepted as a boolean
        self.assertIn("invalid:hazard_type", issues)
        self.assertIn("coerced:people_at_risk", issues)
        self.assertIn("invalid:ongoing", issues)
        self.assertIn("missing:location_text", issues)
        self.assertIsNone(clean["location_text"])

    def test_image_schema_numeric_bounds(self):
        for value, ok in [(0.15, True), ("0.10", True), ("high", False), (0.8, False),
                          (float("nan"), False), (True, False), (-0.05, False)]:
            clean, issues = validate_against_schema({"evidence_score": value}, IMAGE_SCHEMA)
            self.assertEqual("invalid:evidence_score" not in issues, ok, value)


class TestImageAnalysis(ReporterTestCase):
    async def analyse(self, reply, data=JPEG):
        self.llm.replies = [reply]
        return await self.reporter._analyze_image_evidence(data, "image/jpeg", "flooded road", "en")

    async def test_valid_reply_is_snapped_to_tier(self):
        result = await self.analyse(vision_reply(evidence_score=0.13))
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["evidence_score"], 0.15)
        self.assertEqual(len(result["image_sha256"]), 64)

    async def test_malformed_json_is_error(self):
        result = await self.analyse("I think this shows a flood")
        self.assertEqual(result["status"], "error")
        self.assertTrue(result["error"].startswith("schema"))

    async def test_nonnumeric_score_is_error(self):
        result = await self.analyse(vision_reply(evidence_score="strong"))
        self.assertEqual(result["status"], "error")
        self.assertIn("evidence_score", result["error"])

    async def test_api_exception_is_error(self):
        result = await self.analyse(RuntimeError("upstream 500"))
        self.assertEqual(result["status"], "error")

    async def test_timeout_is_error(self):
        Config.VISION_TIMEOUT_S = 0.05
        result = await self.analyse(("sleep", 1.0))
        self.assertEqual((result["status"], result["error"]), ("error", "timeout"))

    async def test_unsupported_payload_makes_no_model_call(self):
        for data in [b"", b"%PDF-1.4 not an image", JPEG + b"\x00" * (Config.MAX_IMAGE_BYTES + 1)]:
            result = await self.analyse(vision_reply(), data=data)
            self.assertEqual(result["status"], "unsupported")
        self.assertEqual(self.llm.calls, [])


class TestVisualPolicy(unittest.TestCase):
    TEXT_UNKNOWN = {"report_domain": "unknown", "hazard_type": "unknown", "category": None,
                    "hazard_scale": "unknown", "description": "see photo"}
    TEXT_KNOWN = {"report_domain": "hazard", "hazard_type": "landslide", "category": "slope crack",
                  "hazard_scale": "minor", "description": "crack"}

    def analysis(self, **kw):
        a = {"status": "ok", "hazard_detected": True, "hazard_category": "localised_flooding",
             "possible_condition": "road_flooding", "severity_from_image": "high",
             "report_image_consistency": "high", "evidence_score": 0.20}
        a.update(kw)
        return a

    def assert_no_support(self, analysis, outcome):
        fields, contribution, decisions = apply_visual_policy(self.TEXT_UNKNOWN, analysis)
        self.assertEqual(contribution, 0.0)
        self.assertEqual(fields, self.TEXT_UNKNOWN)
        self.assertTrue(all(not d["accepted"] for d in decisions))
        self.assertEqual(rep.classify_visual_outcome(analysis), outcome)

    def test_failure_contradiction_no_hazard_unusable_never_support(self):
        self.assert_no_support({"status": "error"}, "unavailable")
        self.assert_no_support({"status": "unsupported"}, "unavailable")
        self.assert_no_support(self.analysis(report_image_consistency="contradiction"), "contradiction")
        self.assert_no_support(self.analysis(hazard_detected=False), "no_hazard")
        self.assert_no_support(self.analysis(hazard_category="none"), "no_hazard")
        self.assert_no_support(self.analysis(evidence_score=0.0), "unusable")

    def test_supporting_image_backfills_only_unknown_text_fields(self):
        fields, contribution, decisions = apply_visual_policy(self.TEXT_UNKNOWN, self.analysis())
        self.assertEqual(contribution, 0.20)
        self.assertEqual((fields["report_domain"], fields["hazard_type"], fields["hazard_scale"]),
                         ("hazard", "flood", "major"))
        self.assertTrue(all(d["accepted"] for d in decisions))

        fields, contribution, decisions = apply_visual_policy(self.TEXT_KNOWN, self.analysis())
        self.assertEqual(fields, self.TEXT_KNOWN)  # text-derived values preserved
        self.assertEqual({d["reason"] for d in decisions}, {"text value present; text takes precedence"})

    def test_low_consistency_scores_but_does_not_backfill(self):
        fields, contribution, decisions = apply_visual_policy(
            self.TEXT_UNKNOWN, self.analysis(report_image_consistency="low", evidence_score=0.05))
        self.assertEqual(contribution, 0.05)
        self.assertEqual(fields["hazard_type"], "unknown")
        self.assertFalse(any(d["accepted"] for d in decisions))

    def test_ablation_modes(self):
        _, c, _ = apply_visual_policy(self.TEXT_UNKNOWN, self.analysis(), VISUAL_TEXT_ONLY)
        self.assertEqual(c, 0.0)
        fields, c, _ = apply_visual_policy(self.TEXT_UNKNOWN, self.analysis(), VISUAL_SCORE_ONLY)
        self.assertEqual((c, fields["hazard_type"]), (0.20, "unknown"))

    def test_legacy_mode_documents_old_positive_fallback(self):
        _, c, _ = apply_visual_policy(self.TEXT_UNKNOWN, {"status": "error"}, VISUAL_LEGACY)
        self.assertEqual(c, 0.05)
        fields, c, _ = apply_visual_policy(
            self.TEXT_UNKNOWN, self.analysis(report_image_consistency="contradiction"), VISUAL_LEGACY)
        self.assertEqual((c, fields["hazard_type"]), (0.20, "flood"))


# ── Aggregation, reliability, context ────────────────────────────────────────

class TestAggregation(unittest.TestCase):
    @staticmethod
    def product_formula(rs):
        rs = [min(0.95, max(0.05, r)) for r in rs]
        pr, pq = math.prod(rs), math.prod(1 - r for r in rs)
        return pr / (pr + pq) if pr + pq else 0.0

    def test_empty_single_clipped_mixed(self):
        self.assertIsNone(aggregate_reliabilities([]))
        self.assertAlmostEqual(aggregate_reliabilities([0.5]), 0.5)
        self.assertAlmostEqual(aggregate_reliabilities([0.999]), 0.95)
        self.assertAlmostEqual(aggregate_reliabilities([0.0]), 0.05)
        for rs in ([0.7, 0.4], [0.9, 0.2, 0.6], [0.3, 0.3, 0.8, 0.65, 0.5]):
            self.assertAlmostEqual(aggregate_reliabilities(rs), self.product_formula(rs), places=12)

    def test_large_sets_are_stable(self):
        self.assertEqual(self.product_formula([0.5] * 1100), 0.0)  # direct products underflow
        self.assertAlmostEqual(aggregate_reliabilities([0.5] * 1100), 0.5)
        self.assertAlmostEqual(aggregate_reliabilities([0.95] * 1100), 1.0)
        self.assertAlmostEqual(aggregate_reliabilities([0.05] * 1100), 0.0)
        self.assertAlmostEqual(aggregate_reliabilities([0.95] * 1100 + [0.05] * 1100), 0.5)

    def test_reliability_update_is_bounded_ema(self):
        self.assertEqual(reliability_update(0.5, True), 0.65)
        self.assertEqual(reliability_update(0.5, False), 0.35)
        r = 0.5
        for _ in range(50):
            r = reliability_update(r, True)
        self.assertEqual(r, 0.95)


class TestCorroboration(ReporterTestCase):
    def test_self_exclusion_and_contributor_dedup(self):
        me = rep._hash_phone(PHONE_A)
        self.insert_report("R1", me)
        for i in range(3):
            self.insert_report(f"R2{i}", "other_user")
        self.insert_report("R3", "third_user", loc="near Ratnapura town")
        d = self.reporter._corroboration_details(
            {"location_text": "near Ratnapura", "report_domain": "hazard", "hazard_type": "landslide"}, me)
        self.assertEqual(d["location_token"], "ratnapura")
        self.assertEqual(sorted(c["user_hash"] for c in d["contributors"]), ["other_user", "third_user"])
        self.assertEqual(len(next(c for c in d["contributors"] if c["user_hash"] == "other_user")["report_ids"]), 3)
        self.assertAlmostEqual(d["score"], 0.30 * 0.5)

    def test_byte_identical_photo_is_not_independent_corroboration(self):
        self.insert_report("COPY", "other_user")
        with sqlite3.connect(Config.COMMUNITY_REPORTS_DB) as conn:
            conn.execute("UPDATE community_reports SET image_sha256 = 'abc' WHERE report_id = 'COPY'")
        fields = {"location_text": "Ratnapura", "report_domain": "hazard", "hazard_type": "landslide"}
        self.assertEqual(self.reporter._corroboration_details(fields, "me", image_sha256="abc")["contributors"], [])
        self.assertEqual(len(self.reporter._corroboration_details(fields, "me", image_sha256="xyz")["contributors"]), 1)
        self.assertEqual(len(self.reporter._corroboration_details(fields, "me")["contributors"]), 1)

    def test_location_token_skips_positional_words(self):
        self.assertEqual(self.reporter._location_token("near the temple"), "temple")
        self.assertEqual(self.reporter._location_token("behind Kandy hospital"), "kandy")

    def test_no_corroborators_scores_zero(self):
        d = self.reporter._corroboration_details(
            {"location_text": "Galle", "report_domain": "hazard", "hazard_type": "flood"}, "me")
        self.assertEqual((d["score"], d["agreement"]), (0.0, None))


class TestRainfallContext(ReporterTestCase):
    def set_cache(self, mm, fetched_at, forecast_date):
        self.reporter._rainfall_cache = {"ratnapura": {
            "mm": mm, "fetched_at": fetched_at.isoformat(), "forecast_date": forecast_date,
            "kind": "forecast_precipitation_sum_mm"}}

    def test_fresh_forecast_gives_bonus_stale_does_not(self):
        now = datetime.now(timezone.utc)
        today = self.reporter._colombo_today(now)
        self.set_cache(60, now - timedelta(minutes=10), today)
        self.assertEqual(self.reporter._get_rainfall_bonus_sync("ratnapura", "landslide", now=now), 0.05)
        self.set_cache(60, now - timedelta(minutes=Config.RAINFALL_CACHE_TTL_MINUTES + 1), today)
        self.assertEqual(self.reporter._get_rainfall_bonus_sync("ratnapura", "landslide", now=now), 0.0)
        yesterday = self.reporter._colombo_today(now - timedelta(days=1))
        self.set_cache(60, now - timedelta(minutes=10), yesterday)
        self.assertEqual(self.reporter._get_rainfall_bonus_sync("ratnapura", "landslide", now=now), 0.0)


# ── Decision policies ────────────────────────────────────────────────────────

class TestDecisionPolicies(unittest.TestCase):
    up = staticmethod(lambda x: math.nextafter(x, 2.0))
    down = staticmethod(lambda x: math.nextafter(x, -1.0))

    def test_baseline_exact_boundaries(self):
        cases = [
            (self.down(0.40), 0.9, "store_only"), (0.40, 0.9, "flag_review"),
            (0.40, self.down(0.30), "monitor"), (0.40, 0.30, "flag_review"),
            (self.down(0.70), 0.69, "flag_review"), (0.70, 0.69, "monitor"),
            (0.70, self.down(0.70), "monitor"), (0.70, 0.70, "escalate"), (self.up(0.70), 0.70, "escalate"),
        ]
        for conf, sev, expected in cases:
            self.assertEqual(decide_action_baseline(conf, sev), expected, (conf, sev))

    def test_baseline_known_issues_are_preserved(self):
        # High severity with low confidence is stored without review.
        self.assertEqual(decide_action_baseline(0.39, 1.0), "store_only")
        # Raising confidence to 0.70 at severity 0.50 moves review → monitor.
        self.assertEqual(decide_action_baseline(self.down(0.70), 0.50), "flag_review")
        self.assertEqual(decide_action_baseline(0.70, 0.50), "monitor")

    def test_candidate_exact_boundaries(self):
        cases = [
            (0.0, self.down(0.70), "store_only"), (0.0, 0.70, "expedited_review"),
            (self.down(0.70), 0.70, "expedited_review"), (0.70, 0.70, "escalate"),
            (self.down(0.40), 0.5, "store_only"), (0.40, 0.5, "flag_review"),
            (0.70, 0.50, "flag_review"), (0.40, self.down(0.30), "monitor"), (0.40, 0.30, "flag_review"),
        ]
        for conf, sev, expected in cases:
            self.assertEqual(decide_action_candidate(conf, sev), expected, (conf, sev))

    def monotone_violations(self, policy):
        grid = sorted({v for b in (0.0, 0.30, 0.40, 0.70, 1.0)
                       for v in (b, self.down(b), self.up(b)) if 0.0 <= v <= 1.0} | {i / 20 for i in range(21)})
        rank = {a: i for i, a in enumerate(reversed(ACTION_PRIORITY))}
        bad = []
        for i in range(len(grid) - 1):
            for other in grid:
                lo, hi = grid[i], grid[i + 1]
                if rank[policy(hi, other)] < rank[policy(lo, other)]:
                    bad.append(("confidence", lo, hi, other))
                if rank[policy(other, hi)] < rank[policy(other, lo)]:
                    bad.append(("severity", lo, hi, other))
        return bad

    def test_candidate_is_monotone_baseline_is_not(self):
        self.assertEqual(self.monotone_violations(decide_action_candidate), [])
        self.assertTrue(self.monotone_violations(decide_action_baseline))

    def test_quantization_removes_float_residue(self):
        # location 0.15 + plausibility 0.20 + image 0.05 is 0.40 in decimal,
        # but the unquantized binary sum lands just below the threshold.
        raw = 0.0
        for part in (0.15, 0.0, 0.0, 0.20, 0.0, 0.05):  # summation order of the original scorer
            raw += part
        self.assertLess(raw, 0.40)
        self.assertEqual(decide_action_baseline(raw, 0.5), "store_only")
        self.assertEqual(decide_action_baseline(rep.quantize_score(raw), 0.5), "flag_review")


# ── End-to-end processing, persistence, provenance ───────────────────────────

class TestProcessReport(ReporterTestCase):
    async def test_stored_report_carries_replayable_provenance(self):
        self.llm.replies = [text_reply(location_text="Kelaniya", hazard_type="flood"), vision_reply()]
        out = await self.reporter.process_report(PHONE_A, "Water rising in Kelaniya", "en",
                                                 image_bytes=JPEG, image_mime="image/jpeg", message_id="wamid.1")
        self.assertTrue(out["stored"])
        row = self.rows("SELECT * FROM community_reports")[0]
        prov = json.loads(row["scoring_provenance"])
        parts = prov["confidence_components"]
        recomputed = rep.quantize_score(sum(parts[k] for k in ("completeness", "plausibility",
                                                               "corroboration", "image_evidence")))
        self.assertEqual(prov["confidence"], recomputed)
        self.assertEqual(row["confidence_score"], round(recomputed, 3))
        self.assertEqual(prov["policy"]["active"], rep.POLICY_BASELINE)
        self.assertEqual(row["shadow_action"], decide_action_candidate(prov["confidence"], prov["severity"]))
        self.assertEqual(prov["visual"]["outcome"], "supporting")
        self.assertEqual(prov["visual"]["analysis"]["model_snapshot"], "gpt-4o-mini-fake")
        self.assertEqual(len(prov["prompts"]["extraction"]), 12)
        self.assertEqual(prov["extraction"]["status"], "ok")

    async def test_vision_failure_contributes_nothing(self):
        self.llm.replies = [text_reply(hazard_type="unknown", report_domain="unknown"), "garbage"]
        await self.reporter.process_report(PHONE_A, "see photo, Ratnapura", "en", image_bytes=JPEG)
        row = self.rows("SELECT * FROM community_reports")[0]
        self.assertEqual(row["image_evidence_score"], 0.0)
        self.assertEqual(row["hazard_type"], "unknown")
        self.assertIsNone(row["image_hazard_category"])
        self.assertEqual(json.loads(row["scoring_provenance"])["visual"]["outcome"], "unavailable")

    async def test_malformed_text_reply_uses_keyword_fallback(self):
        self.llm.replies = ["{not json"]
        out = await self.reporter.process_report(PHONE_A, "landslide happening now", "en")
        self.assertTrue(out["needs_clarification"])  # fallback has no location
        meta = out["pending_report"]["_extraction_meta"]
        self.assertEqual(meta["status"], "fallback")
        self.assertEqual(out["pending_report"]["hazard_type"], "landslide")

    async def test_storage_failure_is_not_acknowledged_and_writes_nothing(self):
        with sqlite3.connect(Config.COMMUNITY_REPORTS_DB) as conn:
            conn.execute("CREATE TRIGGER fail_insert BEFORE INSERT ON report_status_log "
                         "BEGIN SELECT RAISE(ABORT, 'disk full simulation'); END")
        self.llm.replies = [text_reply()]
        out = await self.reporter.process_report(PHONE_A, "crack in Ratnapura", "en")
        self.assertFalse(out["stored"])
        self.assertIsNone(out["report_id"])
        self.assertEqual(self.rows("SELECT * FROM community_reports"), [])
        self.assertEqual(self.rows("SELECT * FROM user_reliability"), [])

    async def test_duplicate_message_id_stores_once_without_inference(self):
        self.llm.replies = [text_reply()]
        first = await self.reporter.process_report(PHONE_A, "crack in Ratnapura", "en", message_id="wamid.X")
        second = await self.reporter.process_report(PHONE_A, "crack in Ratnapura", "en", message_id="wamid.X")
        self.assertEqual(first["report_id"], second["report_id"])
        self.assertTrue(second["duplicate"])
        self.assertEqual(len(self.llm.calls), 1)
        self.assertEqual(len(self.rows("SELECT * FROM community_reports")), 1)


    async def test_concurrent_redelivery_is_stopped_by_unique_index(self):
        self.llm.replies = [text_reply(), text_reply()]
        a, b = await asyncio.gather(
            self.reporter.process_report(PHONE_A, "crack in Ratnapura", "en", message_id="wamid.C"),
            self.reporter.process_report(PHONE_A, "crack in Ratnapura", "en", message_id="wamid.C"))
        self.assertEqual(a["report_id"], b["report_id"])
        self.assertEqual(len(self.rows("SELECT * FROM community_reports")), 1)
        self.assertEqual(self.rows("SELECT n_reports FROM user_reliability"), [{"n_reports": 1}])

# ── Clarification through the orchestrator ───────────────────────────────────

class FakeAgent:
    """Routes every message to the real submit_community_report tool closure."""

    def __init__(self, reporter):
        self.reporter = reporter
        self.invocations = 0

    async def ainvoke(self, message, language, phone_number, history, report_sink=None, message_id=None):
        self.invocations += 1
        tools = build_tools(None, self.reporter, None, language, phone_number,
                            report_sink=report_sink, message_id=message_id)
        submit = next(t for t in tools if t.name == "submit_community_report")
        return await submit.ainvoke({"report_text": message})


class TestClarificationFlow(ReporterTestCase):
    def setUp(self):
        super().setUp()
        ConversationMemory._local_sessions.clear()
        ConversationMemory._local_conversations.clear()
        self.orch = WhatsAppOrchestrator.__new__(WhatsAppOrchestrator)
        self.orch.memory = ConversationMemory(None)
        self.orch.reporter = self.reporter
        self.orch.agent = FakeAgent(self.reporter)
        for phone in (PHONE_A, PHONE_B):
            self.orch.memory.update_session(phone, {"phone_number": phone, "language": "en"})

    async def send(self, phone, text, mid, image=None):
        return await self.orch.process_message(phone, text, mid, image_bytes=image,
                                               image_mime="image/jpeg" if image else None)

    def stored(self):
        return self.rows("SELECT * FROM community_reports")

    async def test_text_report_via_agent_then_location_reply(self):
        self.llm.replies = [text_reply(location_text=None, location_specific=False,
                                       clarification_question="Which village is this in?")]
        reply = await self.send(PHONE_A, "There is a crack on the slope behind my house", "m1")
        self.assertEqual(reply, "Which village is this in?")
        session = self.orch.memory.get_session(PHONE_A)
        self.assertEqual(session["report_state"], "awaiting_clarification")

        reply = await self.send(PHONE_A, "Ratnapura, near the temple", "m2")
        self.assertIn("Report", reply)
        rows = self.stored()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["location_text"], "Ratnapura, near the temple")
        self.assertEqual(rows[0]["source_message_id"], "m2")
        self.assertEqual(len(self.llm.calls), 1)  # no re-extraction on continuation
        self.assertEqual(self.orch.agent.invocations, 1)
        self.assertNotIn("report_state", self.orch.memory.get_session(PHONE_A))

    async def test_image_report_then_location_reply_runs_vision_once(self):
        self.llm.replies = [text_reply(location_text=None, location_specific=False), vision_reply()]
        await self.send(PHONE_A, "Look at this", "m1", image=JPEG)
        reply = await self.send(PHONE_A, "Kelaniya main road", "m2")
        self.assertIn("Report", reply)
        self.assertEqual(sum(self.llm.is_vision(i) for i in range(len(self.llm.calls))), 1)
        row = self.stored()[0]
        self.assertEqual(json.loads(row["scoring_provenance"])["visual"]["outcome"], "supporting")

    async def test_second_photo_during_clarification_is_not_reanalysed(self):
        self.llm.replies = [text_reply(location_text=None, location_specific=False), vision_reply()]
        await self.send(PHONE_A, "Look at this", "m1", image=JPEG)
        await self.send(PHONE_A, "", "m2", image=JPEG)  # empty caption: still pending
        self.assertEqual(self.stored(), [])
        await self.send(PHONE_A, "Kelaniya", "m3")
        prov = json.loads(self.stored()[0]["scoring_provenance"])
        self.assertEqual(prov["visual"]["images_not_analysed"], 1)
        self.assertEqual(len(self.llm.calls), 2)

    async def test_cancel_discards_pending_report(self):
        self.llm.replies = [text_reply(location_text=None, location_specific=False)]
        await self.send(PHONE_A, "crack on slope", "m1")
        reply = await self.send(PHONE_A, "cancel", "m2")
        self.assertIn("cancelled", reply)
        self.assertEqual(self.stored(), [])
        self.assertNotIn("pending_report", self.orch.memory.get_session(PHONE_A))

    async def test_expired_pending_report_is_dropped(self):
        self.llm.replies = [text_reply(location_text=None, location_specific=False), text_reply()]
        await self.send(PHONE_A, "crack on slope", "m1")
        session = self.orch.memory.get_session(PHONE_A)
        session["pending_report_at"] = (datetime.now(timezone.utc) - timedelta(
            minutes=Config.PENDING_REPORT_TTL_MINUTES + 1)).isoformat()
        await self.send(PHONE_A, "New report: crack in Ratnapura", "m2")
        self.assertEqual(self.orch.agent.invocations, 2)  # routed as a new message
        self.assertEqual(self.stored()[0]["location_text"], "Ratnapura")

    async def test_pending_report_is_isolated_per_user(self):
        self.llm.replies = [text_reply(location_text=None, location_specific=False),
                            text_reply(location_text="Galle")]
        await self.send(PHONE_A, "crack on slope", "m1")
        await self.send(PHONE_B, "flooding in Galle", "m2")
        self.assertEqual(self.stored()[0]["location_text"], "Galle")
        self.assertEqual(self.orch.memory.get_session(PHONE_A)["report_state"], "awaiting_clarification")
        self.assertNotIn("report_state", self.orch.memory.get_session(PHONE_B))

    async def test_webhook_redelivery_is_ignored(self):
        self.llm.replies = [text_reply()]
        await self.send(PHONE_A, "crack in Ratnapura", "m1")
        self.assertIsNone(await self.send(PHONE_A, "crack in Ratnapura", "m1"))
        self.assertEqual(len(self.stored()), 1)
        self.assertEqual(self.orch.agent.invocations, 1)


# ── Human review ─────────────────────────────────────────────────────────────

class TestReview(ReporterTestCase):
    def reliability(self, user="u1"):
        return self.rows("SELECT * FROM user_reliability WHERE user_hash = ?", (user,))[0]

    def test_verification_is_idempotent(self):
        self.insert_report("R1", "u1")
        self.assertTrue(self.reporter.review_report("R1", "verified")["changed"])
        self.assertFalse(self.reporter.review_report("R1", "verified")["changed"])
        self.assertEqual(self.reliability()["reliability"], 0.65)
        self.assertEqual(len(self.rows("SELECT * FROM review_events")), 1)

    def test_correction_replays_as_if_wrong_review_never_happened(self):
        for rid in ("R1", "R2"):
            self.insert_report(rid, "u1")
        self.reporter.review_report("R1", "verified")
        self.reporter.review_report("R2", "false")
        self.reporter.review_report("R1", "false")  # R1 was reviewed wrongly
        rel = self.reliability()
        expected = reliability_update(reliability_update(0.5, False), False)
        self.assertEqual(rel["reliability"], expected)
        self.assertEqual((rel["n_verified"], rel["n_rejected"]), (0, 2))
        self.assertEqual(self.rows("SELECT status, review_outcome FROM community_reports WHERE report_id='R1'"),
                         [{"status": "closed", "review_outcome": "false"}])

    def test_retraction_restores_prior_reliability(self):
        self.insert_report("R1", "u1")
        self.reporter.review_report("R1", "verified")
        self.reporter.review_report("R1", "retracted")
        self.assertEqual(self.reliability()["reliability"], 0.5)
        self.assertFalse(self.reporter.review_report("R1", "retracted")["changed"])

    def test_review_is_atomic(self):
        self.insert_report("R1", "u1")
        with mock.patch.object(CommunityReporter, "_replay_reliability", side_effect=RuntimeError):
            with self.assertRaises(RuntimeError):
                self.reporter.review_report("R1", "verified")
        self.assertEqual(self.rows("SELECT * FROM review_events"), [])
        self.assertEqual(self.rows("SELECT status FROM community_reports"), [{"status": "new"}])

    def test_bad_inputs(self):
        with self.assertRaises(KeyError):
            self.reporter.review_report("NOPE", "verified")
        self.insert_report("R1", "u1")
        with self.assertRaises(ValueError):
            self.reporter.review_report("R1", "approve")

    def test_pre_existing_reliability_is_the_replay_base(self):
        path = os.path.join(self.tmp.name, "legacy.db")
        with sqlite3.connect(path) as conn:
            conn.execute("CREATE TABLE user_reliability (user_hash TEXT PRIMARY KEY, reliability REAL NOT NULL, "
                         "n_reports INTEGER NOT NULL DEFAULT 0, n_verified INTEGER NOT NULL DEFAULT 0, "
                         "n_rejected INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL)")
            conn.execute("INSERT INTO user_reliability VALUES ('u1', 0.8, 3, 2, 0, 'x')")
        Config.COMMUNITY_REPORTS_DB = path
        self.reporter = CommunityReporter()
        self.insert_report("R1", "u1")
        self.reporter.review_report("R1", "verified")
        self.assertEqual(self.reliability()["reliability"], reliability_update(0.8, True))


# ── Retention ────────────────────────────────────────────────────────────────

class TestRetention(ReporterTestCase):
    def image(self, name, age_days=0):
        os.makedirs(Config.REPORT_IMAGES_DIR, exist_ok=True)
        path = os.path.join(Config.REPORT_IMAGES_DIR, name)
        with open(path, "wb") as f:
            f.write(JPEG)
        t = (datetime.now(timezone.utc) - timedelta(days=age_days)).timestamp()
        os.utime(path, (t, t))
        return path

    def test_unreviewed_expiry_archives_without_touching_reliability(self):
        old = datetime.now(timezone.utc) - timedelta(days=8)
        self.insert_report("OLD", "u1", created_at=old)
        self.insert_report("FALSE", "u1", created_at=old)
        self.reporter.review_report("FALSE", "false")
        before = self.rows("SELECT reliability FROM user_reliability")
        stats = self.reporter.apply_retention()
        self.assertEqual(stats["archived"], 1)
        self.assertEqual(self.rows("SELECT reliability FROM user_reliability"), before)
        statuses = {r["report_id"]: (r["status"], r["review_outcome"])
                    for r in self.rows("SELECT report_id, status, review_outcome FROM community_reports")}
        self.assertEqual(statuses, {"OLD": ("archived", None), "FALSE": ("closed", "false")})

    def test_low_confidence_unknown_is_deleted_with_its_image(self):
        path = self.image("a.jpg", age_days=15)
        self.insert_report("U", "u1", created_at=datetime.now(timezone.utc) - timedelta(days=15),
                           domain="unknown", conf=0.2, image_path=path)
        self.assertEqual(self.reporter.apply_retention()["deleted"], 1)
        self.assertFalse(os.path.exists(path))
        self.assertEqual(self.rows("SELECT new_status FROM report_status_log WHERE report_id='U' "
                                   "ORDER BY id DESC LIMIT 1"), [{"new_status": "deleted"}])

    def test_old_images_and_orphans_are_removed(self):
        Config.IMAGE_RETENTION_DAYS = 30
        kept = self.image("recent.jpg")
        aged = self.image("aged.jpg", age_days=31)
        orphan_old = self.image("orphan_old.jpg", age_days=1)
        orphan_new = self.image("orphan_new.jpg")
        self.insert_report("V", "u1", status="verified", image_path=aged,
                           created_at=datetime.now(timezone.utc) - timedelta(days=31))
        self.insert_report("N", "u1", image_path=kept)
        stats = self.reporter.apply_retention()
        self.assertEqual((stats["images_deleted"], stats["orphan_images_deleted"]), (1, 1))
        self.assertTrue(os.path.exists(kept) and os.path.exists(orphan_new))
        self.assertFalse(os.path.exists(aged) or os.path.exists(orphan_old))
        self.assertIsNone(self.rows("SELECT image_path FROM community_reports WHERE report_id='V'")[0]["image_path"])

    def test_scheduler_job_runs_without_lock_errors(self):
        from agent import scheduler
        self.insert_report("OLD", "u1", created_at=datetime.now(timezone.utc) - timedelta(days=8))
        scheduler._reporter_instance = self.reporter
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            scheduler._retention_job()
        scheduler._reporter_instance = None
        self.assertNotIn("error", out.getvalue())
        self.assertNotIn("locked", out.getvalue())
        self.assertEqual(self.rows("SELECT status FROM community_reports"), [{"status": "archived"}])


# ── Pseudonyms and privacy ───────────────────────────────────────────────────

class TestPrivacy(ReporterTestCase):
    async def test_keyed_pseudonym_migrates_legacy_history(self):
        legacy = rep._legacy_hash_phone(PHONE_A)
        self.insert_report("R1", legacy)
        self.reporter.review_report("R1", "verified")
        Config.REPORTER_ID_KEY = "test-secret"
        keyed = self.reporter._resolve_user_hash(PHONE_A)
        self.assertTrue(keyed.startswith("k1_"))
        self.assertNotEqual(keyed, legacy)
        for table in ("community_reports", "user_reliability", "review_events"):
            self.assertEqual({r["user_hash"] for r in self.rows(f"SELECT user_hash FROM {table}")}, {keyed})
        self.assertEqual(self.rows("SELECT reliability FROM user_reliability")[0]["reliability"], 0.65)

    async def test_no_raw_phone_number_in_database_or_logs(self):
        Config.REPORTER_ID_KEY = "test-secret"
        self.llm.replies = [text_reply()]
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            await self.reporter.process_report(PHONE_A, "crack in Ratnapura", "en")
        self.assertNotIn(PHONE_A, out.getvalue())
        with open(Config.COMMUNITY_REPORTS_DB, "rb") as f:
            self.assertNotIn(PHONE_A.encode(), f.read())


if __name__ == "__main__":
    unittest.main()
