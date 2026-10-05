"""
Admin API and panel. Every route except the login pages requires require_admin().

Sign-in: an authorised WhatsApp number messages "admin" to the bot and receives a
single-use link (see agent/admin_auth.py). The panel itself is webui/admin.html.
"""
import base64
import html
import json
import os
import sqlite3
from datetime import datetime, timezone
from urllib.parse import parse_qs

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse

from agent import admin_auth
from agent.scheduler import trigger_alert_now, trigger_sheets_sync_now
from config import Config

router = APIRouter(prefix="/admin")

_reporter = None
_UI_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "webui", "admin.html")
_PAGE_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
                                "connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"),
}


def configure(reporter) -> None:
    global _reporter
    _reporter = reporter


def admin_actor(request: Request) -> str:
    return admin_auth.require_admin(request)


def _page(title: str, body: str, status: int = 200) -> HTMLResponse:
    doc = ("<!DOCTYPE html><html lang='en'><head><meta charset='UTF-8'>"
           "<meta name='viewport' content='width=device-width, initial-scale=1'>"
           f"<title>{html.escape(title)}</title><style>body{{font-family:Arial,sans-serif;background:#f0f4f8;"
           "display:flex;justify-content:center;padding:40px 16px}.c{background:#fff;border-radius:12px;padding:32px;"
           "max-width:460px;box-shadow:0 4px 20px rgba(0,0,0,.1)}button{padding:12px 20px;border:0;border-radius:7px;"
           "background:#27ae60;color:#fff;font-weight:700;font-size:1rem;cursor:pointer}p{color:#444;line-height:1.5}"
           f"</style></head><body><div class='c'><h2>{html.escape(title)}</h2>{body}</div></body></html>")
    return HTMLResponse(doc, status_code=status, headers=_PAGE_HEADERS)


_NEED_LINK = ("<p>Message <b>admin</b> to the WhatsApp bot from your authorised number to get a "
              "login link. Links work once and expire after 10 minutes.</p>")


# ── Sign-in ───────────────────────────────────────────────────────────────

@router.get("/login")
async def login_form(t: str = ""):
    """Shows a confirmation button; the link is only consumed by the POST, so link scanners can't spend it."""
    if not t or not admin_auth.peek_login_token(t):
        return _page("Link not valid", "<p>This login link is invalid, expired or already used.</p>" + _NEED_LINK, 400)
    return _page("Admin sign-in", "<p>Sign in to the Early Warning admin panel?</p>"
                 f"<form method='post' action='/admin/login'><input type='hidden' name='t' value='{html.escape(t)}'>"
                 "<button type='submit'>Sign in</button></form>")


@router.post("/login")
async def login(request: Request):
    token = parse_qs((await request.body()).decode("utf-8", "replace")).get("t", [""])[0]
    sub = admin_auth.consume_login_token(token) if token else None
    if not sub:
        return _page("Link not valid", "<p>This login link is invalid, expired or already used.</p>" + _NEED_LINK, 400)
    print(f"[admin] sign-in sub={sub}")
    response = RedirectResponse("/admin/ui", status_code=303, headers=_PAGE_HEADERS)
    response.set_cookie(admin_auth.COOKIE_NAME, admin_auth.make_session(sub), max_age=admin_auth.SESSION_TTL_S,
                        httponly=True, secure=True, samesite="lax", path="/admin")
    return response


@router.post("/logout")
async def logout():
    response = JSONResponse({"status": "ok"})
    response.delete_cookie(admin_auth.COOKIE_NAME, path="/admin")
    return response


@router.get("/ui")
async def panel(request: Request):
    if not admin_auth.read_session(request.cookies.get(admin_auth.COOKIE_NAME, "")):
        return _page("Sign in required", _NEED_LINK, 401)
    return FileResponse(_UI_FILE, media_type="text/html", headers=_PAGE_HEADERS)


@router.get("/session")
async def session_info(actor: str = Depends(admin_actor)):
    return {"ok": True, "warnings_editing": bool(Config.WARNINGS_GITHUB_TOKEN)}


# ── Warnings file (data.json in the repo, edited with a server-side token) ─

def _contents_url() -> str:
    return f"https://api.github.com/repos/{Config.WARNINGS_REPO}/contents/{Config.WARNINGS_PATH}"


def _gh_headers() -> dict:
    return {"Authorization": f"Bearer {Config.WARNINGS_GITHUB_TOKEN}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"}


def _require_warnings_config() -> None:
    if not Config.WARNINGS_GITHUB_TOKEN:
        raise HTTPException(status_code=503, detail="Warnings editing is not configured (WARNINGS_GITHUB_TOKEN).")


async def _read_warnings_file(client: httpx.AsyncClient) -> dict:
    r = await client.get(_contents_url(), params={"ref": Config.WARNINGS_BRANCH}, headers=_gh_headers())
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=f"GitHub returned HTTP {r.status_code}")
    meta = r.json()
    return {"sha": meta["sha"], "data": json.loads(base64.b64decode(meta["content"]))}


@router.get("/warnings")
async def get_warnings(actor: str = Depends(admin_actor)):
    _require_warnings_config()
    async with httpx.AsyncClient(timeout=15) as client:
        current = await _read_warnings_file(client)
    return {"warnings": current["data"].get("warnings", {}), "last_updated": current["data"].get("last_updated"),
            "sha": current["sha"]}


@router.post("/warnings")
async def save_warnings(request: Request, actor: str = Depends(admin_actor)):
    _require_warnings_config()
    try:
        body = await request.json()
        incoming, sha = body["warnings"], body["sha"]
    except (ValueError, KeyError, TypeError):
        raise HTTPException(status_code=400, detail="Expected JSON with 'warnings' and 'sha'")
    async with httpx.AsyncClient(timeout=15) as client:
        current = await _read_warnings_file(client)
        if sha != current["sha"]:
            raise HTTPException(status_code=409, detail="The warnings changed since you loaded them. Reload and try again.")
        known = current["data"].get("warnings", {})
        if not isinstance(incoming, dict) or set(incoming) != set(known) or not all(isinstance(v, bool) for v in incoming.values()):
            raise HTTPException(status_code=400, detail="Warnings must be true/false for the existing districts")
        data = {**current["data"], "warnings": incoming, "last_updated": datetime.now(timezone.utc).isoformat()}
        active = [d for d, on in incoming.items() if on]
        message = ("update warnings: active in " + ", ".join(active)) if active else "update warnings: all clear"
        put = await client.put(_contents_url(), headers=_gh_headers(), json={
            "message": message, "branch": Config.WARNINGS_BRANCH, "sha": current["sha"],
            "content": base64.b64encode(json.dumps(data, indent=2, ensure_ascii=False).encode()).decode()})
    if put.status_code in (409, 422):
        raise HTTPException(status_code=409, detail="The warnings changed since you loaded them. Reload and try again.")
    if put.status_code not in (200, 201):
        raise HTTPException(status_code=502, detail=f"GitHub returned HTTP {put.status_code}")
    print(f"[admin] warnings saved actor={actor} active={len(active)}")
    return {"status": "ok", "sha": put.json()["content"]["sha"], "active": len(active)}


# ── Alerts, registrations ─────────────────────────────────────────────────

@router.post("/trigger-alerts")
async def admin_trigger_alerts(actor: str = Depends(admin_actor)):
    """Manually trigger one alert cycle (crawl + send)."""
    print(f"[admin] trigger-alerts actor={actor}")
    return {"status": "ok", "stats": await trigger_alert_now()}


@router.post("/sync-registrations")
async def admin_sync_registrations(actor: str = Depends(admin_actor)):
    """Manually pull the latest registrations from Google Sheets."""
    print(f"[admin] sync-registrations actor={actor}")
    return {"status": "ok", "synced": await trigger_sheets_sync_now()}


@router.get("/registrations/count")
async def admin_registration_count(actor: str = Depends(admin_actor)):
    """Return the number of registered subscribers."""
    from agent.registration import count_registrations
    return {"count": count_registrations()}


# ── Community report endpoints ────────────────────────────────────────────

_REPORT_COLUMNS = """report_id, timestamp, language, report_domain,
                           hazard_type, category, location_text, description,
                           confidence_score, severity_score, action, status,
                           people_at_risk, ongoing, image_path, image_evidence_score,
                           image_hazard_category"""


@router.get("/reports")
async def admin_list_reports(status: str = "new", limit: int = 50, actor: str = Depends(admin_actor)):
    """
    List community reports.
    status: new | monitored | under_review | verified | closed | archived
            OR an action value: escalate | flag_review | monitor | store_only
    When the value matches a known action it filters by action instead of status.
    """
    action_values = {"escalate", "flag_review", "monitor", "store_only"}
    try:
        with sqlite3.connect(Config.COMMUNITY_REPORTS_DB) as conn:
            conn.row_factory = sqlite3.Row
            if status in action_values:
                # Only show reports not yet reviewed — exclude verified/closed/archived
                rows = conn.execute(f"""
                    SELECT {_REPORT_COLUMNS}
                    FROM community_reports
                    WHERE action = ?
                      AND status NOT IN ('verified', 'closed', 'archived')
                    ORDER BY severity_score DESC, timestamp DESC
                    LIMIT ?
                """, (status, limit)).fetchall()
            else:
                rows = conn.execute(f"""
                    SELECT {_REPORT_COLUMNS}
                    FROM community_reports
                    WHERE status = ?
                    ORDER BY severity_score DESC, timestamp DESC
                    LIMIT ?
                """, (status, limit)).fetchall()
        return {"reports": [dict(r) for r in rows]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _review(report_id: str, actor: str, decision: str):
    try:
        result = _reporter.review_report(report_id, decision, reviewer=actor)
    except KeyError:
        raise HTTPException(status_code=404, detail="Report not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    print(f"[admin] review {report_id} {decision} actor={actor}")
    return {"status": "ok", "report_id": report_id, "new_status": result["status"],
            "review_outcome": result["review_outcome"], "changed": result["changed"]}


@router.post("/reports/{report_id}/verify")
async def admin_verify_report(report_id: str, actor: str = Depends(admin_actor)):
    """Review a report as verified. Repeating it is a no-op (idempotent)."""
    return _review(report_id, actor, "verified")


@router.post("/reports/{report_id}/reject")
async def admin_reject_report(report_id: str, actor: str = Depends(admin_actor)):
    """Review a report as a verified false report (status 'closed')."""
    return _review(report_id, actor, "false")


@router.post("/reports/{report_id}/retract")
async def admin_retract_review(report_id: str, actor: str = Depends(admin_actor)):
    """Withdraw a mistaken review; the contributor's reliability is replayed without it."""
    return _review(report_id, actor, "retracted")


@router.get("/reports/stats")
async def admin_report_stats(actor: str = Depends(admin_actor)):
    """Summary stats for the community reports dashboard."""
    try:
        with sqlite3.connect(Config.COMMUNITY_REPORTS_DB) as conn:
            total     = conn.execute("SELECT COUNT(*) FROM community_reports").fetchone()[0]
            new_ct    = conn.execute("SELECT COUNT(*) FROM community_reports WHERE status='new'").fetchone()[0]
            escalated = conn.execute("SELECT COUNT(*) FROM community_reports WHERE status='escalated'").fetchone()[0]
            review    = conn.execute("SELECT COUNT(*) FROM community_reports WHERE action='flag_review' AND status='new'").fetchone()[0]
            users     = conn.execute("SELECT COUNT(*) FROM user_reliability").fetchone()[0]
        return {"total": total, "new": new_ct, "escalated": escalated, "needs_review": review, "tracked_users": users}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
