"""
Hybrid Intent Classifier for UCSI Buddy Chatbot

Classification Flow:
1. Keyword Guard - Force RAG for UCSI keywords, force personal for personal keywords
2. Vector Search - Fast semantic similarity matching
3. LLM Fallback - When vector confidence is low

Categories:
- ucsi_domain: UCSI-specific info (hostel, programme, staff, facility, schedule)
- personal: User's personal data (profile, grades)
- general_knowledge: General world knowledge, famous people, etc.
"""

import re
from typing import Any, Dict, List, Optional

from app.engines.semantic_router_async import semantic_router_async
from app.engines.ai_engine_async import ai_engine_async
from app.engines.intent_config import (
    UCSI_KEYWORDS,
    has_ucsi_keywords as _config_has_ucsi_keywords,
    detect_entity_type as _config_detect_entity_type,
    is_aggregate_query as _config_is_aggregate,
)


# =============================================================================
# CONFIGURATION
# =============================================================================

VECTOR_HIGH_CONFIDENCE = 0.65  # Vector result is trusted
VECTOR_LOW_CONFIDENCE = 0.45   # Below this, definitely need LLM help
LLM_MIN_CONFIDENCE = 0.55      # LLM result minimum to be trusted

# UCSI_KEYWORDS is now imported from intent_config.py (single source of truth)

# Personal query patterns
PERSONAL_PATTERNS = [
    # English
    r"\bmy\s+(grade|gpa|cgpa|result|profile|info|information|id|nationality|advisor|adviser|major|programme|program)\b",
    r"\b(show|tell|what('s|is)?)\s+(me\s+)?my\b",
    r"\bwho\s+am\s+i\b",
    r"\bam\s+i\b",
    # Korean
    r"내\s*(정보|프로필|성적|학점|점수|gpa|국적|전공|학번|지도교수)",
    r"나는\s*누구",
    r"제\s*(정보|프로필|성적)",
]

# Grade-specific patterns (requires high security)
GRADE_PATTERNS = [
    r"\b(grade|gpa|cgpa|result|score|exam)\b",
    r"\b(성적|학점|점수|평점)\b",
]

# Capability/smalltalk patterns
CAPABILITY_PATTERNS = [
    r"\b(can|could|do|will|would)\s+you\s+(please\s+)?(do\s+)?(a\s+)?(dance|sing|jump|run|swim|stand|crawl|roll|fly|handstand)\b",
    r"\bwhat\s+can\s+you\s+do\b",
    r"\bwhat\s+do\s+you\s+do\b",
    r"\bwhat\s+are\s+you\b",
    r"\bwho\s+are\s+you\b",
    r"\bhow\s+can\s+you\s+help\b",
    r"물구나무",
    r"(춤|노래|점프).*(해|춰|불러)",
    r"(너|넌|니가|네가).*(뭘|뭐|무엇).*(해줄|할|도와|하는|할\s*수)",
    r"(뭘|뭐|무엇).*(해줄|할|도와).*(수|있)",
    r"(너|넌).*(누구|뭐야|뭐니)",
    r"(어떤|무슨)\s*(도움|기능|일).*(줄|할|수)",
    r"(도와|도움).*(줄|줘|주).*(수|있|뭐)",
]


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _normalize_text(text: str) -> str:
    """Normalize text for matching."""
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def _has_ucsi_keywords(message: str) -> bool:
    """Check if message contains UCSI-related keywords. Delegates to intent_config."""
    return _config_has_ucsi_keywords(message)


def _is_personal_query(message: str) -> bool:
    """Check if message is asking about personal information."""
    text = _normalize_text(message)
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in PERSONAL_PATTERNS)


def _is_grade_query(message: str) -> bool:
    """Check if message is specifically about grades/GPA."""
    text = _normalize_text(message)
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in GRADE_PATTERNS)


def _is_capability_query(message: str) -> bool:
    """Check if message is capability/smalltalk question."""
    text = _normalize_text(message)
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in CAPABILITY_PATTERNS)


def _extract_search_term(message: str, intent: str) -> Optional[str]:
    """Extract a search term for RAG based on the intent."""
    text = str(message or "").strip()
    if len(text) > 80:
        text = text[:80]
    return text if text else None


def _map_intent_to_category(intent: str) -> str:
    """Map semantic router intent to category."""
    personal_intents = {"personal_profile", "personal_grade"}
    ucsi_intents = {"ucsi_programme", "ucsi_hostel", "ucsi_staff", "ucsi_facility", "ucsi_schedule"}
    general_intents = {"general_world", "general_person"}
    capability_intents = {"capability_smalltalk"}

    if intent in personal_intents:
        return "personal"
    elif intent in ucsi_intents:
        return "ucsi_domain"
    elif intent == "general_person":
        # Check RAG for names (could be student/staff)
        return "general_person_check"
    elif intent in general_intents:
        return "general_knowledge"
    elif intent in capability_intents:
        return "capability"
    else:
        return "unknown"


def _detect_query_type(message: str) -> str:
    """Detect whether the query is specific or aggregate.
    Returns: 'aggregate' | 'specific'
    """
    if _config_is_aggregate(message):
        return "aggregate"
    return "specific"


def _detect_entity(message: str) -> str | None:
    """Detect entity type from message. Delegates to intent_config."""
    return _config_detect_entity_type(message)


# =============================================================================
# MAIN CLASSIFIER
# =============================================================================

class IntentClassifier:
    """
    Hybrid Intent Classifier

    Flow:
    1. Keyword Guard (highest priority)
    2. Vector Search (fast, primary)
    3. LLM Fallback (when uncertain)
    """

    async def classify(
        self,
        user_message: str,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
        language: str = "en",
        search_term: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Classify user intent using hybrid approach.

        Returns:
            {
                "category": "ucsi_domain" | "personal" | "general_knowledge" | "capability",
                "intent": "ucsi_hostel" | "personal_grade" | "general_world" | ...,
                "confidence": 0.0 ~ 1.0,
                "needs_rag": True | False,
                "is_personal": True | False,
                "is_grade_query": True | False,
                "search_term": str | None,
                "source": "keyword_guard" | "vector" | "llm" | "hybrid",
                "debug": { ... }  # For debugging
            }
        """
        message = str(user_message or "").strip()
        if not message:
            return self._empty_result()

        debug_info = {
            "keyword_guard": None,
            "vector_result": None,
            "llm_result": None,
            "decision_reason": None,
        }

        # =================================================================
        # [1] KEYWORD GUARD - Highest Priority
        # =================================================================

        # Personal query check (must be first)
        if _is_personal_query(message):
            is_grade = _is_grade_query(message)
            debug_info["keyword_guard"] = "personal_query_detected"
            debug_info["decision_reason"] = "Keyword guard: personal pattern matched"

            return {
                "category": "personal",
                "intent": "personal_grade" if is_grade else "personal_profile",
                "confidence": 1.0,
                "needs_rag": False,
                "is_personal": True,
                "is_grade_query": is_grade,
                "search_term": None,
                "source": "keyword_guard",
                "query_type": "specific",
                "entity_type": None,
                "debug": debug_info,
            }

        # Greeting / simple hi check — fast route to capability handler
        _greeting_tokens = {
            "hi", "hello", "hey", "hii", "hiii", "yo", "sup",
            "good morning", "good afternoon", "good evening",
            "안녕", "안녕하세요", "하이", "헬로", "반가워", "반갑습니다",
            "야", "이봐", "저기", "저기요", "ㅎㅇ", "ㅎㅎ", "ㅋㅋ",
            "하잉", "방가", "방가워",
        }
        msg_stripped = re.sub(r"[!?.~,]+$", "", _normalize_text(message)).strip()
        if msg_stripped in _greeting_tokens:
            debug_info["keyword_guard"] = "greeting_detected"
            debug_info["decision_reason"] = "Keyword guard: greeting pattern matched"
            return {
                "category": "capability",
                "intent": "capability_smalltalk",
                "confidence": 1.0,
                "needs_rag": False,
                "is_personal": False,
                "is_grade_query": False,
                "search_term": None,
                "source": "keyword_guard",
                "query_type": "specific",
                "entity_type": None,
                "debug": debug_info,
            }

        # Short Korean casual message detection (3 chars or less, not UCSI keyword)
        if len(msg_stripped) <= 3 and not _has_ucsi_keywords(message):
            has_korean = any(0xAC00 <= ord(ch) <= 0xD7A3 or 0x3131 <= ord(ch) <= 0x318E for ch in msg_stripped)
            if has_korean:
                debug_info["keyword_guard"] = "short_korean_casual_detected"
                debug_info["decision_reason"] = "Keyword guard: short Korean casual message"
                return {
                    "category": "capability",
                    "intent": "capability_smalltalk",
                    "confidence": 1.0,
                    "needs_rag": False,
                    "is_personal": False,
                    "is_grade_query": False,
                    "search_term": None,
                    "source": "keyword_guard",
                    "query_type": "specific",
                    "entity_type": None,
                    "debug": debug_info,
                }

        # Capability/smalltalk check
        if _is_capability_query(message):
            debug_info["keyword_guard"] = "capability_query_detected"
            debug_info["decision_reason"] = "Keyword guard: capability pattern matched"

            return {
                "category": "capability",
                "intent": "capability_smalltalk",
                "confidence": 1.0,
                "needs_rag": False,
                "is_personal": False,
                "is_grade_query": False,
                "search_term": None,
                "source": "keyword_guard",
                "query_type": "specific",
                "entity_type": None,
                "debug": debug_info,
            }

        # UCSI keyword check - Force RAG
        has_ucsi = _has_ucsi_keywords(message)
        if has_ucsi:
            debug_info["keyword_guard"] = "ucsi_keywords_detected"

        # =================================================================
        # [2] VECTOR SEARCH - Fast Primary Classification
        # =================================================================

        vector_result = await semantic_router_async.classify(
            user_message=message,
            search_term=search_term,
            language=language,
            conversation_history=conversation_history,
        )

        vector_intent = str((vector_result or {}).get("intent") or "unknown")
        vector_confidence = float((vector_result or {}).get("confidence") or 0.0)

        debug_info["vector_result"] = {
            "intent": vector_intent,
            "confidence": vector_confidence,
        }

        # If UCSI keywords detected, force UCSI domain regardless of vector result
        if has_ucsi:
            # Use vector intent if it's UCSI-related, otherwise default
            if vector_intent.startswith("ucsi_"):
                final_intent = vector_intent
            else:
                final_intent = "ucsi_general"

            q_type = _detect_query_type(message)
            e_type = _detect_entity(message)

            # Aggregate queries: still classify as ucsi_domain but mark query_type
            # so chat.py can route to LLM-First instead of RAG
            if q_type == "aggregate":
                debug_info["decision_reason"] = "UCSI keywords + aggregate query → LLM-First route"
            else:
                debug_info["decision_reason"] = "UCSI keywords force RAG"

            return {
                "category": "ucsi_domain",
                "intent": final_intent,
                "confidence": max(vector_confidence, 0.7),
                "needs_rag": q_type != "aggregate",
                "is_personal": False,
                "is_grade_query": False,
                "search_term": _extract_search_term(message, final_intent),
                "source": "keyword_guard",
                "query_type": q_type,
                "entity_type": e_type,
                "debug": debug_info,
            }

        # Vector result is confident enough
        if vector_confidence >= VECTOR_HIGH_CONFIDENCE:
            category = _map_intent_to_category(vector_intent)
            debug_info["decision_reason"] = f"Vector confidence high ({vector_confidence:.2f} >= {VECTOR_HIGH_CONFIDENCE})"

            q_type = _detect_query_type(message)
            e_type = _detect_entity(message)
            return {
                "category": "personal" if category == "personal" else ("ucsi_domain" if category == "general_person_check" else category),
                "intent": vector_intent,
                "confidence": vector_confidence,
                "needs_rag": (category == "ucsi_domain" or category == "general_person_check") and q_type != "aggregate",
                "is_personal": category == "personal",
                "is_grade_query": vector_intent == "personal_grade",
                "search_term": _extract_search_term(message, vector_intent) if (category in ("ucsi_domain", "general_person_check")) else None,
                "source": "vector",
                "query_type": q_type,
                "entity_type": e_type,
                "debug": debug_info,
            }

        # =================================================================
        # [3] LLM FALLBACK - When Vector is Uncertain
        # =================================================================

        # Check if it looks like general knowledge (before calling LLM)
        # Old logic removed: Do NOT assume general knowledge just because keywords are missing.
        # We want to ask the LLM (plan_intent) to decide if it's UCSI related.
        # if _is_general_knowledge(message) and vector_confidence < VECTOR_LOW_CONFIDENCE: ...

        # Call LLM for assistance
        llm_result = await ai_engine_async.plan_intent(
            user_message=message,
            conversation_history=conversation_history,
            language=language,
            search_term=search_term,
        )

        llm_intent = str((llm_result or {}).get("intent") or "unknown")
        llm_confidence = float((llm_result or {}).get("confidence") or 0.0)
        llm_needs_context = bool((llm_result or {}).get("needs_context"))

        debug_info["llm_result"] = {
            "intent": llm_intent,
            "confidence": llm_confidence,
            "needs_context": llm_needs_context,
        }

        # =================================================================
        # [4] MERGE DECISIONS
        # =================================================================

        # LLM is confident
        if llm_confidence >= LLM_MIN_CONFIDENCE and llm_intent != "unknown":
            category = _map_intent_to_category(llm_intent)

            # Override: if LLM says no context needed but vector found UCSI intent
            if not llm_needs_context and vector_intent.startswith("ucsi_") and vector_confidence >= VECTOR_LOW_CONFIDENCE:
                debug_info["decision_reason"] = "LLM says no context, but vector found UCSI - trusting vector"
                q_type = _detect_query_type(message)
                e_type = _detect_entity(message)
                return {
                    "category": "ucsi_domain",
                    "intent": vector_intent,
                    "confidence": vector_confidence,
                    "needs_rag": q_type != "aggregate",
                    "is_personal": False,
                    "is_grade_query": False,
                    "search_term": _extract_search_term(message, vector_intent),
                    "source": "hybrid",
                    "query_type": q_type,
                    "entity_type": e_type,
                    "debug": debug_info,
                }

            debug_info["decision_reason"] = f"LLM confident ({llm_confidence:.2f} >= {LLM_MIN_CONFIDENCE})"

            q_type = _detect_query_type(message)
            e_type = _detect_entity(message)
            return {
                "category": category,
                "intent": llm_intent,
                "confidence": llm_confidence,
                "needs_rag": (llm_needs_context or category == "ucsi_domain") and q_type != "aggregate",
                "is_personal": category == "personal",
                "is_grade_query": llm_intent == "personal_grade",
                "search_term": (llm_result or {}).get("search_term") or _extract_search_term(message, llm_intent),
                "source": "llm",
                "query_type": q_type,
                "entity_type": e_type,
                "debug": debug_info,
            }

        # Both uncertain - use vector if it has something, otherwise general
        if vector_confidence >= VECTOR_LOW_CONFIDENCE:
            category = _map_intent_to_category(vector_intent)
            debug_info["decision_reason"] = f"Both uncertain, using vector ({vector_confidence:.2f})"

            q_type = _detect_query_type(message)
            e_type = _detect_entity(message)
            return {
                "category": category,
                "intent": vector_intent,
                "confidence": vector_confidence,
                "needs_rag": category == "ucsi_domain" and q_type != "aggregate",
                "is_personal": category == "personal",
                "is_grade_query": vector_intent == "personal_grade",
                "search_term": _extract_search_term(message, vector_intent) if category == "ucsi_domain" else None,
                "source": "vector",
                "query_type": q_type,
                "entity_type": e_type,
                "debug": debug_info,
            }

        # Fallback to general knowledge
        debug_info["decision_reason"] = "All classifiers uncertain, defaulting to general_knowledge"

        return {
            "category": "general_knowledge",
            "intent": "general_world",
            "confidence": 0.4,
            "needs_rag": False,
            "is_personal": False,
            "is_grade_query": False,
            "search_term": None,
            "source": "fallback",
            "query_type": "specific",
            "entity_type": None,
            "debug": debug_info,
        }

    def _empty_result(self) -> Dict[str, Any]:
        """Return empty/error result."""
        return {
            "category": "unknown",
            "intent": "unknown",
            "confidence": 0.0,
            "needs_rag": False,
            "is_personal": False,
            "is_grade_query": False,
            "search_term": None,
            "source": "error",
            "query_type": "specific",
            "entity_type": None,
            "debug": {"error": "Empty message"},
        }


# Singleton instance
intent_classifier = IntentClassifier()
