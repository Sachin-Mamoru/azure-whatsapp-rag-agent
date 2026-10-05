"""
Admin access: WhatsApp login links, signed sessions, CSRF, route protection,
warnings editing (GitHub mocked) and the orchestrator "admin" command.

Run:  python -m unittest discover -s tests -v   (no network, no API key)
"""
import base64
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-test-not-used")
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:1/0")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from agent import admin_auth, admin_routes  # noqa: E402
from agent.memory import ConversationMemory  # noqa: E402
from agent.orchestrator import WhatsAppOrchestrator  # noqa: E402
from agent.reporter import CommunityReporter  # noqa: E402
from config import Config  # noqa: E402

ADMIN_A, ADMIN_B, STRANGER = "94000000001", "94000000002", "94000000999"
HDR = {"X-Requested-With": "admin-ui"}


class FakeGitHub:
    """Stands in for httpx.AsyncClient against the contents API."""
    file = {}
    puts = []

    class _Resp:
        def __init__(self, status, body):
            self.status_code, self._body = status, body

        def json(self):
            return self._body

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, params=None, headers=None):
        assert headers["Authorization"] == "Bearer gh-test"
        f = FakeGitHub.file
        return self._Resp(200, {"sha": f["sha"], "content": base64.b64encode(f["text"].encode()).decode()})

    async def put(self, url, headers=None, json=None):
        f = FakeGitHub.file
        if json["sha"] != f["sha"]:
            return self._Resp(409, {})
        FakeGitHub.puts.append(json)
        f["text"] = base64.b64decode(json["content"]).decode()
        f["sha"] = "sha-" + str(len(FakeGitHub.puts))
        return self._Resp(200, {"content": {"sha": f["sha"]}})


class AdminTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = {k: getattr(Config, k) for k in (
            "ADMIN_SECRET", "ADMIN_PHONE_NUMBERS", "ADMIN_SESSION_KEY", "ADMIN_PUBLIC_URL", "WARNINGS_GITHUB_TOKEN",
            "COMMUNITY_REPORTS_DB", "REPORT_IMAGES_DIR")}
        Config.ADMIN_SECRET = "script-secret"
        Config.ADMIN_PHONE_NUMBERS = f"{ADMIN_A}, +94 000 000 002"
        Config.ADMIN_SESSION_KEY = "k" * 32
        Config.ADMIN_PUBLIC_URL = "https://bot.test"
        Config.WARNINGS_GITHUB_TOKEN = "gh-test"
        Config.COMMUNITY_REPORTS_DB = os.path.join(self.tmp.name, "reports.db")
        Config.REPORT_IMAGES_DIR = os.path.join(self.tmp.name, "images")
        admin_auth._login_links.clear()
        admin_auth._last_link_at.clear()
        self.reporter = CommunityReporter()
        admin_routes.configure(self.reporter)
        app = FastAPI()
        app.include_router(admin_routes.router)
        self.app = app
        self.client = TestClient(app, base_url="https://bot.test")
        FakeGitHub.puts = []
        FakeGitHub.file = {"sha": "sha-0", "text": json.dumps(
            {"warnings": {"Colombo": False, "Galle": True}, "last_updated": "old", "note": "keep me"})}
        patcher = mock.patch.object(admin_routes.httpx, "AsyncClient", FakeGitHub)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        for k, v in self.saved.items():
            setattr(Config, k, v)
        self.tmp.cleanup()

    def link_token(self, phone=ADMIN_A):
        status, url = admin_auth.create_login_link(phone)
        self.assertEqual(status, "ok")
        return url.split("t=")[1]

    def sign_in(self, client=None, phone=ADMIN_A):
        client = client or self.client
        r = client.post("/admin/login", content=f"t={self.link_token(phone)}",
                        headers={"Content-Type": "application/x-www-form-urlencoded"}, follow_redirects=False)
        self.assertEqual(r.status_code, 303, r.text)
        return r

    def insert_report(self, report_id="R1", user="u1"):
        record = {c: None for c in CommunityReporter._REPORT_COLUMNS}
        record.update(report_id=report_id, timestamp="2026-10-05T00:00:00+00:00", user_hash=user, language="en",
                      report_domain="hazard", hazard_type="flood", category="flood", location_text="Kandy",
                      description="seeded", confidence_score=0.5, severity_score=0.5, action="monitor",
                      status="new", people_at_risk=0, ongoing=0, image_evidence_score=0.0,
                      created_at="2026-10-05T00:00:00+00:00")
        self.reporter._store_report(record)


class TestLoginLinks(AdminTestCase):
    def test_only_listed_numbers_in_any_format_are_admins(self):
        self.assertTrue(admin_auth.is_admin_phone("94000000001"))
        self.assertTrue(admin_auth.is_admin_phone("+94 000-000-001"))
        self.assertTrue(admin_auth.is_admin_phone(ADMIN_B))
        self.assertFalse(admin_auth.is_admin_phone(STRANGER))
        Config.ADMIN_PHONE_NUMBERS = ""
        self.assertFalse(admin_auth.is_admin_phone(ADMIN_A))

    def test_link_is_issued_once_per_minute_and_only_to_admins(self):
        status, url = admin_auth.create_login_link(ADMIN_A, now=1000.0)
        self.assertEqual(status, "ok")
        self.assertTrue(url.startswith("https://bot.test/admin/login?t="))
        self.assertEqual(admin_auth.create_login_link(ADMIN_A, now=1030.0)[0], "cooldown")
        self.assertEqual(admin_auth.create_login_link(ADMIN_A, now=1061.0)[0], "ok")
        self.assertEqual(admin_auth.create_login_link(STRANGER)[0], "disabled")

    def test_link_is_disabled_without_a_session_key(self):
        Config.ADMIN_SESSION_KEY = ""
        self.assertEqual(admin_auth.create_login_link(ADMIN_A)[0], "disabled")

    def test_token_is_single_use_and_expires(self):
        _, url = admin_auth.create_login_link(ADMIN_A, now=1000.0)
        token = url.split("t=")[1]
        self.assertIsNotNone(admin_auth.consume_login_token(token, now=1100.0))
        self.assertIsNone(admin_auth.consume_login_token(token, now=1101.0))
        _, url2 = admin_auth.create_login_link(ADMIN_B, now=2000.0)
        self.assertIsNone(admin_auth.consume_login_token(url2.split("t=")[1], now=2000.0 + 601))
        self.assertIsNone(admin_auth.consume_login_token("not-a-token"))

    def test_each_admin_gets_a_distinct_subject_and_no_phone_number_leaks(self):
        a, b = admin_auth._subject(ADMIN_A), admin_auth._subject(ADMIN_B)
        self.assertNotEqual(a, b)
        self.assertNotIn(ADMIN_A, a)


class TestSessions(AdminTestCase):
    def test_round_trip_tamper_expiry_and_key_change(self):
        cookie = admin_auth.make_session("sub1", now=1000.0)
        self.assertEqual(admin_auth.read_session(cookie, now=1000.0 + 3600), "sub1")
        self.assertIsNone(admin_auth.read_session(cookie, now=1000.0 + admin_auth.SESSION_TTL_S + 1))
        payload, _, sig = cookie.partition(".")
        forged = base64.urlsafe_b64encode(json.dumps({"sub": "admin2", "exp": 9999999999}).encode()).decode().rstrip("=")
        self.assertIsNone(admin_auth.read_session(forged + "." + sig, now=1000.0))
        self.assertIsNone(admin_auth.read_session(payload + ".deadbeef", now=1000.0))
        self.assertIsNone(admin_auth.read_session("garbage"))
        Config.ADMIN_SESSION_KEY = "z" * 32
        self.assertIsNone(admin_auth.read_session(cookie, now=1000.0))


class TestSignInFlow(AdminTestCase):
    def test_get_shows_a_button_and_does_not_spend_the_link(self):
        token = self.link_token()
        page = self.client.get(f"/admin/login?t={token}")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Sign in", page.text)
        self.assertEqual(page.headers["referrer-policy"], "no-referrer")
        self.assertTrue(admin_auth.peek_login_token(token))

    def test_post_signs_in_with_a_locked_down_cookie_and_cannot_be_replayed(self):
        token = self.link_token()
        body = {"content": f"t={token}", "headers": {"Content-Type": "application/x-www-form-urlencoded"}}
        r = self.client.post("/admin/login", follow_redirects=False, **body)
        self.assertEqual((r.status_code, r.headers["location"]), (303, "/admin/ui"))
        cookie = r.headers["set-cookie"].lower()
        for part in ("httponly", "secure", "samesite=lax", "path=/admin", f"max-age={admin_auth.SESSION_TTL_S}"):
            self.assertIn(part, cookie)
        replay = self.client.post("/admin/login", follow_redirects=False, **body)
        self.assertEqual(replay.status_code, 400)

    def test_bad_links_are_rejected_without_detail(self):
        self.assertEqual(self.client.get("/admin/login?t=nope").status_code, 400)
        self.assertEqual(self.client.get("/admin/login").status_code, 400)
        r = self.client.post("/admin/login", content="t=nope", headers={"Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual(r.status_code, 400)

    def test_panel_needs_a_session_and_ships_a_csp(self):
        anon = self.client.get("/admin/ui")
        self.assertEqual(anon.status_code, 401)
        self.assertNotIn("Early Warning Admin", anon.text)
        self.sign_in()
        ui = self.client.get("/admin/ui")
        self.assertEqual(ui.status_code, 200)
        self.assertIn("Early Warning Admin", ui.text)
        self.assertIn("connect-src 'self'", ui.headers["content-security-policy"])
        self.assertEqual(ui.headers["cache-control"], "no-store")

    def test_logout_ends_the_session(self):
        self.sign_in()
        self.assertEqual(self.client.get("/admin/reports/stats").status_code, 200)
        self.client.post("/admin/logout", headers=HDR)
        self.assertEqual(self.client.get("/admin/reports/stats").status_code, 401)

    def test_two_admins_have_independent_sessions(self):
        other = TestClient(self.app, base_url="https://bot.test")
        self.sign_in()
        self.assertEqual(other.get("/admin/reports/stats").status_code, 401)
        self.sign_in(other, phone=ADMIN_B)
        self.assertEqual(other.get("/admin/reports/stats").status_code, 200)


class TestRouteProtection(AdminTestCase):
    PUBLIC = {"/admin/login", "/admin/logout", "/admin/ui"}

    def test_every_other_admin_route_rejects_anonymous_callers(self):
        checked = 0
        for route in admin_routes.router.routes:
            if route.path in self.PUBLIC:
                continue
            path = route.path.replace("{report_id}", "x")
            for method in route.methods - {"HEAD", "OPTIONS"}:
                r = self.client.request(method, path)
                self.assertEqual(r.status_code, 401, f"{method} {route.path} is not protected")
                checked += 1
        self.assertGreaterEqual(checked, 10)

    def test_script_header_still_works_and_wrong_or_empty_secret_does_not(self):
        self.assertEqual(self.client.get("/admin/reports/stats", headers={"X-Admin-Token": "script-secret"}).status_code, 200)
        self.assertEqual(self.client.get("/admin/reports/stats", headers={"X-Admin-Token": "wrong"}).status_code, 401)
        self.assertEqual(self.client.get("/admin/reports/stats", headers={"X-Admin-Token": "ünïcode".encode("latin-1")}).status_code, 401)
        Config.ADMIN_SECRET = ""
        self.assertEqual(self.client.get("/admin/reports/stats", headers={"X-Admin-Token": ""}).status_code, 401)
        self.assertEqual(self.client.get("/admin/reports/stats").status_code, 401)

    def test_cookie_posts_need_the_csrf_header(self):
        self.sign_in()
        self.assertEqual(self.client.post("/admin/reports/R1/verify").status_code, 403)
        self.assertEqual(self.client.post("/admin/reports/R1/verify", headers={"X-Requested-With": "other"}).status_code, 403)
        self.assertEqual(self.client.post("/admin/reports/NOPE/verify", headers=HDR).status_code, 404)

    def test_tampered_cookie_is_rejected(self):
        self.sign_in()
        good = self.client.cookies.get("ewas_admin")
        self.client.cookies.clear()
        self.client.cookies.set("ewas_admin", good[:-3] + "abc", domain="bot.test", path="/admin")
        self.assertEqual(self.client.get("/admin/reports/stats").status_code, 401)

    def test_review_records_which_admin_acted(self):
        self.insert_report()
        self.sign_in()
        r = self.client.post("/admin/reports/R1/verify", headers=HDR)
        self.assertEqual((r.status_code, r.json()["new_status"]), (200, "verified"))
        import sqlite3
        reviewer = sqlite3.connect(Config.COMMUNITY_REPORTS_DB).execute(
            "SELECT reviewer FROM review_events WHERE report_id='R1'").fetchone()[0]
        self.assertEqual(reviewer, admin_auth._subject(ADMIN_A))


class TestWarnings(AdminTestCase):
    def test_read_returns_the_file_without_exposing_the_token(self):
        self.sign_in()
        r = self.client.get("/admin/warnings")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["warnings"], {"Colombo": False, "Galle": True})
        self.assertNotIn("gh-test", r.text)

    def test_save_updates_only_the_warnings_and_commits_with_a_clear_message(self):
        self.sign_in()
        r = self.client.post("/admin/warnings", headers=HDR, json={"warnings": {"Colombo": True, "Galle": False}, "sha": "sha-0"})
        self.assertEqual((r.status_code, r.json()["active"]), (200, 1))
        saved = json.loads(FakeGitHub.file["text"])
        self.assertEqual(saved["warnings"], {"Colombo": True, "Galle": False})
        self.assertEqual(saved["note"], "keep me")
        self.assertNotEqual(saved["last_updated"], "old")
        self.assertEqual(FakeGitHub.puts[0]["message"], "update warnings: active in Colombo")
        self.client.post("/admin/warnings", headers=HDR, json={"warnings": {"Colombo": False, "Galle": False}, "sha": "sha-1"})
        self.assertEqual(FakeGitHub.puts[1]["message"], "update warnings: all clear")

    def test_stale_edit_is_refused_instead_of_overwriting_someone_else(self):
        self.sign_in()
        self.client.post("/admin/warnings", headers=HDR, json={"warnings": {"Colombo": True, "Galle": True}, "sha": "sha-0"})
        stale = self.client.post("/admin/warnings", headers=HDR, json={"warnings": {"Colombo": False, "Galle": False}, "sha": "sha-0"})
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(len(FakeGitHub.puts), 1)

    def test_invalid_payloads_are_rejected_before_anything_is_written(self):
        self.sign_in()
        for body in ({"warnings": {"Colombo": True, "Galle": True, "Atlantis": True}, "sha": "sha-0"},
                     {"warnings": {"Colombo": True}, "sha": "sha-0"},
                     {"warnings": {"Colombo": "yes", "Galle": False}, "sha": "sha-0"},
                     {"warnings": ["Colombo"], "sha": "sha-0"}):
            self.assertEqual(self.client.post("/admin/warnings", headers=HDR, json=body).status_code, 400, body)
        self.assertEqual(self.client.post("/admin/warnings", headers=HDR, json={"nope": 1}).status_code, 400)
        self.assertEqual(FakeGitHub.puts, [])

    def test_editing_is_unavailable_until_a_token_is_configured(self):
        Config.WARNINGS_GITHUB_TOKEN = ""
        self.sign_in()
        self.assertEqual(self.client.get("/admin/warnings").status_code, 503)
        self.assertEqual(self.client.post("/admin/warnings", headers=HDR, json={"warnings": {}, "sha": "x"}).status_code, 503)
        self.assertFalse(self.client.get("/admin/session").json()["warnings_editing"])


class TestAdminCommand(AdminTestCase):
    def setUp(self):
        super().setUp()
        ConversationMemory._local_sessions.clear()
        ConversationMemory._local_conversations.clear()
        self.orch = WhatsAppOrchestrator.__new__(WhatsAppOrchestrator)
        self.orch.memory = ConversationMemory(None)
        self.orch.reporter = self.reporter
        self.agent_calls = []

        class Agent:
            async def ainvoke(inner, message, *a, **k):
                self.agent_calls.append(message)
                return "agent reply"
        self.orch.agent = Agent()
        for phone in (ADMIN_A, STRANGER):
            self.orch.memory.update_session(phone, {"phone_number": phone, "language": "en"})

    def send(self, phone, text):
        import asyncio
        return asyncio.run(self.orch.process_message(phone, text, "m-" + text))

    def test_admin_number_gets_a_link_not_an_agent_call(self):
        reply = self.send(ADMIN_A, "admin")
        self.assertIn("https://bot.test/admin/login?t=", reply)
        self.assertEqual(self.agent_calls, [])
        self.assertIn("Wait a minute", self.send(ADMIN_A, "Admin"))

    def test_other_numbers_get_no_link_and_no_hint(self):
        reply = self.send(STRANGER, "admin")
        self.assertEqual(reply, "agent reply")
        self.assertNotIn("/admin/login", reply)

    def test_admin_numbers_are_treated_normally_for_other_messages(self):
        self.assertEqual(self.send(ADMIN_A, "what is a landslide"), "agent reply")


if __name__ == "__main__":
    unittest.main()
