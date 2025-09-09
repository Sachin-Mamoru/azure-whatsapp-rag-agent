from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import PlainTextResponse
import json
import requests
from agent.orchestrator import WhatsAppOrchestrator
from config import Config

app = FastAPI(title="WhatsApp RAG Agent")

# Initialize the orchestrator
orchestrator = WhatsAppOrchestrator()

@app.get("/")
async def root():
    return {"message": "WhatsApp RAG Agent is running"}

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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
