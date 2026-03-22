import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN")
    WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
    WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
    
    MODEL_PROVIDER = os.getenv("MODEL_PROVIDER", "openai")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    MODEL_NAME = os.getenv("MODEL_NAME", "gpt-4o-mini")
    EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-large")
    
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    RAG_VECTOR_DIR = os.getenv("RAG_VECTOR_DIR", "./vectorstore")
    TRAINING_ROOT = os.getenv("TRAINING_ROOT", "./training-files/general-hazard-awareness")
    
    # WhatsApp API URLs
    WHATSAPP_BASE_URL = f"https://graph.facebook.com/v18.0/{WHATSAPP_PHONE_NUMBER_ID}"

    # ── Registration & Alert features ──────────────────────────────────────
    # SQLite path for subscriber registrations
    REGISTRATIONS_DB = os.getenv("REGISTRATIONS_DB", "./data/registrations.db")

    # Google Sheets (linked to Google Form responses)
    GOOGLE_SHEETS_CREDENTIALS_FILE = os.getenv("GOOGLE_SHEETS_CREDENTIALS_FILE", "./credentials.json")
    GOOGLE_SHEETS_SPREADSHEET_ID   = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID", "")

    # GitHub Pages URL of the early warning data.json
    # Example: https://your-username.github.io/your-repo/data.json
    EARLY_WARNING_DATA_URL = os.getenv("EARLY_WARNING_DATA_URL", "")

    # Registration Google Form URL shown to new users
    REGISTRATION_FORM_URL = os.getenv(
        "REGISTRATION_FORM_URL",
        "https://forms.gle/YOUR_FORM_ID_HERE"
    )

    # Scheduler intervals (minutes)
    SHEETS_SYNC_INTERVAL_MINUTES = int(os.getenv("SHEETS_SYNC_INTERVAL_MINUTES", "30"))
    ALERT_CHECK_INTERVAL_MINUTES = int(os.getenv("ALERT_CHECK_INTERVAL_MINUTES", "60"))
