from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
import json
import requests
from agent.orchestrator import WhatsAppOrchestrator
from agent.scheduler import start_scheduler, stop_scheduler, trigger_alert_now, trigger_sheets_sync_now
from config import Config


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start background scheduler on boot, shut it down on exit."""
    # Verify WhatsApp token on startup
    try:
        resp = requests.get(
            f"https://graph.facebook.com/v22.0/{Config.WHATSAPP_PHONE_NUMBER_ID}",
            params={"access_token": Config.WHATSAPP_TOKEN},
            timeout=10
        )
        if resp.status_code == 200:
            print("[startup] ✅ WhatsApp token is valid.")
        else:
            err = resp.json().get("error", {})
            print(f"[startup] ❌ WhatsApp token INVALID: {err.get('message','unknown')} "
                  f"(code {err.get('code')}). Bot will NOT be able to reply to messages. "
                  f"Update WHATSAPP_TOKEN env var with a fresh token.")
    except Exception as e:
        print(f"[startup] ⚠️  Could not verify WhatsApp token: {e}")

    start_scheduler(reporter=orchestrator.reporter)
    yield
    stop_scheduler()


app = FastAPI(title="WhatsApp RAG Agent", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://sachin-mamoru.github.io"],
    allow_methods=["POST", "GET"],
    allow_headers=["X-Admin-Token", "Content-Type"],
)

# Initialize the orchestrator
orchestrator = WhatsAppOrchestrator()

@app.get("/")
async def root():
    return {"message": "WhatsApp RAG Agent is running"}

@app.get("/health/token")
async def check_token():
    """Check if the WhatsApp token is currently valid."""
    try:
        resp = requests.get(
            f"https://graph.facebook.com/v22.0/{Config.WHATSAPP_PHONE_NUMBER_ID}",
            params={"access_token": Config.WHATSAPP_TOKEN},
            timeout=10
        )
        if resp.status_code == 200:
            return {"token_valid": True, "phone_number_id": Config.WHATSAPP_PHONE_NUMBER_ID}
        err = resp.json().get("error", {})
        return {"token_valid": False, "error": err.get("message"), "code": err.get("code")}
    except Exception as e:
        return {"token_valid": False, "error": str(e)}

@app.get("/webhook")
async def verify_webhook(request: Request):
    """Verify webhook for WhatsApp"""
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")
    
    if mode == "subscribe" and token == Config.WHATSAPP_VERIFY_TOKEN:
        return PlainTextResponse(challenge)
    else:
        raise HTTPException(status_code=403, detail="Forbidden")

@app.post("/webhook")
async def receive_message(request: Request):
    """Receive and process WhatsApp messages"""
    try:
        body = await request.json()
        
        if body.get("object") == "whatsapp_business_account":
            for entry in body.get("entry", []):
                for change in entry.get("changes", []):
                    if change.get("field") == "messages":
                        value = change.get("value", {})
                        
                        # Process incoming messages
                        for message in value.get("messages", []):
                            phone_number = message.get("from")
                            message_body = message.get("text", {}).get("body", "")
                            message_id = message.get("id")
                            
                            if phone_number and message_body:
                                # Process message through orchestrator
                                response = await orchestrator.process_message(
                                    phone_number, message_body, message_id
                                )
                                
                                if response:
                                    await send_whatsapp_message(phone_number, response)
        
        return {"status": "ok"}
    
    except Exception as e:
        print(f"Error processing webhook: {e}")
        return {"status": "error"}

async def send_whatsapp_message(phone_number: str, message: str):
    """Send message via WhatsApp API"""
    url = f"{Config.WHATSAPP_BASE_URL}/messages"
    headers = {
        "Authorization": f"Bearer {Config.WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "messaging_product": "whatsapp",
        "to": phone_number,
        "type": "text",
        "text": {"body": message}
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error sending WhatsApp message: {e}")
        return None


# ── Admin / internal endpoints ─────────────────────────────────────────────
@app.post("/admin/trigger-alerts")
async def admin_trigger_alerts(request: Request):
    """
    Manually trigger one alert cycle (crawl + send).
    Requires the internal admin token via X-Admin-Token header.
    """
    _require_admin_token(request)
    stats = await trigger_alert_now()
    return {"status": "ok", "stats": stats}


@app.post("/admin/sync-registrations")
async def admin_sync_registrations(request: Request):
    """Manually pull the latest registrations from Google Sheets."""
    _require_admin_token(request)
    count = await trigger_sheets_sync_now()
    return {"status": "ok", "synced": count}


@app.get("/admin/registrations/count")
async def admin_registration_count(request: Request):
    """Return the number of registered subscribers."""
    _require_admin_token(request)
    from agent.registration import count_registrations
    return {"count": count_registrations()}


def _require_admin_token(request: Request):
    """Simple admin auth guard using ADMIN_SECRET env var."""
    import os
    secret = os.getenv("ADMIN_SECRET", "")
    if not secret:
        return  # if not set, allow freely (dev mode)
    token = request.headers.get("X-Admin-Token", "")
    if token != secret:
        raise HTTPException(status_code=401, detail="Unauthorized")


# ── Community report admin endpoints ──────────────────────────────────────

@app.get("/admin/reports")
async def admin_list_reports(
    request: Request,
    status: str = "new",
    limit: int = 50,
):
    """
    List community reports.
    status: new | monitored | under_review | verified | closed | archived
            OR an action value: escalate | flag_review | monitor | store_only
    When the value matches a known action it filters by action instead of status.
    """
    _require_admin_token(request)
    import sqlite3 as _sq
    db_path = Config.COMMUNITY_REPORTS_DB
    _action_values = {"escalate", "flag_review", "monitor", "store_only"}
    try:
        with _sq.connect(db_path) as conn:
            conn.row_factory = _sq.Row
            if status in _action_values:
                # Only show reports not yet reviewed — exclude verified/closed/archived
                rows = conn.execute("""
                    SELECT report_id, timestamp, language, report_domain,
                           hazard_type, category, location_text, description,
                           confidence_score, severity_score, action, status,
                           people_at_risk, ongoing
                    FROM community_reports
                    WHERE action = ?
                      AND status NOT IN ('verified', 'closed', 'archived')
                    ORDER BY severity_score DESC, timestamp DESC
                    LIMIT ?
                """, (status, limit)).fetchall()
            else:
                rows = conn.execute("""
                    SELECT report_id, timestamp, language, report_domain,
                           hazard_type, category, location_text, description,
                           confidence_score, severity_score, action, status,
                           people_at_risk, ongoing
                    FROM community_reports
                    WHERE status = ?
                    ORDER BY severity_score DESC, timestamp DESC
                    LIMIT ?
                """, (status, limit)).fetchall()
        return {"reports": [dict(r) for r in rows]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/admin/reports/{report_id}/verify")
async def admin_verify_report(report_id: str, request: Request):
    """
    Mark a report as verified (confirmed by official source or observation).
    Updates the reporter's Bayesian reliability score upward.
    """
    _require_admin_token(request)
    import sqlite3 as _sq
    db_path = Config.COMMUNITY_REPORTS_DB
    now = __import__("datetime").datetime.utcnow().isoformat()
    try:
        with _sq.connect(db_path) as conn:
            row = conn.execute(
                "SELECT user_hash, status FROM community_reports WHERE report_id = ?",
                (report_id,)
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Report not found")
            user_hash, old_status = row
            conn.execute(
                "UPDATE community_reports SET status = 'verified' WHERE report_id = ?",
                (report_id,)
            )
            conn.execute("""
                INSERT INTO report_status_log (report_id, old_status, new_status, changed_at, note)
                VALUES (?, ?, 'verified', ?, 'admin verified')
            """, (report_id, old_status, now))
            conn.commit()
        # Update Bayesian reliability
        orchestrator.reporter.update_user_reliability(
            user_hash, verified=True, note=f"admin verified {report_id}"
        )
        return {"status": "ok", "report_id": report_id, "new_status": "verified"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/admin/reports/{report_id}/reject")
async def admin_reject_report(report_id: str, request: Request):
    """
    Mark a report as closed/rejected (false report or unvalidated).
    Updates the reporter's Bayesian reliability score downward.
    """
    _require_admin_token(request)
    import sqlite3 as _sq
    db_path = Config.COMMUNITY_REPORTS_DB
    now = __import__("datetime").datetime.utcnow().isoformat()
    try:
        with _sq.connect(db_path) as conn:
            row = conn.execute(
                "SELECT user_hash, status FROM community_reports WHERE report_id = ?",
                (report_id,)
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Report not found")
            user_hash, old_status = row
            conn.execute(
                "UPDATE community_reports SET status = 'closed' WHERE report_id = ?",
                (report_id,)
            )
            conn.execute("""
                INSERT INTO report_status_log (report_id, old_status, new_status, changed_at, note)
                VALUES (?, ?, 'closed', ?, 'admin rejected')
            """, (report_id, old_status, now))
            conn.commit()
        # Update Bayesian reliability
        orchestrator.reporter.update_user_reliability(
            user_hash, verified=False, note=f"admin rejected {report_id}"
        )
        return {"status": "ok", "report_id": report_id, "new_status": "closed"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/admin/reports/stats")
async def admin_report_stats(request: Request):
    """Summary stats for the community reports dashboard."""
    _require_admin_token(request)
    import sqlite3 as _sq
    db_path = Config.COMMUNITY_REPORTS_DB
    try:
        with _sq.connect(db_path) as conn:
            total     = conn.execute("SELECT COUNT(*) FROM community_reports").fetchone()[0]
            new_ct    = conn.execute("SELECT COUNT(*) FROM community_reports WHERE status='new'").fetchone()[0]
            escalated = conn.execute("SELECT COUNT(*) FROM community_reports WHERE status='escalated'").fetchone()[0]
            review    = conn.execute("SELECT COUNT(*) FROM community_reports WHERE action='flag_review' AND status='new'").fetchone()[0]
            users     = conn.execute("SELECT COUNT(*) FROM user_reliability").fetchone()[0]
        return {
            "total": total,
            "new": new_ct,
            "escalated": escalated,
            "needs_review": review,
            "tracked_users": users,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
