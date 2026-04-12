import redis
import json
from typing import Optional, Dict, Any
from agent.memory import ConversationMemory
from agent.rag import RAGSystem
from agent.reporter import CommunityReporter, detect_report_intent
from agent.disaster_agent import DisasterAgent
from agent.tools import WebSearchTool
from agent.i18n import get_menu_text, get_response_text, get_registration_prompt
from config import Config

class WhatsAppOrchestrator:
    def __init__(self):
        try:
            self.redis_client = redis.from_url(
                Config.REDIS_URL,
                socket_connect_timeout=3,
                socket_timeout=3,
            )
            self.redis_client.ping()  # validate connection at startup
            print(f"[orchestrator] Redis connected: {Config.REDIS_URL[:30]}...")
        except Exception as e:
            print(f"[orchestrator] Redis unavailable ({e}), using in-memory sessions only")
            self.redis_client = None
        self.memory = ConversationMemory(self.redis_client)
        self.rag_system = RAGSystem()
        self.reporter = CommunityReporter()
        self.web_search = WebSearchTool()
        self.agent = DisasterAgent(self.rag_system, self.reporter, self.web_search)

    # ── Registration commands ──────────────────────────────────────────────
    _REGISTER_COMMANDS = [
        "register", "sign up", "signup", "subscribe", "alert", "alerts",
        "early warning", "ලියාපදිංචි", "ලියාපදිංචි වන්න", "අනතුරු ඇඟවීම",
        "பதிவு", "பதிவு செய்", "எச்சரிக்கை",
    ]

    # ── STOP / unsubscribe ─────────────────────────────────────────────────
    _STOP_COMMANDS = ["stop", "unsubscribe", "නතර", "நிறுத்து"]

    # ── Community report explicit triggers ────────────────────────────────
    _REPORT_COMMANDS = [
        "report", "report hazard", "submit report", "i want to report",
        "report incident", "report an issue", "i need to report",
        # Sinhala
        "වාර්තා", "වාර්තා කරන්න", "දැනුම් දෙන්න", "අනතුරක් වාර්තා",
        # Tamil
        "அறிக்கை", "அறிக்கை செய்", "தெரிவிக்க", "புகார்",
    ]

    @staticmethod
    def _detect_script_language(text: str) -> Optional[str]:
        """Detect language purely from Unicode script ranges — fast and reliable."""
        for ch in text:
            cp = ord(ch)
            if 0x0D80 <= cp <= 0x0DFF:   # Sinhala block
                return "si"
            if 0x0B80 <= cp <= 0x0BFF:   # Tamil block
                return "ta"
        return None  # no non-ASCII script found → treat as English

    async def process_message(self, phone_number: str, message: str, message_id: str) -> Optional[str]:
        """Process incoming WhatsApp message and return response"""
        try:
            # Get user session data
            session = self.memory.get_session(phone_number)
            message_lower = message.strip().lower()

            # ── 1. Script-based language detection (highest priority) ──────
            # Detect Sinhala/Tamil from the actual Unicode characters in the message.
            # This overrides the stored session language so replies always match input.
            script_lang = self._detect_script_language(message)
            if script_lang:
                session["language"] = script_lang
                self.memory.update_session(phone_number, session)

            # ── 2. Language change intent detection ───────────────────────
            language_commands = [
                # English
                "change language", "language", "menu", "/language", "/lang",
                "switch language", "i want to change the language",
                "i want to change language", "want to change language",
                "change the language", "switch to", "language menu", "select language",
                # Sinhala
                "භාෂාව වෙනස් කරන්න", "භාෂාව", "ලැයිස්තුව",
                "භාෂාවක් තෝරන්න", "භාෂා මෙනුව",
                # Tamil
                "மொழியை மாற்று", "மொழி", "பட்டியல்", "மொழியை மாற்றுங்கள்",
                "மொழியைத் தேர்ந்தெடுக்கவும்", "மொழி மெனு",
            ]
            if any(cmd in message_lower for cmd in language_commands):
                # Reset language so next reply sets it fresh
                session["language"] = None
                self.memory.update_session(phone_number, session)
                return get_menu_text()

            # ── 3. Registration command ────────────────────────────────────
            if any(cmd in message_lower for cmd in self._REGISTER_COMMANDS):
                lang = session.get("language", "en")
                return get_registration_prompt(Config.REGISTRATION_FORM_URL, lang)

            # ── 4. STOP / unsubscribe command ─────────────────────────────
            if any(cmd in message_lower for cmd in self._STOP_COMMANDS):
                lang = session.get("language", "en")
                stop_msgs = {
                    "en": "✅ You have been unsubscribed from early warning alerts. Reply *register* anytime to re-subscribe.",
                    "si": "✅ ඔබ මුල් අනතුරු ඇඟවීම් දැනුම්දීම් වලින් ඉවත් කර ඇත. නැවත ලියාපදිංචි වීමට ඕනෑම වේලාවක *register* ලෙස පිළිතුරු දෙන්න.",
                    "ta": "✅ ஆரம்ப எச்சரிக்கை அறிவிப்புகளிலிருந்து நீங்கள் பதிவு நீக்கப்பட்டீர்கள். மீண்டும் பதிவு செய்ய எந்த நேரத்திலும் *register* என்று பதிலளிக்கவும்.",
                }
                try:
                    import sqlite3 as _sqlite3, os as _os
                    db_path = _os.getenv("REGISTRATIONS_DB", "./data/registrations.db")
                    if _os.path.exists(db_path):
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

            # ── 5. Language selection menu reply (1 / 2 / 3) ──────────────
            if message.strip() in ["1", "2", "3"]:
                language_map = {"1": "si", "2": "en", "3": "ta"}
                selected_language = language_map[message.strip()]
                session["language"] = selected_language
                self.memory.update_session(phone_number, session)
                return get_response_text("language_selected", selected_language)

            # ── 6. First-time users: show menu for greetings ──────────────
            if not session.get("language"):
                greetings = {"hi", "hello", "hey", "start", "help", "menu", "1", "2", "3"}
                if message_lower.strip() in greetings or len(message_lower.strip()) <= 3:
                    return get_menu_text()
                # For a real first question with no script detected, default to English
                session["language"] = "en"
                self.memory.update_session(phone_number, session)

            user_language = session["language"] or "en"

            # ── 7. Community report clarification bypass ──────────────────
            # If the user was asked a location clarification for a pending
            # report, route directly back to the reporter — no agent call
            # needed since this is a stateful continuation, not a new decision.
            if session.get("report_state") == "awaiting_clarification":
                self.memory.add_message(phone_number, "user", message)
                result = await self.reporter.process_report(
                    phone_number, message, user_language,
                    pending_report=session.get("pending_report"),
                )
                if result["needs_clarification"]:
                    session["pending_report"] = result["pending_report"]
                else:
                    session.pop("report_state", None)
                    session.pop("pending_report", None)
                self.memory.update_session(phone_number, session)
                self.memory.add_message(phone_number, "assistant", result["response"])
                return result["response"]

            # ── 8. Fetch conversation history ─────────────────────────────
            conversation_history = self.memory.get_conversation_history(
                phone_number, limit=10
            )

            # ── 9. Save user message ──────────────────────────────────────
            self.memory.add_message(phone_number, "user", message)

            # ── 10. Agent-based routing ───────────────────────────────────
            # The LLM agent decides which tool to call: query_knowledge_base,
            # search_web, submit_community_report, or get_community_observations.
            # Every tool-call decision is logged in agent_tool_calls for
            # research evaluation.
            response = await self.agent.ainvoke(
                message, user_language, phone_number, conversation_history
            )

            # If the agent reported a pending clarification, capture state
            # (the submit_community_report tool surfaces this in its response text;
            # we also check the reporter's last pending state for session tracking)
            if not response:
                response = get_response_text("no_answer", user_language)

            # ── 11. Save the assistant reply ──────────────────────────────
            self.memory.add_message(phone_number, "assistant", response)

            return response

        except Exception as e:
            print(f"Error in orchestrator: {e}")
            return get_response_text("error", session.get("language", "en"))
    
    def get_user_stats(self, phone_number: str) -> Dict[str, Any]:
        """Get user conversation statistics"""
        return self.memory.get_user_stats(phone_number)
