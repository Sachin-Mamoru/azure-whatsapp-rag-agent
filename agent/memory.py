import json
import time
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta

class ConversationMemory:
    # In-memory fallback — survives Redis outages within the same process
    _local_sessions: Dict[str, Dict] = {}
    _local_conversations: Dict[str, List] = {}

    def __init__(self, redis_client):
        self.redis = redis_client
        self.session_prefix = "session:"
        self.conversation_prefix = "conv:"
        self.session_timeout = 3600 * 24  # 24 hours

    def _redis_ok(self) -> bool:
        try:
            self.redis.ping()
            return True
        except Exception as e:
            print(f"[memory] Redis unavailable: {e}")
            return False

    def get_session(self, phone_number: str) -> Dict[str, Any]:
        """Get or create user session"""
        session_key = f"{self.session_prefix}{phone_number}"

        # Try Redis first
        try:
            session_data = self.redis.get(session_key)
            if session_data:
                session = json.loads(session_data)
                # Sync back to local cache
                ConversationMemory._local_sessions[phone_number] = session
                return session
        except Exception as e:
            print(f"[memory] Redis get_session error: {e}")

        # Fallback: local in-memory cache
        if phone_number in ConversationMemory._local_sessions:
            return ConversationMemory._local_sessions[phone_number]

        # Brand-new session
        new_session = {
            "phone_number": phone_number,
            "language": None,
            "created_at": datetime.now().isoformat(),
            "last_activity": datetime.now().isoformat(),
            "message_count": 0
        }
        self.update_session(phone_number, new_session)
        return new_session

    def update_session(self, phone_number: str, session_data: Dict[str, Any]):
        """Update user session"""
        session_key = f"{self.session_prefix}{phone_number}"
        session_data["last_activity"] = datetime.now().isoformat()

        # Always write to local cache first (guaranteed)
        ConversationMemory._local_sessions[phone_number] = session_data

        # Also persist to Redis (best-effort)
        try:
            self.redis.setex(
                session_key,
                self.session_timeout,
                json.dumps(session_data)
            )
        except Exception as e:
            print(f"[memory] Redis update_session error (using local cache): {e}")
    
    def add_message(self, phone_number: str, role: str, content: str):
        """Add message to conversation history"""
        conv_key = f"{self.conversation_prefix}{phone_number}"

        message = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat()
        }

        # Always update local cache
        local_conv = ConversationMemory._local_conversations.setdefault(phone_number, [])
        local_conv.append(message)
        if len(local_conv) > 20:
            ConversationMemory._local_conversations[phone_number] = local_conv[-20:]

        # Persist to Redis (best-effort)
        try:
            existing = self.redis.get(conv_key)
            conversation = json.loads(existing) if existing else []
            conversation.append(message)
            if len(conversation) > 20:
                conversation = conversation[-20:]
            self.redis.setex(conv_key, self.session_timeout, json.dumps(conversation))
        except Exception as e:
            print(f"[memory] Redis add_message error (using local cache): {e}")

        # Update message count in session
        try:
            session = self.get_session(phone_number)
            session["message_count"] = session.get("message_count", 0) + 1
            self.update_session(phone_number, session)
        except Exception as e:
            print(f"[memory] update message_count error: {e}")
    
    def get_conversation_history(self, phone_number: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Get conversation history"""
        conv_key = f"{self.conversation_prefix}{phone_number}"

        try:
            conversation_data = self.redis.get(conv_key)
            if conversation_data:
                conversation = json.loads(conversation_data)
                ConversationMemory._local_conversations[phone_number] = conversation
                return conversation[-limit:] if limit else conversation
        except Exception as e:
            print(f"[memory] Redis get_conversation error: {e}")

        # Fallback to local cache
        local_conv = ConversationMemory._local_conversations.get(phone_number, [])
        return local_conv[-limit:] if limit else local_conv
    
    def clear_conversation(self, phone_number: str):
        """Clear conversation history"""
        conv_key = f"{self.conversation_prefix}{phone_number}"
        
        try:
            self.redis.delete(conv_key)
        except Exception as e:
            print(f"Error clearing conversation: {e}")
    
    def get_user_stats(self, phone_number: str) -> Dict[str, Any]:
        """Get user statistics"""
        try:
            session = self.get_session(phone_number)
            conversation = self.get_conversation_history(phone_number)
            
            return {
                "total_messages": len(conversation),
                "user_messages": len([m for m in conversation if m["role"] == "user"]),
                "assistant_messages": len([m for m in conversation if m["role"] == "assistant"]),
                "language": session.get("language"),
                "created_at": session.get("created_at"),
                "last_activity": session.get("last_activity"),
                "session_message_count": session.get("message_count", 0)
            }
        except Exception as e:
            print(f"Error getting user stats: {e}")
            return {}
    
    def cleanup_old_sessions(self, days_old: int = 7):
        """Clean up old sessions (maintenance function)"""
        try:
            # This is a simplified version - in production you'd want to scan keys more efficiently
            cutoff_date = datetime.now() - timedelta(days=days_old)
            
            # Get all session keys (note: this is not efficient for large datasets)
            session_keys = self.redis.keys(f"{self.session_prefix}*")
            
            for key in session_keys:
                try:
                    session_data = self.redis.get(key)
                    if session_data:
                        session = json.loads(session_data)
                        last_activity = datetime.fromisoformat(session.get("last_activity", ""))
                        
                        if last_activity < cutoff_date:
                            phone_number = session.get("phone_number", "")
                            # Delete session and conversation
                            self.redis.delete(key)
                            if phone_number:
                                self.redis.delete(f"{self.conversation_prefix}{phone_number}")
                            print(f"Cleaned up old session: {phone_number}")
                            
                except Exception as e:
                    print(f"Error processing session key {key}: {e}")
                    continue
                    
        except Exception as e:
            print(f"Error in cleanup: {e}")
