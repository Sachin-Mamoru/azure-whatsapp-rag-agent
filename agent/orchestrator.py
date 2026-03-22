import redis
import json
import asyncio
from typing import Optional, Dict, Any
from agent.memory import ConversationMemory
from agent.rag import RAGSystem
from agent.tools import WebSearchTool
from agent.i18n import LanguageDetector, get_menu_text, get_response_text, get_registration_prompt
from config import Config

class WhatsAppOrchestrator:
    def __init__(self):
        self.redis_client = redis.from_url(Config.REDIS_URL)
        self.memory = ConversationMemory(self.redis_client)
        self.rag_system = RAGSystem()
        self.web_search = WebSearchTool()
        self.lang_detector = LanguageDetector()

    # ── Registration commands ──────────────────────────────────────────────
    _REGISTER_COMMANDS = [
        "register", "sign up", "signup", "subscribe", "alert", "alerts",
        "early warning", "ලියාපදිංචි", "ලියාපදිංචි වන්න", "අනතුරු ඇඟවීම",
        "பதிவு", "பதிவு செய்", "எச்சரிக்கை",
    ]

    # ── STOP / unsubscribe ─────────────────────────────────────────────────
    _STOP_COMMANDS = ["stop", "unsubscribe", "නතර", "நிறுத்து"]

    async def process_message(self, phone_number: str, message: str, message_id: str) -> Optional[str]:
        """Process incoming WhatsApp message and return response"""
        try:
            # Get user session data
            session = self.memory.get_session(phone_number)
            message_lower = message.strip().lower()
            
            # Check for language change commands first (more comprehensive list)
            language_commands = [
                # English commands
                "change language", "language", "menu", "/language", "/lang", "switch language",
                "i want to change the language", "i want to change language", "want to change language",
                "change the language", "switch to", "language menu", "select language",
                # Sinhala commands  
                "භාෂාව වෙනස් කරන්න", "භාෂාව", "ලැයිස්තුව", "භාෂාව වෙනස් කරන්න",
                "භාෂාවක් තෝරන්න", "භාෂා මෙනුව",
                # Tamil commands
                "மொழியை மாற்று", "மொழி", "பட்டியல்", "மொழியை மாற்றுங்கள்",
                "மொழியைத் தேர்ந்தெடுக்கவும்", "மொழி மெனு"
            ]
            
            # Check if user wants to change language (more flexible matching)
            if any(cmd in message_lower for cmd in language_commands):
                return get_menu_text()

            # ── Registration command ────────────────────────────────────────
            if any(cmd in message_lower for cmd in self._REGISTER_COMMANDS):
                lang = session.get("language", "en")
                return get_registration_prompt(Config.REGISTRATION_FORM_URL, lang)

            # ── STOP / unsubscribe command ──────────────────────────────────
            if any(cmd in message_lower for cmd in self._STOP_COMMANDS):
                lang = session.get("language", "en")
                stop_msgs = {
                    "en": "✅ You have been unsubscribed from early warning alerts. Reply *register* anytime to re-subscribe.",
                    "si": "✅ ඔබ මුල් අනතුරු ඇඟවීම් දැනුම්දීම් වලින් ඉවත් කර ඇත. නැවත ලියාපදිංචි වීමට ඕනෑම වේලාවක *register* ලෙස පිළිතුරු දෙන්න.",
                    "ta": "✅ ஆரம்ப எச்சரிக்கை அறிவிப்புகளிலிருந்து நீங்கள் பதிவு நீக்கப்பட்டீர்கள். மீண்டும் பதிவு செய்ய எந்த நேரத்திலும் *register* என்று பதிலளிக்கவும்.",
                }
                # Mark as unsubscribed in the registration DB (if they exist)
                try:
                    from agent.registration import upsert_registration, get_all_subscribers
                    import sqlite3, os
                    db_path = os.getenv("REGISTRATIONS_DB", "./data/registrations.db")
                    if os.path.exists(db_path):
                        import sqlite3 as _sqlite3
                        conn = _sqlite3.connect(db_path)
                        conn.execute(
                            "UPDATE registrations SET consent = 0 WHERE phone_number = ?",
                            (phone_number,)
                        )
                        conn.commit()
                        conn.close()
                except Exception as e:
                    print(f"[orchestrator] STOP update failed: {e}")
                return stop_msgs.get(lang, stop_msgs["en"])


            if message.strip() in ["1", "2", "3"]:
                language_map = {"1": "si", "2": "en", "3": "ta"}
                selected_language = language_map.get(message.strip())
                
                if selected_language:
                    session["language"] = selected_language
                    self.memory.update_session(phone_number, session)
                    return get_response_text("language_selected", selected_language)
            
            # If no language set, show menu only for greetings/short messages
            # For real questions, default silently to English and answer directly
            if not session.get("language"):
                session["language"] = "en"
                self.memory.update_session(phone_number, session)
                greetings = {"hi", "hello", "hey", "start", "help", "menu", "1", "2", "3"}
                if message_lower.strip() in greetings or len(message_lower.strip()) <= 3:
                    return get_menu_text()
            
            user_language = session["language"]
            
            # Detect if message is in a different language and update if needed
            detected_lang = self.lang_detector.detect_language(message)
            if detected_lang in ["si", "en", "ta"] and detected_lang != user_language:
                # Only switch if we're confident about the detection
                if len(message) > 10:  # Only for longer messages to avoid false positives
                    session["language"] = detected_lang
                    user_language = detected_lang
                    self.memory.update_session(phone_number, session)
                    # Acknowledge the language change
                    await asyncio.sleep(0.1)  # Small delay to ensure session is updated
            
            # Add message to conversation history
            self.memory.add_message(phone_number, "user", message)
            
            # Try RAG first
            rag_response = await self.rag_system.query(message, user_language)
            
            if rag_response and rag_response.get("confidence", 0) > 0.7:
                response = rag_response["answer"]
            else:
                # Fall back to web search
                web_response = await self.web_search.search(message, user_language)
                if web_response:
                    response = web_response
                else:
                    # Check if it's likely a question that needs web search
                    web_keywords = ["weather", "news", "current", "today", "time", "price", "stock"]
                    if any(keyword in message.lower() for keyword in web_keywords):
                        response = get_response_text("web_search_limited", user_language)
                    else:
                        response = get_response_text("no_answer", user_language)
            
            # Add response to conversation history
            self.memory.add_message(phone_number, "assistant", response)
            
            return response
            
        except Exception as e:
            print(f"Error in orchestrator: {e}")
            return get_response_text("error", session.get("language", "en"))
    
    def get_user_stats(self, phone_number: str) -> Dict[str, Any]:
        """Get user conversation statistics"""
        return self.memory.get_user_stats(phone_number)
