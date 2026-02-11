"""
Intent Configuration — Single Source of Truth for all keyword/pattern definitions.

Every file that needs keyword matching (intent_classifier, chat, chat_helpers)
imports from here. No more duplicate keyword lists.
"""

from typing import Dict, FrozenSet, List, Set, Tuple

# =============================================================================
# UCSI DOMAIN KEYWORDS — triggers RAG search
# =============================================================================

UCSI_KEYWORDS: FrozenSet[str] = frozenset({
    # English
    "ucsi", "campus", "hostel", "dorm", "dormitory", "accommodation",
    "tuition", "fee", "fees", "scholarship", "programme", "program",
    "faculty", "department", "lecturer", "professor", "dean", "staff",
    "library", "gym", "facility", "facilities", "cafeteria", "clinic",
    "block", "building", "semester", "intake", "schedule", "calendar",
    "exam", "examination", "registration", "enrollment", "admission",
    "student", "students", "alumni", "graduate",
    "pet", "dog", "cat", "animal",
    "rule", "policy", "regulation", "dress code", "attire", "uniform",
    "permission", "allowed", "forbidden", "ban", "fine", "penalty",
    "smoke", "smoking", "alcohol", "drinking", "parking", "car", "vehicle",
    "visitor", "guest", "curfew", "lockout",
    "wifi", "internet", "network", "print", "printing", "atm", "bank",
    "shuttle", "bus", "transport", "clinic", "doctor", "medical", "insurance",
    "aircon", "air conditioner", "laundry", "clean", "contract", "termination",
    "hours", "opening time", "close", "booking", "book", "holiday", "break",
    "orientation", "graduation", "commencement", "ielts", "muet", "entry requirement",
    "duration", "english requirement",

    # Korean
    "기숙사", "숙소", "등록금", "학비", "장학금", "전공", "학과", "학부",
    "교수", "강사", "학장", "직원", "도서관", "체육관", "시설", "식당",
    "블록", "건물", "학기", "입학", "일정", "시험", "등록", "캠퍼스",
    "학생", "재학생", "졸업생", "동문", "원생",
    "애완동물", "반려동물", "강아지", "고양이",
    "규정", "규칙", "정책", "복장", "옷차림", "유니폼",
    "허용", "금지", "벌금", "페널티", "흡연", "담배", "음주", "술",
    "주차", "차량", "방문객", "손님", "통금", "출입",
    "와이파이", "인터넷", "프린트", "인쇄", "은행", "셔틀", "버스", "교통",
    "병원", "진료", "보험",
})

# =============================================================================
# ENTITY TYPE KEYWORDS — determines what kind of rich content to show
# =============================================================================

STAFF_KEYWORDS: FrozenSet[str] = frozenset({
    "staff", "professor", "lecturer", "dean", "chancellor",
    "advisor", "adviser", "instructor", "teacher", "student", "pupil",
    "교수", "강사", "학장", "총장", "부총장", "직원", "지도교수", "학생",
})

BUILDING_KEYWORDS: FrozenSet[str] = frozenset({
    "block", "building", "map", "where", "location", "address",
    "블록", "건물", "어디", "지도", "위치", "캠퍼스 위치",
})

HOSTEL_KEYWORDS: FrozenSet[str] = frozenset({
    "hostel", "dorm", "dormitory", "accommodation", "room", "rent", "deposit",
    "pet", "dog", "cat", "animal",
    "기숙사", "숙소", "룸", "보증금", "애완동물", "반려동물",
})

PROGRAMME_KEYWORDS: FrozenSet[str] = frozenset({
    "programme", "program", "major", "course", "tuition", "fee",
    "scholarship", "diploma", "foundation", "bachelor", "master", "phd",
    "전공", "학과", "학부", "프로그램", "등록금", "입학",
})

SCHEDULE_KEYWORDS: FrozenSet[str] = frozenset({
    "schedule", "calendar", "event", "semester", "intake", "deadline", "exam",
    "학사일정", "일정", "학기", "입학시기", "마감", "시험",
})

# =============================================================================
# AGGREGATE QUERY PATTERNS — questions asking for counts, lists, totals
# These should NOT trigger rich content and should use LLM general knowledge.
# =============================================================================

AGGREGATE_PATTERNS: Tuple[str, ...] = (
    "how many", "list all", "count of", "number of",
    "all the", "every single", "complete list",
    "overview of", "summary of",
    "몇 명", "몇 개", "전체 목록", "모든 직원", "모든 교수",
    "총 몇", "얼마나 많",
)

# =============================================================================
# ENTITY TYPE DETECTION — maps keywords to entity types
# =============================================================================

ENTITY_KEYWORD_MAP: Dict[str, FrozenSet[str]] = {
    "staff": STAFF_KEYWORDS,
    "building": BUILDING_KEYWORDS,
    "hostel": HOSTEL_KEYWORDS,
    "programme": PROGRAMME_KEYWORDS,
    "schedule": SCHEDULE_KEYWORDS,
}

# =============================================================================
# INTENT → PREFERRED RAG LABELS
# =============================================================================

INTENT_TO_LABELS: Dict[str, List[str]] = {
    "ucsi_hostel": ["Hostel", "HostelFAQ"],
    "ucsi_facility": ["Facility", "CampusBlocks"],
    "ucsi_programme": ["Programme"],
    "ucsi_staff": ["Staff"],
    "ucsi_schedule": ["Schedule"],
}

ENTITY_TO_LABELS: Dict[str, List[str]] = {
    "hostel": ["Hostel", "HostelFAQ"],
    "building": ["Facility", "CampusBlocks"],
    "programme": ["Programme"],
    "staff": ["Staff"],
    "student": ["Student", "Staff"],
    "schedule": ["Schedule"],
}


# =============================================================================
# HELPER FUNCTIONS — reusable across all files
# =============================================================================

def has_ucsi_keywords(text: str) -> bool:
    """Check if text contains any UCSI domain keyword."""
    lowered = text.lower()
    return any(kw in lowered for kw in UCSI_KEYWORDS)


def detect_entity_type(text: str) -> str | None:
    """Detect entity type from text. Returns 'staff', 'building', etc. or None."""
    lowered = text.lower()
    for entity_type, keywords in ENTITY_KEYWORD_MAP.items():
        if any(kw in lowered for kw in keywords):
            return entity_type
    return None


def is_aggregate_query(text: str) -> bool:
    """Check if text is an aggregate/statistical question."""
    lowered = text.lower()
    return any(pattern in lowered for pattern in AGGREGATE_PATTERNS)


def get_preferred_labels(intent: str | None = None, entity_type: str | None = None) -> list[str] | None:
    """Get preferred RAG labels from intent or entity type."""
    if intent and intent in INTENT_TO_LABELS:
        return INTENT_TO_LABELS[intent]
    if entity_type and entity_type in ENTITY_TO_LABELS:
        return ENTITY_TO_LABELS[entity_type]
    return None
