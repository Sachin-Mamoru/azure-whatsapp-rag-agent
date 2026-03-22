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

    start_scheduler()
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
