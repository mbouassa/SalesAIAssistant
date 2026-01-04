"""
Memory Service using Firebase Firestore.
Persists conversation history per room.

NOTE: Firebase imports are lazy to avoid gRPC threading conflicts with Daily SDK.
"""

import os
import json
from datetime import datetime
from typing import Optional, Any, TYPE_CHECKING

# Type hints only - no runtime import
if TYPE_CHECKING:
    from google.cloud.firestore import Client

# Initialize Firebase once (lazy)
_firebase_initialized = False
_db: Optional["Client"] = None
_firestore_module: Any = None  # Store reference to firestore module


def _ensure_firebase_init() -> Optional["Client"]:
    """Initialize Firebase Admin SDK (lazy import to avoid gRPC conflicts)."""
    global _firebase_initialized, _db, _firestore_module
    
    if _firebase_initialized:
        return _db
    
    # Lazy import to avoid loading gRPC until we actually need Firebase
    try:
        import firebase_admin
        from firebase_admin import credentials, firestore
        _firestore_module = firestore  # Store reference for use elsewhere
    except ImportError as e:
        print(f"[Memory] ⚠️ Firebase not installed: {e}")
        _firebase_initialized = True
        return None
    
    cred = None
    
    # Option 1: Check for FIREBASE_CREDENTIALS env var (for deployment)
    firebase_creds_json = os.environ.get("FIREBASE_CREDENTIALS")
    if firebase_creds_json:
        try:
            creds_dict = json.loads(firebase_creds_json)
            cred = credentials.Certificate(creds_dict)
            print("[Memory] Using Firebase credentials from environment variable", flush=True)
        except json.JSONDecodeError as e:
            print(f"[Memory] ⚠️ Invalid FIREBASE_CREDENTIALS JSON: {e}")
    
    # Option 2: Fall back to credentials file (for local development)
    if cred is None:
        cred_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "firebase-credentials.json"
        )
        
        if os.path.exists(cred_path):
            cred = credentials.Certificate(cred_path)
            print("[Memory] Using Firebase credentials from file", flush=True)
        else:
            print(f"[Memory] ⚠️ No Firebase credentials found (no env var or file)")
            _firebase_initialized = True
            return None
    
    try:
        # Check if already initialized
        try:
            firebase_admin.get_app()
        except ValueError:
            firebase_admin.initialize_app(cred)
        
        _db = firestore.client()
        _firebase_initialized = True
        print("[Memory] ✓ Firebase initialized", flush=True)
        return _db
    except Exception as e:
        print(f"[Memory] ❌ Firebase init failed: {e}", flush=True)
        _firebase_initialized = True
        return None


def _get_firestore():
    """Get the firestore module (must be called after init)."""
    return _firestore_module


class MemoryService:
    """
    Manages conversation history in Firestore.
    
    Structure:
    conversations/{room_name}/messages/{message_id}
        - role: "user" | "assistant"
        - content: str
        - timestamp: datetime
    """
    
    MAX_MESSAGES = 20  # Limit context sent to LLM
    
    def __init__(self, room_name: str):
        self.room_name = room_name
        self.db = _ensure_firebase_init()
        self._messages_cache: list[dict] = []
    
    @property
    def _messages_ref(self):
        """Get reference to messages subcollection."""
        if not self.db:
            return None
        return self.db.collection("conversations").document(self.room_name).collection("messages")
    
    async def load_history(self) -> list[dict]:
        """Load recent conversation history from Firestore."""
        if not self._messages_ref:
            return []
        
        firestore = _get_firestore()
        if not firestore:
            return []
        
        try:
            # Get last N messages ordered by timestamp
            docs = (
                self._messages_ref
                .order_by("timestamp", direction=firestore.Query.DESCENDING)
                .limit(self.MAX_MESSAGES)
                .stream()
            )
            
            messages = []
            for doc in docs:
                data = doc.to_dict()
                messages.append({
                    "role": data.get("role", "user"),
                    "content": data.get("content", ""),
                })
            
            # Reverse to get chronological order
            messages.reverse()
            self._messages_cache = messages
            
            print(f"[Memory] Loaded {len(messages)} messages for room '{self.room_name}'", flush=True)
            return messages
            
        except Exception as e:
            print(f"[Memory] Error loading history: {e}", flush=True)
            return []
    
    async def add_message(self, role: str, content: str) -> None:
        """Add a message to conversation history."""
        if not self._messages_ref:
            # Fallback: just cache locally
            self._messages_cache.append({"role": role, "content": content})
            return
        
        firestore = _get_firestore()
        if not firestore:
            self._messages_cache.append({"role": role, "content": content})
            return
        
        try:
            # Add to Firestore
            self._messages_ref.add({
                "role": role,
                "content": content,
                "timestamp": firestore.SERVER_TIMESTAMP,
            })
            
            # Update local cache
            self._messages_cache.append({"role": role, "content": content})
            
            # Trim cache to max size
            if len(self._messages_cache) > self.MAX_MESSAGES:
                self._messages_cache = self._messages_cache[-self.MAX_MESSAGES:]
                
        except Exception as e:
            print(f"[Memory] Error saving message: {e}", flush=True)
            # Still cache locally
            self._messages_cache.append({"role": role, "content": content})
    
    def get_messages_for_llm(self) -> list[dict]:
        """Get messages formatted for OpenAI API."""
        return self._messages_cache.copy()
    
    async def clear_history(self) -> None:
        """Clear all messages for this room."""
        if not self._messages_ref:
            self._messages_cache = []
            return
        
        try:
            # Delete all documents in subcollection
            docs = self._messages_ref.stream()
            for doc in docs:
                doc.reference.delete()
            
            self._messages_cache = []
            print(f"[Memory] Cleared history for room '{self.room_name}'", flush=True)
            
        except Exception as e:
            print(f"[Memory] Error clearing history: {e}", flush=True)
    
    async def save_user_info(self, name: str, email: str) -> None:
        """
        Save user info to the conversation document.
        
        Structure:
        conversations/{room_name}/user_info
            - name: str
            - email: str
            - captured_at: datetime
        """
        if not self.db:
            print(f"[Memory] ⚠️ Firebase not available, cannot save user info", flush=True)
            return
        
        firestore = _get_firestore()
        if not firestore:
            return
        
        try:
            # Save to conversations/{room_name} document directly as a field
            # or as a subcollection - let's use subcollection for consistency
            user_info_ref = (
                self.db.collection("conversations")
                .document(self.room_name)
                .collection("user_info")
                .document("contact")
            )
            
            user_info_ref.set({
                "name": name,
                "email": email,
                "captured_at": firestore.SERVER_TIMESTAMP,
            })
            
            print(f"[Memory] ✓ Saved user info: {name} ({email})", flush=True)
            
        except Exception as e:
            print(f"[Memory] ❌ Error saving user info: {e}", flush=True)

