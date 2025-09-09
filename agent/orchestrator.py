import redis
import json
from typing import Optional, Dict, Any
from agent.memory import ConversationMemory
from agent.rag import RAGSystem
from agent.tools import WebSearchTool
from agent.i18n import LanguageDetector, get_menu_text, get_response_text
from config import Config

class WhatsAppOrchestrator:
    def __init__(self):
        self.redis_client = redis.from_url(Config.REDIS_URL)
        self.memory = ConversationMemory(self.redis_client)
        self.rag_system = RAGSystem()
        self.web_search = WebSearchTool()
        self.lang_detector = LanguageDetector()
        
    async def process_message(self, phone_number: str, message: str, message_id: str) -> Optional[str]:
        """Process incoming WhatsApp message and return response"""
        try:
            # Get user session data
            session = self.memory.get_session(phone_number)
            
            # Check if user is selecting language
            if message.strip() in ["1", "2", "3"] and not session.get("language"):
                language_map = {"1": "si", "2": "en", "3": "ta"}
                selected_language = language_map.get(message.strip())
                
                if selected_language:
                    session["language"] = selected_language
                    self.memory.update_session(phone_number, session)
                    return get_response_text("language_selected", selected_language)
            
            # If no language set, show menu
            if not session.get("language"):
                return get_menu_text()
            
            user_language = session["language"]
            
            # Detect if message is in a different language and update if needed
            detected_lang = self.lang_detector.detect_language(message)
            if detected_lang in ["si", "en", "ta"] and detected_lang != user_language:
                session["language"] = detected_lang
                user_language = detected_lang
                self.memory.update_session(phone_number, session)
            
            # Add message to conversation history
            self.memory.add_message(phone_number, "user", message)
            
            # Try RAG first
            rag_response = await self.rag_system.query(message, user_language)
            
            if rag_response and rag_response.get("confidence", 0) > 0.7:
                response = rag_response["answer"]
            else:
                # Fall back to web search
                web_response = await self.web_search.search(message, user_language)
                response = web_response if web_response else get_response_text("no_answer", user_language)
            
            # Add response to conversation history
            self.memory.add_message(phone_number, "assistant", response)
            
            return response
            
        except Exception as e:
            print(f"Error in orchestrator: {e}")
            return get_response_text("error", session.get("language", "en"))
    
    def get_user_stats(self, phone_number: str) -> Dict[str, Any]:
        """Get user conversation statistics"""
        return self.memory.get_user_stats(phone_number)
