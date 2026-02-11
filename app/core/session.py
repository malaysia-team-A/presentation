from typing import Dict, Any, Deque
from collections import deque
from datetime import datetime

# In-memory session store
high_security_sessions: Dict[str, datetime] = {}
conversation_history_store: Dict[str, Deque[Dict[str, str]]] = {}

CONVERSATION_HISTORY_LIMIT = 12

def get_conversation_history(session_key: str):
    return list(conversation_history_store.get(session_key, []))

def append_conversation_message(session_key: str, role: str, content: str):
    if not session_key or not content:
        return
    if session_key not in conversation_history_store:
        conversation_history_store[session_key] = deque(maxlen=CONVERSATION_HISTORY_LIMIT)
    conversation_history_store[session_key].append({"role": role, "content": content})
