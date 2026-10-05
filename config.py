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
    WHATSAPP_BASE_URL = f"https://graph.facebook.com/v22.0/{WHATSAPP_PHONE_NUMBER_ID}"

    # ── Registration & Alert features ──────────────────────────────────────
    # SQLite path for subscriber registrations
    REGISTRATIONS_DB = os.getenv("REGISTRATIONS_DB", "./data/registrations.db")

    # SQLite path for community hazard reports (separate from authoritative RAG)
    COMMUNITY_REPORTS_DB = os.getenv("COMMUNITY_REPORTS_DB", "./data/community_reports.db")

    # Local disk folder where photos attached to community reports are saved
    REPORT_IMAGES_DIR = os.getenv("REPORT_IMAGES_DIR", "./data/report_images")

    # ── Community reporting policy / retention ─────────────────────────────
    # Decision policy that drives the stored action; the other policy is still
    # computed and persisted in the report's scoring provenance (shadow mode).
    ACTIVE_DECISION_POLICY = os.getenv("ACTIVE_DECISION_POLICY", "baseline-v1")
    # Keyed pseudonyms for contributors. Unset = legacy unkeyed SHA-256 prefix.
    REPORTER_ID_KEY = os.getenv("REPORTER_ID_KEY", "")
    VISION_TIMEOUT_S = float(os.getenv("VISION_TIMEOUT_S", "45"))
    EXTRACTION_TIMEOUT_S = float(os.getenv("EXTRACTION_TIMEOUT_S", "30"))
    MAX_IMAGE_BYTES = int(os.getenv("MAX_IMAGE_BYTES", str(10 * 1024 * 1024)))
    PENDING_REPORT_TTL_MINUTES = int(os.getenv("PENDING_REPORT_TTL_MINUTES", "60"))
    RAINFALL_CACHE_TTL_MINUTES = int(os.getenv("RAINFALL_CACHE_TTL_MINUTES", "180"))
    IMAGE_RETENTION_DAYS = int(os.getenv("IMAGE_RETENTION_DAYS", "30"))

    # ── Admin access ───────────────────────────────────────────────────────
    # Scripts may send ADMIN_SECRET in X-Admin-Token; people sign in with a WhatsApp login link.
    ADMIN_SECRET = os.getenv("ADMIN_SECRET", "")
    ADMIN_PHONE_NUMBERS = os.getenv("ADMIN_PHONE_NUMBERS", "")  # comma-separated, digits with country code
    ADMIN_SESSION_KEY = os.getenv("ADMIN_SESSION_KEY", "")
    ADMIN_PUBLIC_URL = os.getenv(
        "ADMIN_PUBLIC_URL", "https://whatsapp-agent.wittysand-7a29c211.eastus.azurecontainerapps.io")
    # Held server-side so no browser ever needs a GitHub token to edit the warnings file.
    WARNINGS_GITHUB_TOKEN = os.getenv("WARNINGS_GITHUB_TOKEN", "")
    WARNINGS_REPO = os.getenv("WARNINGS_REPO", "Sachin-Mamoru/azure-whatsapp-rag-agent")
    WARNINGS_PATH = os.getenv("WARNINGS_PATH", "early-warning-site/data.json")
    WARNINGS_BRANCH = os.getenv("WARNINGS_BRANCH", "main")

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
