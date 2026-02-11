"""
UX Engine for UCSI Buddy Chatbot

Improves user experience through:
1. Greeting messages - friendly first impressions
2. Error handling - helpful error messages
3. Response formatting - clear, structured responses
4. Conversation flow - smooth multi-turn interactions
5. Clarification - asking when uncertain
6. Tone management - friendly, professional tone
"""

import re
import random
from typing import Any, Dict, List, Optional
from datetime import datetime


# =============================================================================
# GREETING MESSAGES
# =============================================================================

GREETINGS = {
    "en": {
        "morning": [
            "Good morning! How can I help you today?",
            "Morning! What would you like to know about UCSI?",
        ],
        "afternoon": [
            "Good afternoon! How may I assist you?",
            "Hello! What can I help you with today?",
        ],
        "evening": [
            "Good evening! How can I help you?",
            "Evening! What would you like to know?",
        ],
        "default": [
            "Hello! I'm UCSI Buddy. How can I help you today?",
            "Hi there! What would you like to know about UCSI?",
            "Welcome! I'm here to help with any UCSI-related questions.",
        ],
        "returning": [
            "Welcome back! How can I help you?",
            "Good to see you again! What can I do for you?",
        ],
    },
    "ko": {
        "morning": [
            "좋은 아침이에요! 무엇을 도와드릴까요?",
            "안녕하세요! UCSI에 대해 궁금한 게 있으신가요?",
        ],
        "afternoon": [
            "안녕하세요! 무엇을 도와드릴까요?",
            "반갑습니다! 어떤 것이 궁금하세요?",
        ],
        "evening": [
            "좋은 저녁이에요! 무엇을 도와드릴까요?",
            "안녕하세요! 궁금한 것이 있으시면 물어봐 주세요.",
        ],
        "default": [
            "안녕하세요! UCSI Buddy입니다. 무엇을 도와드릴까요?",
            "반갑습니다! UCSI에 대해 궁금한 것이 있으시면 물어봐 주세요.",
        ],
        "returning": [
            "다시 오셨군요! 무엇을 도와드릴까요?",
            "반가워요! 어떤 것이 궁금하세요?",
        ],
    },
}


def get_greeting(language: str = "en", is_returning: bool = False) -> str:
    """Get appropriate greeting based on time and user status."""
    hour = datetime.now().hour
    lang_greetings = GREETINGS.get(language, GREETINGS["en"])

    if is_returning:
        return random.choice(lang_greetings["returning"])

    if 5 <= hour < 12:
        return random.choice(lang_greetings["morning"])
    elif 12 <= hour < 18:
        return random.choice(lang_greetings["afternoon"])
    elif 18 <= hour < 22:
        return random.choice(lang_greetings["evening"])
    else:
        return random.choice(lang_greetings["default"])


# =============================================================================
# ERROR MESSAGES
# =============================================================================

ERROR_MESSAGES = {
    "en": {
        "generic": "I apologize, but I encountered an issue. Please try again.",
        "no_data": "I couldn't find information about that in my knowledge base. Could you try rephrasing your question?",
        "login_required": "Please log in to access your personal information.",
        "password_required": "For security, please verify your password to view grade information.",
        "rate_limited": "I'm receiving many requests right now. Please wait a moment.",
        "timeout": "The request took too long. Please try again.",
        "invalid_input": "I didn't quite understand that. Could you please rephrase?",
        "ambiguous": "I'm not sure what you're asking about. Could you be more specific?",
    },
    "ko": {
        "generic": "죄송합니다, 문제가 발생했어요. 다시 시도해 주세요.",
        "no_data": "해당 정보를 찾지 못했어요. 다른 방식으로 질문해 주시겠어요?",
        "login_required": "개인 정보를 보려면 로그인이 필요해요.",
        "password_required": "보안을 위해 성적 정보 조회 시 비밀번호 확인이 필요해요.",
        "rate_limited": "지금 요청이 많아요. 잠시 후 다시 시도해 주세요.",
        "timeout": "요청이 오래 걸리고 있어요. 다시 시도해 주세요.",
        "invalid_input": "이해하지 못했어요. 다시 말씀해 주시겠어요?",
        "ambiguous": "무엇에 대해 물어보시는 건지 잘 모르겠어요. 조금 더 구체적으로 말씀해 주시겠어요?",
    },
}


def get_error_message(error_type: str, language: str = "en") -> str:
    """Get localized error message."""
    lang_errors = ERROR_MESSAGES.get(language, ERROR_MESSAGES["en"])
    return lang_errors.get(error_type, lang_errors["generic"])


# =============================================================================
# RESPONSE FORMATTING
# =============================================================================

def format_list_response(items: List[str], title: str = "", language: str = "en") -> str:
    """Format a list of items nicely."""
    if not items:
        return ""

    formatted = []
    if title:
        formatted.append(f"**{title}**\n")

    for i, item in enumerate(items, 1):
        formatted.append(f"{i}. {item}")

    return "\n".join(formatted)


def format_key_value_response(data: Dict[str, Any], language: str = "en") -> str:
    """Format key-value pairs nicely."""
    if not data:
        return ""

    lines = []
    for key, value in data.items():
        # Convert key to readable format
        readable_key = key.replace("_", " ").title()
        lines.append(f"**{readable_key}**: {value}")

    return "\n".join(lines)


def truncate_response(text: str, max_length: int = 1500, language: str = "en") -> str:
    """Truncate long responses with a note."""
    if not text or len(text) <= max_length:
        return text

    # Find a good break point
    truncated = text[:max_length]
    last_period = truncated.rfind(".")
    last_newline = truncated.rfind("\n")

    break_point = max(last_period, last_newline)
    if break_point > max_length * 0.7:
        truncated = truncated[:break_point + 1]

    if language == "ko":
        truncated += "\n\n_(더 자세한 정보가 필요하시면 질문해 주세요.)_"
    else:
        truncated += "\n\n_(Ask for more details if needed.)_"

    return truncated


def add_friendly_closing(text: str, language: str = "en", has_more: bool = False) -> str:
    """Add a friendly closing to responses."""
    if not text:
        return text

    # Don't add if already has a closing
    closings_to_check = [
        "더 궁금", "도움이", "질문이", "알려드릴",
        "help", "question", "else", "more",
    ]
    if any(c in text.lower() for c in closings_to_check):
        return text

    # Add appropriate closing
    if has_more:
        if language == "ko":
            return text + "\n\n더 궁금한 점이 있으시면 물어봐 주세요!"
        return text + "\n\nFeel free to ask if you have more questions!"
    else:
        if language == "ko":
            return text + "\n\n도움이 되셨나요?"
        return text + "\n\nWas this helpful?"

    return text


# =============================================================================
# CLARIFICATION
# =============================================================================

CLARIFICATION_TEMPLATES = {
    "en": {
        "ambiguous_person": "I found multiple matches for '{name}'. Did you mean:\n{options}\nPlease specify which one.",
        "ambiguous_topic": "Your question could be about several topics:\n{options}\nWhich one are you interested in?",
        "need_more_info": "Could you provide more details? For example:\n{suggestions}",
        "confirm_intent": "Just to make sure, are you asking about {topic}?",
    },
    "ko": {
        "ambiguous_person": "'{name}'에 해당하는 결과가 여러 개 있어요:\n{options}\n어떤 것을 말씀하시는 건가요?",
        "ambiguous_topic": "여러 주제에 해당할 수 있어요:\n{options}\n어떤 것에 대해 알고 싶으세요?",
        "need_more_info": "조금 더 구체적으로 말씀해 주시겠어요? 예를 들어:\n{suggestions}",
        "confirm_intent": "혹시 {topic}에 대해 물어보시는 건가요?",
    },
}


def create_clarification_message(
    clarification_type: str,
    language: str = "en",
    **kwargs,
) -> str:
    """Create a clarification message."""
    lang_templates = CLARIFICATION_TEMPLATES.get(language, CLARIFICATION_TEMPLATES["en"])
    template = lang_templates.get(clarification_type, "Could you please clarify?")

    try:
        return template.format(**kwargs)
    except KeyError:
        return template


# =============================================================================
# CONVERSATION CONTINUITY
# =============================================================================

def create_follow_up_suggestions(
    current_topic: str,
    language: str = "en",
    user_type: str = "guest",
) -> List[str]:
    """Create contextual follow-up suggestions."""
    suggestions = {
        "en": {
            "hostel": [
                "What's included in the hostel fee?",
                "Can I pay by installment?",
                "What are the room types?",
            ],
            "programme": [
                "What are the entry requirements?",
                "How long is the programme?",
                "What's the tuition fee?",
            ],
            "staff": [
                "How can I contact them?",
                "What's their office location?",
                "What are their office hours?",
            ],
            "personal": [
                "Show my GPA",
                "What's my programme?",
                "Who is my advisor?",
            ],
            "default": [
                "Tell me about UCSI hostel",
                "What programmes are offered?",
                "How do I contact staff?",
            ],
        },
        "ko": {
            "hostel": [
                "기숙사 비용에 뭐가 포함되어 있어요?",
                "분할 납부 가능해요?",
                "방 종류는 어떤 게 있어요?",
            ],
            "programme": [
                "입학 조건이 뭐예요?",
                "기간이 얼마나 되나요?",
                "등록금은 얼마예요?",
            ],
            "staff": [
                "어떻게 연락하나요?",
                "사무실 위치가 어디예요?",
                "근무 시간이 어떻게 되나요?",
            ],
            "personal": [
                "내 GPA 보여줘",
                "내 전공이 뭐야?",
                "내 지도교수가 누구야?",
            ],
            "default": [
                "UCSI 기숙사 알려줘",
                "어떤 전공이 있어요?",
                "직원에게 어떻게 연락해요?",
            ],
        },
    }

    lang_suggestions = suggestions.get(language, suggestions["en"])
    topic_suggestions = lang_suggestions.get(current_topic, lang_suggestions["default"])

    # Add personal suggestions if logged in
    if user_type == "student" and current_topic != "personal":
        personal = lang_suggestions.get("personal", [])[:1]
        topic_suggestions = personal + topic_suggestions[:2]

    return topic_suggestions[:3]


# =============================================================================
# TYPING INDICATOR MESSAGES
# =============================================================================

def get_thinking_message(language: str = "en") -> str:
    """Get a 'thinking' message for typing indicator."""
    messages = {
        "en": [
            "Let me check that for you...",
            "Looking up the information...",
            "One moment please...",
        ],
        "ko": [
            "확인해 볼게요...",
            "정보를 찾고 있어요...",
            "잠시만 기다려 주세요...",
        ],
    }
    lang_messages = messages.get(language, messages["en"])
    return random.choice(lang_messages)


# =============================================================================
# MAIN UX CLASS
# =============================================================================

class UXEngine:
    """
    Main UX Engine for enhancing user experience.
    """

    def __init__(self):
        self.conversation_topics = {}  # Track topics per session

    def enhance_response(
        self,
        response_text: str,
        language: str = "en",
        category: str = "general",
        sources: List[str] = None,
        is_first_message: bool = False,
        session_id: str = None,
    ) -> Dict[str, Any]:
        """
        Enhance a response with UX improvements.

        Returns:
            {
                "text": str,
                "suggestions": List[str],
                "metadata": Dict
            }
        """
        # Track topic for this session
        if session_id:
            self.conversation_topics[session_id] = category

        # Format the response
        enhanced_text = response_text

        # Add greeting for first message
        if is_first_message and not response_text.startswith(("Hello", "Hi", "안녕")):
            greeting = get_greeting(language, is_returning=False)
            enhanced_text = f"{greeting}\n\n{enhanced_text}"

        # Truncate if too long
        enhanced_text = truncate_response(enhanced_text, language=language)

        # Generate follow-up suggestions
        topic = self._infer_topic(category, sources)
        suggestions = create_follow_up_suggestions(topic, language)

        return {
            "text": enhanced_text,
            "suggestions": suggestions,
            "metadata": {
                "category": category,
                "topic": topic,
                "enhanced": True,
            },
        }

    def _infer_topic(self, category: str, sources: List[str] = None) -> str:
        """Infer the topic from category and sources."""
        if category == "personal":
            return "personal"

        if sources:
            source_str = " ".join(sources).lower()
            if "hostel" in source_str:
                return "hostel"
            if "programme" in source_str or "major" in source_str:
                return "programme"
            if "staff" in source_str:
                return "staff"

        return "default"

    def handle_error(
        self,
        error_type: str,
        language: str = "en",
        details: str = None,
    ) -> str:
        """Handle errors with user-friendly messages."""
        message = get_error_message(error_type, language)

        if details and error_type == "no_data":
            if language == "ko":
                message += f"\n\n검색어: {details}"
            else:
                message += f"\n\nSearch term: {details}"

        return message

    def create_clarification(
        self,
        clarification_type: str,
        language: str = "en",
        **kwargs,
    ) -> str:
        """Create a clarification request."""
        return create_clarification_message(clarification_type, language, **kwargs)


# Singleton instance
ux_engine = UXEngine()
