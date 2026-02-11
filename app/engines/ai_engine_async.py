import os
import re
import json
import asyncio
import random
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from google import genai
from .language_engine import multilingual
from .db_engine_async import db_engine_async

# ============================================================
# 🚀 ASYNC RESILIENCE CONFIGURATION
# ============================================================

def _env_int(name: str, default: int) -> int:
    try: return int(os.getenv(name, str(default)))
    except: return default

def _env_float(name: str, default: float) -> float:
    try: return float(os.getenv(name, str(default)))
    except: return default

MAX_RETRIES = _env_int("AI_MAX_RETRIES", 2)
BASE_DELAY = _env_float("AI_BASE_DELAY", 0.5)
MAX_DELAY = _env_float("AI_MAX_DELAY", 2.0)
JITTER_FACTOR = _env_float("AI_JITTER_FACTOR", 0.2)

CIRCUIT_FAILURE_THRESHOLD = _env_int("AI_CIRCUIT_FAILURE_THRESHOLD", 8)
CIRCUIT_RECOVERY_TIMEOUT = _env_int("AI_CIRCUIT_RECOVERY_TIMEOUT", 8)
CIRCUIT_HALF_OPEN_MAX_CALLS = _env_int("AI_CIRCUIT_HALF_OPEN_MAX_CALLS", 3)

RATE_LIMIT_RPM = _env_int("AI_RATE_LIMIT_RPM", 120)
RATE_LIMIT_TOKENS = _env_int("AI_RATE_LIMIT_TOKENS", max(30, RATE_LIMIT_RPM))
RATE_LIMIT_REFILL_RATE = max(_env_float("AI_RATE_LIMIT_REFILL_RATE", RATE_LIMIT_RPM / 60.0), 0.1)
FAST_PATH_ENABLED = str(os.getenv("AI_FAST_PATH_ENABLED", "false")).strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

class AsyncCircuitBreaker:
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"
    
    def __init__(self):
        self.state = self.CLOSED
        self.failure_count = 0
        self.last_failure_time = None
        self.half_open_calls = 0
        self._lock = asyncio.Lock()
    
    async def can_execute(self) -> bool:
        async with self._lock:
            if self.state == self.CLOSED:
                return True
            elif self.state == self.OPEN:
                if self.last_failure_time and \
                   datetime.now() - self.last_failure_time > timedelta(seconds=CIRCUIT_RECOVERY_TIMEOUT):
                    self.state = self.HALF_OPEN
                    self.half_open_calls = 0
                    return True
                return False
            else: # HALF_OPEN
                if self.half_open_calls < CIRCUIT_HALF_OPEN_MAX_CALLS:
                    self.half_open_calls += 1
                    return True
                return False

    async def record_success(self):
        async with self._lock:
            self.state = self.CLOSED
            self.failure_count = 0

    async def record_failure(self):
        async with self._lock:
            self.failure_count += 1
            self.last_failure_time = datetime.now()
            if self.state == self.HALF_OPEN:
                self.state = self.OPEN
            elif self.failure_count >= CIRCUIT_FAILURE_THRESHOLD:
                self.state = self.OPEN

    async def get_status(self):
        async with self._lock:
            return {
                "state": self.state,
                "failure_count": self.failure_count,
                "last_failure": self.last_failure_time.isoformat() if self.last_failure_time else None
            }

class AsyncTokenBucketRateLimiter:
    def __init__(self):
        self.capacity = RATE_LIMIT_TOKENS
        self.tokens = RATE_LIMIT_TOKENS
        self.refill_rate = RATE_LIMIT_REFILL_RATE
        self.last_refill = time.time()
        self._lock = asyncio.Lock()
    
    async def acquire(self, timeout=10.0) -> bool:
        start_time = time.time()
        while time.time() - start_time < timeout:
            async with self._lock:
                now = time.time()
                elapsed = now - self.last_refill
                self.tokens = min(self.capacity, self.tokens + (elapsed * self.refill_rate))
                self.last_refill = now
                
                if self.tokens >= 1:
                    self.tokens -= 1
                    return True
            await asyncio.sleep(0.1)
        return False

_circuit_breaker = AsyncCircuitBreaker()
_rate_limiter = AsyncTokenBucketRateLimiter()

class AsyncAIEngine:
    def __init__(self, model_name=None):
        self.raw_model_name = model_name or os.getenv("GEMINI_MODEL", "gemma-3-27b-it")
        # Prefer GEMINI_API_KEY, keep GOOGLE_API_KEY as legacy fallback.
        self.api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        self.client = None
        
        if self.api_key:
            try:
                # Initialize Async Client
                self.client = genai.Client(api_key=self.api_key, http_options={'api_version': 'v1beta'})
                self.model_name = self.raw_model_name.replace("models/", "")
                print(f"[AsyncAI] Initialized with model: {self.model_name}")
            except Exception as e:
                print(f"AsyncGemini Init Failed: {e}")
        else:
            print("[AsyncAI] Missing API key. Set GEMINI_API_KEY (or legacy GOOGLE_API_KEY).")
        
    def _topic_hint(self, user_message: str) -> str:
        q = (user_message or "").lower()
        if "scholarship" in q: return "scholarship details"
        return "that specific information"

    def _context_fallback_response(self, user_message: str, data_context: str) -> str:
        if not data_context or "[NO_RELEVANT_DATA_FOUND]" in data_context:
            return f"I cannot find {self._topic_hint(user_message)} in our database."
        snippet = data_context.split("\n\n")[0]
        snippet = re.sub(r"\[conf:[^\]]+\]", "", snippet)
        snippet = snippet.replace("[Document]", "").strip()
        return snippet if snippet else f"I cannot find {self._topic_hint(user_message)}."

    def _should_use_fast_path(self, query: str) -> dict:
        q = query.lower().strip()
        if q in ["hi", "hello", "hey"]:
            return {"text": "Hello! How can I help you?", "needs_context": False}
        return None

    def _sanitize_search_term(self, value) -> str | None:
        if value is None:
            return None
        token = str(value).strip()
        if not token:
            return None
        if len(token) > 64:
            token = token[:64]
        return token

    def _extract_turn_text(self, raw_content: Any) -> str:
        text = str(raw_content or "").strip()
        if not text:
            return ""
        if text.startswith("{") and text.endswith("}"):
            try:
                payload = json.loads(text)
                if isinstance(payload, dict):
                    candidate = payload.get("text")
                    if isinstance(candidate, str) and candidate.strip():
                        text = candidate.strip()
            except Exception:
                pass
        text = re.sub(r"\s+", " ", text).strip()
        return text[:280]

    def _format_conversation_text(
        self,
        conversation_history: Optional[List[Dict[str, Any]]],
        user_message: str,
        limit: int = 6,
    ) -> str:
        if not isinstance(conversation_history, list) or not conversation_history:
            return ""

        history_items = [item for item in conversation_history if isinstance(item, dict)]
        if not history_items:
            return ""

        # chat.py appends current user turn before inference; avoid duplicating it in prompt.
        if str(history_items[-1].get("role") or "").strip().lower() == "user":
            tail = self._extract_turn_text(history_items[-1].get("content"))
            if tail and tail == str(user_message or "").strip():
                history_items = history_items[:-1]

        if not history_items:
            return ""

        # If conversation is long, summarize older turns
        total_items = len(history_items)
        if total_items > limit:
            older_items = history_items[:-limit]
            recent_items = history_items[-limit:]

            # Create summary of older turns
            topics = set()
            for item in older_items:
                content = self._extract_turn_text(item.get("content"))
                if content:
                    # Extract key topics from content
                    for keyword in ["hostel", "programme", "fee", "staff", "facility", "schedule", "gpa", "grade"]:
                        if keyword in content.lower():
                            topics.add(keyword)

            summary_line = ""
            if topics:
                summary_line = f"[Earlier discussion about: {', '.join(sorted(topics))}]\n"

            lines: List[str] = []
            if summary_line:
                lines.append(summary_line)

            for item in recent_items:
                role = str(item.get("role") or "").strip().lower()
                content = self._extract_turn_text(item.get("content"))
                if not content:
                    continue
                speaker = "User" if role == "user" else "Assistant"
                lines.append(f"{speaker}: {content}")
            return "\n".join(lines)

        lines: List[str] = []
        for item in history_items[-max(1, int(limit)):]:
            role = str(item.get("role") or "").strip().lower()
            content = self._extract_turn_text(item.get("content"))
            if not content:
                continue
            speaker = "User" if role == "user" else "Assistant"
            lines.append(f"{speaker}: {content}")
        return "\n".join(lines)

    def _extract_json_dict(self, raw_text: str) -> Optional[Dict[str, Any]]:
        text = str(raw_text or "").strip()
        if not text:
            return None
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group(0))
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                pass

        decoder = json.JSONDecoder()
        for start in [i for i, ch in enumerate(text) if ch == "{"][:6]:
            try:
                parsed, _ = decoder.raw_decode(text[start:])
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                continue
        return None

    def _canonical_intent(self, value: Any) -> str:
        raw = str(value or "").strip().lower().replace("-", "_")
        mapping = {
            "personal": "personal_profile",
            "personal_info": "personal_profile",
            "profile": "personal_profile",
            "my_profile": "personal_profile",
            "my_info": "personal_profile",
            "grades": "personal_grade",
            "grade": "personal_grade",
            "gpa": "personal_grade",
            "cgpa": "personal_grade",
            "ucsi_general": "ucsi_programme",
            "programme": "ucsi_programme",
            "program": "ucsi_programme",
            "program_info": "ucsi_programme",
            "hostel": "ucsi_hostel",
            "staff": "ucsi_staff",
            "facility": "ucsi_facility",
            "facilities": "ucsi_facility",
            "schedule": "ucsi_schedule",
            "general": "general_world",
            "general_knowledge": "general_world",
            "world_knowledge": "general_world",
            "person": "general_person",
            "person_query": "general_person",
            "smalltalk": "capability_smalltalk",
            "capability": "capability_smalltalk",
            "chitchat": "capability_smalltalk",
        }
        if raw in mapping:
            return mapping[raw]
        allowed = {
            "personal_profile",
            "personal_grade",
            "ucsi_programme",
            "ucsi_hostel",
            "ucsi_staff",
            "ucsi_facility",
            "ucsi_schedule",
            "general_person",
            "general_world",
            "capability_smalltalk",
            "unknown",
        }
        return raw if raw in allowed else "unknown"

    def _sanitize_entity(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        text = re.sub(r"\s+", " ", str(value).strip())
        text = text.strip(" \t\r\n?!.,\"'`")
        if not text:
            return None
        if len(text) > 80:
            text = text[:80].strip()
        return text or None

    async def plan_intent(
        self,
        user_message: str,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
        language: str = "en",
        search_term: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        if not self.client:
            return None

        question = str(user_message or "").strip()
        if not question:
            return None

        conversation_text = self._format_conversation_text(
            conversation_history=conversation_history,
            user_message=question,
            limit=6,
        )
        lang_instruct = multilingual.get_ai_language_instruction(language)
        hint = self._sanitize_search_term(search_term)

        prompt = f"""You are an intent planner for UCSI Buddy.
Analyze the current user request using conversation context.
Conversation:
{conversation_text or "(no previous turns)"}
Current Question: {question}
Search hint from caller: {hint or "(none)"}

Return JSON only:
{{
  "intent": "...",
  "needs_context": true/false,
  "is_personal": true/false,
  "search_term": "string or null",
  "entity": "string or null",
  "confidence": 0.00
}}

Allowed intent values:
- personal_profile
- personal_grade
- ucsi_programme
- ucsi_hostel
- ucsi_staff
- ucsi_facility
- ucsi_schedule
- general_person
- general_world
- capability_smalltalk
- unknown

Rules:
1. **CRITICAL**: You are a chatbot for UCSI University. The user is asking about the university.
2. If the query is ambiguous (e.g., "check-in time", "pets", "parking", "wifi", "fees", "rules", "dress code"), **YOU MUST ASSUME** it is about UCSI University (Hostel/Facility/Programme).
   - Classify these as `ucsi_hostel`, `ucsi_facility`, etc., and set `needs_context=true`.
   - DO NOT classify them as `general_world` unless it is completely unrelated to university life (e.g., "Capital of France", "How to cook pasta").
3. Use Conversation to resolve follow-up references like "that/it/one/same", "그거", "하나만", "그럼", "그리고".
4. Personal data requests (my profile, my GPA/grades) => is_personal=true and needs_context=true.
5. UCSI/campus/hostel/fees/programme/staff/facility/schedule => needs_context=true with concise search_term.
6. Generic person query not clearly tied to UCSI => general_person with needs_context=false; fill entity if possible.
7. Physical capability/smalltalk (can you dance/handstand, etc.) => capability_smalltalk with needs_context=false.
8. If uncertain, use unknown and set confidence <= 0.50.
9. Confidence must be a number between 0 and 1.
10. Language understanding: {lang_instruct}
"""

        if not await _circuit_breaker.can_execute():
            return None
        if not await _rate_limiter.acquire(timeout=10.0):
            return None

        try:
            for attempt in range(MAX_RETRIES):
                try:
                    response = await self.client.aio.models.generate_content(
                        model=self.model_name,
                        contents=prompt,
                    )
                    text = str(response.text or "")
                    await _circuit_breaker.record_success()
                    data = self._extract_json_dict(text)
                    if not isinstance(data, dict):
                        return None

                    intent = self._canonical_intent(data.get("intent"))
                    confidence = float(data.get("confidence") or 0.0)
                    confidence = max(0.0, min(confidence, 1.0))

                    is_personal = bool(data.get("is_personal"))
                    needs_context = bool(data.get("needs_context"))

                    if intent in {"personal_profile", "personal_grade"}:
                        is_personal = True
                        needs_context = True
                    if intent in {
                        "ucsi_programme",
                        "ucsi_hostel",
                        "ucsi_staff",
                        "ucsi_facility",
                        "ucsi_schedule",
                    }:
                        needs_context = True
                    if intent in {"general_person", "general_world", "capability_smalltalk"}:
                        needs_context = False

                    normalized_search = self._sanitize_search_term(data.get("search_term"))
                    if not normalized_search:
                        normalized_search = hint

                    entity = self._sanitize_entity(data.get("entity"))
                    if intent != "general_person":
                        entity = None

                    return {
                        "intent": intent,
                        "confidence": confidence,
                        "needs_context": needs_context,
                        "is_personal": is_personal,
                        "search_term": normalized_search,
                        "entity": entity,
                    }
                except Exception as e:
                    if "resource_exhausted" in str(e).lower() and attempt < (MAX_RETRIES - 1):
                        await asyncio.sleep(BASE_DELAY * (2 ** attempt))
                        continue
                    await _circuit_breaker.record_failure()
                    raise
        except Exception:
            return None

        return None

    async def process_message(
        self,
        user_message: str,
        data_context: str = "",
        conversation_history=None,
        language: str = "en",
        query_scope_hint: str | None = None,
        rlhf_policy_hint: str | None = None,
    ) -> dict:
        if not self.client:
            return {"response": "System Error: AI Model not initialized."}
            
        # Fast Path
        if FAST_PATH_ENABLED:
            fast = self._should_use_fast_path(user_message)
            if fast:
                return {"response": fast["text"], "needs_context": False}

        context_text = str(data_context or "").strip()
        conversation_text = self._format_conversation_text(
            conversation_history=conversation_history,
            user_message=user_message,
            limit=6,
        )

        # Construct Prompt
        lang_instruct = multilingual.get_ai_language_instruction(language)
        scope_rule = ""
        if query_scope_hint == "general_person":
            scope_rule = (
                "Additional scope hint:\n"
                "- This is a general person query (not UCSI-internal). "
                "Set needs_context=false and answer with general knowledge.\n"
                "- If uncertain, ask one short clarification question (do NOT say documents are missing)."
            )

        rlhf_rule = ""
        if rlhf_policy_hint:
            safe_hint = str(rlhf_policy_hint).strip()[:1200]
            if safe_hint:
                rlhf_rule = (
                    "RLHF policy guidance from historical user feedback:\n"
                    f"{safe_hint}\n"
                    "- Follow this policy unless it conflicts with factual grounding.\n"
                )

        # Build prompt based on whether UCSI context is available
        if context_text:
            # RAG context available → strict grounding mode
            prompt = f"""You are UCSI Buddy, a helpful AI assistant for UCSI University students and prospective students.

## Context (Database Information)
{context_text}

## Conversation History
{conversation_text or "(First message in conversation)"}

## Current Question
{user_message}

## Response Format
Output JSON: {{ "text": "...", "suggestions": [], "needs_context": bool, "search_term": string|null }}

## Response Guidelines
1. Grounding & Knowledge — Decide based on query type:
   A) SPECIFIC queries (about a named person, specific building, specific programme, specific fee):
      - Use ONLY the Context data. Present it accurately with Label: Value format.
      - Example: "tell me about Dr. Kim" → use Dr. Kim's data from Context.
   B) AGGREGATE / GENERAL queries (how many, list all, total count, overview, general facts about UCSI):
      - Do NOT use individual records from Context at all. Do NOT mention any specific names, emails, or positions from Context.
      - Answer BRIEFLY (2-3 sentences max) using your general knowledge about UCSI University.
      - Just answer the question directly and suggest visiting www.ucsiuniversity.edu.my for details.
      - Example: "how many lecturers in UCSI?" → "UCSI University employs several hundred academic staff across 9 faculties. For the exact number and full directory, please visit www.ucsiuniversity.edu.my."
   C) For specific facts (fees, room prices, staff emails, schedules), rely ONLY on Context — do NOT guess.
2. Missing Data:
   - If Context has [NO_RELEVANT_DATA_FOUND] but you have general knowledge about UCSI, share it briefly. Only say "unavailable" if you truly have nothing to offer.
   - If the user asks about a SPECIFIC person/thing and Context has that data, present it. If Context does NOT have it, say so honestly and suggest checking the UCSI website.
   - NEVER list tangentially related records. If the user asks "how many lecturers?" do NOT mention ANY individual names. If the user asks about a specific person and Context has different people, do NOT show those other people.
   - Only present data that DIRECTLY and PRECISELY answers the user's question.
3. Language: {lang_instruct}
4. Tone: Be friendly, helpful, and professional. Use natural conversational language.
5. Brevity: Keep responses concise but complete. Avoid unnecessary repetition.
6. Formatting Rules:
   - Use plain text only. Do NOT use markdown bold (**text**) or italic (*text*).
   - NEVER include database URLs (profile_url, map links, building_image links, programme URLs, coordinates) in the text. These are displayed separately as buttons/images by the system.
   - The ONLY URL you may include in text is the official UCSI website: www.ucsiuniversity.edu.my (when suggesting the user check for more info).
   - When presenting structured information (staff, buildings, programmes, hostels, schedules), use "Label: Value" format on separate lines for clarity.

7. Staff/Professor Info formatting example:
   Name: [full name]
   Position: [title/role]
   Faculty: [faculty or department]
   Email: [email address]
   Do NOT include profile_url or any URL.

8. Building/Block Info formatting example:
   Name: [building name]
   Campus: [campus name]
   Address: [address]
   Do NOT include map URLs, building_image URLs, or coordinates.

9. Hostel Info formatting example:
   Room Type: [type]
   Price: [price]
   Deposit: [amount]

10. Programme Info formatting example:
    Programme: [name]
    Faculty: [faculty]
    Duration: [duration]
    Tuition Fee: [fee]

## Context Rules
- UCSI/campus/hostel/fees/programme/staff/schedule/personal data → needs_context=true, provide search_term
- Generic world knowledge questions → needs_context=false

## Conversation Continuity
- Resolve pronouns and references ("it", "that", "the same one", "그거", "그 전에") using Conversation History
- When user narrows down from previous options, use prior context

## Quality Checks
- For specific numbers/facts from Context, verify they match exactly
- You may supplement with general knowledge for broader questions, but be transparent about it
- NEVER echo internal labels like [Document], [Hostel], [conf:X.XX], or MongoDB source names

{scope_rule}
{rlhf_rule}
"""
        else:
            # No context → free conversational mode
            prompt = f"""You are UCSI Buddy, a friendly and helpful AI assistant.

## Conversation History
{conversation_text or "(First message in conversation)"}

## Current Question
{user_message}

## Response Format
Output JSON: {{ "text": "...", "suggestions": [], "needs_context": bool, "search_term": string|null }}

## How to Respond
- For greetings, casual chat, or small talk: respond warmly and naturally like a friendly assistant
- For general knowledge questions: answer freely using your knowledge
- For UCSI University related questions (hostel, programmes, fees, staff, facilities, schedule): set needs_context=true and provide a search_term so the system can look up accurate data
- NEVER deflect to UCSI topics unless the user actually asks about UCSI
- If you don't know something, simply say so honestly

## Follow-up & Context Resolution
- IMPORTANT: Use Conversation History to resolve follow-up references
- Korean references: "그거", "그것", "그건", "아까", "위에", "그 전에" → check what was discussed before
- English references: "it", "that", "the same one", "those" → resolve using prior context
- If the user is following up on a UCSI topic from conversation history, set needs_context=true with an appropriate search_term

## Language
{lang_instruct}

## Tone
Be friendly, warm, and conversational. Match the user's energy and language style.

{scope_rule}
"""

        # Resilience Checks
        if not await _circuit_breaker.can_execute():
             return {"response": "Service paused for recovery.", "error_type": "circuit_open"}
        
        if not await _rate_limiter.acquire(timeout=10.0):
             return {"response": "Service busy, please wait.", "error_type": "rate_limited"}

        # API Call
        try:
            for attempt in range(MAX_RETRIES):
                try:
                    # Async Generation
                    response = await self.client.aio.models.generate_content(
                        model=self.model_name,
                        contents=prompt
                    )
                    text = response.text
                    await _circuit_breaker.record_success()
                    
                    # Parse JSON — use robust multi-strategy parser
                    data = self._extract_json_dict(text)
                    if data:
                        response_body = str(data.get("text") or text)
                        # Strip any accidentally echoed internal markers
                        response_body = re.sub(r"\[(?:Document|Hostel|Facility|Programme|Staff|Schedule|HostelFAQ|CampusBlocks|Verified Answer)\]\s*", "", response_body)
                        response_body = re.sub(r"\s*\[conf:[0-9.]+\]", "", response_body)
                        suggestions = data.get("suggestions")
                        if not isinstance(suggestions, list):
                            suggestions = []
                        return {
                            "response": response_body.strip(),
                            "suggestions": suggestions[:3],
                            "needs_context": bool(data.get("needs_context", False)),
                            "search_term": self._sanitize_search_term(data.get("search_term")),
                        }
                    
                    # Fallback: clean raw text response
                    clean_text = re.sub(r"\[(?:Document|Hostel|Facility|Programme|Staff|Schedule|HostelFAQ|CampusBlocks|Verified Answer)\]\s*", "", text)
                    clean_text = re.sub(r"\s*\[conf:[0-9.]+\]", "", clean_text).strip()
                    return {"response": clean_text or text, "needs_context": False, "search_term": None}
                    
                except Exception as e:
                    if "resource_exhausted" in str(e).lower():
                        await asyncio.sleep(BASE_DELAY * (2 ** attempt))
                        continue
                    await _circuit_breaker.record_failure()
                    raise e
                    
        except Exception as e:
            print(f"Async AI Error: {e}")
            return {"response": "I encountered an error processing your request.", "error_type": "ai_error"}

# Singleton
ai_engine_async = AsyncAIEngine()
