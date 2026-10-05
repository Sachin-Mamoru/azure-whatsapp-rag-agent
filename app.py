from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
import json
import requests
from agent.orchestrator import WhatsAppOrchestrator
from agent.admin_routes import router as admin_router, configure as configure_admin
from agent.scheduler import start_scheduler, stop_scheduler
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
configure_admin(orchestrator.reporter)
app.include_router(admin_router)

def _mask(phone: str) -> str:
    """Keep logs free of full phone numbers."""
    return f"…{str(phone)[-3:]}" if phone else "?"


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
                        # Numbers may host multiple WhatsApp phone numbers on one WABA;
                        # always reply from the number that actually received the message.
                        metadata = value.get("metadata", {})
                        receiving_phone_number_id = metadata.get("phone_number_id") or Config.WHATSAPP_PHONE_NUMBER_ID
                        if receiving_phone_number_id != Config.WHATSAPP_PHONE_NUMBER_ID:
                            print(f"[webhook] incoming message via phone_number_id={receiving_phone_number_id} "
                                  f"display_number={metadata.get('display_phone_number')} "
                                  f"(configured default is {Config.WHATSAPP_PHONE_NUMBER_ID})")

                        # Delivery/read receipts arrive as "statuses", not "messages" —
                        # log failures so silent proactive-alert drops (e.g. recipient
                        # outside the 24h session window) are visible.
                        for status in value.get("statuses", []):
                            recipient = status.get("recipient_id")
                            status_type = status.get("status")
                            errors = status.get("errors") or []
                            if status_type == "failed" or errors:
                                for err in errors:
                                    print(f"[webhook] delivery FAILED to {_mask(recipient)}: "
                                          f"code={err.get('code')} title={err.get('title')} "
                                          f"detail={err.get('error_data', {}).get('details')}")
                            else:
                                print(f"[webhook] status update: {_mask(recipient)} -> {status_type}")

                        # Process incoming messages
                        for message in value.get("messages", []):
                            phone_number = message.get("from")
                            message_id = message.get("id")
                            msg_type = message.get("type")

                            image_bytes, image_mime = None, None
                            if msg_type == "image":
                                image_info = message.get("image", {})
                                # A photo may arrive with or without a caption
                                message_body = image_info.get("caption") or "[image attached]"
                                media = download_whatsapp_media(image_info.get("id"))
                                if media:
                                    image_bytes, image_mime = media
                            else:
                                message_body = message.get("text", {}).get("body", "")

                            if phone_number and (message_body or image_bytes):
                                # Process message through orchestrator
                                response = await orchestrator.process_message(
                                    phone_number, message_body, message_id,
                                    image_bytes=image_bytes, image_mime=image_mime,
                                )
                                
                                if response:
                                    await send_whatsapp_message(phone_number, response, phone_number_id=receiving_phone_number_id)
        
        return {"status": "ok"}
    
    except Exception as e:
        print(f"Error processing webhook: {e}")
        return {"status": "error"}

def download_whatsapp_media(media_id: str):
    """
    Download a WhatsApp media attachment (2-step Graph API flow):
    1. Resolve the media_id to a short-lived CDN URL + mime type.
    2. Fetch the bytes from that URL using the same bearer token.
    Returns (bytes, mime_type) or None on failure.
    """
    if not media_id:
        return None
    try:
        meta_resp = requests.get(
            f"https://graph.facebook.com/v22.0/{media_id}",
            params={"access_token": Config.WHATSAPP_TOKEN},
            timeout=10,
        )
        meta_resp.raise_for_status()
        meta = meta_resp.json()
        media_url = meta.get("url")
        mime_type = meta.get("mime_type", "image/jpeg")
        if not media_url:
            return None

        file_resp = requests.get(
            media_url,
            headers={"Authorization": f"Bearer {Config.WHATSAPP_TOKEN}"},
            timeout=20,
        )
        file_resp.raise_for_status()
        return file_resp.content, mime_type
    except Exception as e:
        print(f"Error downloading WhatsApp media {media_id}: {e}")
        return None

async def send_whatsapp_message(phone_number: str, message: str, phone_number_id: str = None):
    """Send message via WhatsApp API, from the given phone_number_id (defaults to Config)"""
    sender_id = phone_number_id or Config.WHATSAPP_PHONE_NUMBER_ID
    url = f"https://graph.facebook.com/v22.0/{sender_id}/messages"
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
        body = getattr(e, "response", None)
        detail = body.text if body is not None else ""
        print(f"Error sending WhatsApp message via {sender_id}: {e} {detail}")
        return None


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
