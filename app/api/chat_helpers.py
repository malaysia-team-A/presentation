import json
import re
from typing import Any, Dict, List, Optional

from app.config import Config


def _extract_rich_content(context_text: str) -> Dict[str, Any]:
    """Extract URLs, images, and map links from RAG context for rich display."""
    links: List[Dict[str, str]] = []
    images: List[Dict[str, str]] = []
    seen_urls: set = set()

    if not context_text:
        return {"links": links, "images": images}

    # --- Staff profile URLs (structured format: [staff] name: X | ... | profile_url: URL) ---
    staff_blocks = re.finditer(
        r"\[staff\]\s*name:\s*([^|]+?)(?:\s*\|)", context_text, re.IGNORECASE,
    )
    for block_match in staff_blocks:
        staff_name = block_match.group(1).strip()
        # Find profile_url in the same staff block (until next [staff] or section break)
        block_start = block_match.start()
        next_block = re.search(r"\[staff\]|\[conf:", context_text[block_start + 10:])
        block_end = (block_start + 10 + next_block.start()) if next_block else len(context_text)
        block_text = context_text[block_start:block_end]
        url_match = re.search(r"profile_url:\s*(https?://[^\s|,\]]+)", block_text)
        if url_match:
            url = url_match.group(1).strip().rstrip("'\"}")
            if url not in seen_urls:
                seen_urls.add(url)
                label = f"View {staff_name}'s Profile" if staff_name else "View Staff Profile"
                links.append({"url": url, "type": "staff_profile", "label": label})

    # Fallback: legacy dict format {'profile_url': 'URL', 'name': 'X'}
    legacy_staff = re.finditer(
        r"['\"]?profile_url['\"]?\s*:\s*['\"]?(https?://[^\s'\"}\|,]+)", context_text,
    )
    for match in legacy_staff:
        url = match.group(1).strip().rstrip("'\"}")
        if url not in seen_urls:
            seen_urls.add(url)
            # Try to extract name from nearby context
            nearby = context_text[max(0, match.start() - 200):match.start()]
            name_match = re.search(r"['\"]?name['\"]?\s*:\s*['\"]?([^'\"}\|,]+)", nearby)
            name = name_match.group(1).strip() if name_match else ""
            label = f"View {name}'s Profile" if name else "View Staff Profile"
            links.append({"url": url, "type": "staff_profile", "label": label})

    # --- Building images (CampusBlocks) ---
    image_matches = re.finditer(
        r"building_image:\s*(https?://[^\s\|,\]]+)", context_text, re.IGNORECASE,
    )
    for match in image_matches:
        url = match.group(1).strip().rstrip("'\"| ")
        if url and url not in seen_urls:
            seen_urls.add(url)
            # Extract block name from preceding context
            preceding = context_text[max(0, match.start() - 300):match.start()]
            name_match = re.search(r"name:\s*([^|]+)", preceding)
            block_name = name_match.group(1).strip() if name_match else ""
            label = block_name if block_name else "Building Image"
            images.append({"url": url, "type": "building_image", "label": label})

    # --- Map links (CampusBlocks) ---
    map_matches = re.finditer(
        r"(?:^|\|)\s*map:\s*(https?://[^\s\|,\]]+)", context_text, re.IGNORECASE,
    )
    for match in map_matches:
        url = match.group(1).strip().rstrip("'\"| ")
        if url and url not in seen_urls:
            seen_urls.add(url)
            links.append({"url": url, "type": "map", "label": "View on Map"})

    # --- Programme URLs ---
    url_matches = re.finditer(r"Url:\s*(https?://[^\s\|,\]]+)", context_text)
    for match in url_matches:
        url = match.group(1).strip().rstrip("'\"| ")
        if url and url not in seen_urls:
            seen_urls.add(url)
            links.append({"url": url, "type": "programme_info", "label": "More Information"})

    return {"links": links[:5], "images": images[:3]}

def _user_student_number(user: Optional[dict]) -> str:
    return str((user or {}).get("sub") or (user or {}).get("student_number") or "").strip()


def _user_display_name(user: Optional[dict]) -> str:
    name = str((user or {}).get("name") or "").strip()
    return name or "Guest"



def _contains_token(text: str, keyword: str) -> bool:
    t = (text or "").lower()
    kw = (keyword or "").strip().lower()
    if not t or not kw:
        return False
    if " " in kw:
        return kw in t
    return re.search(rf"(?<![a-z0-9]){re.escape(kw)}(?![a-z0-9])", t) is not None


def _is_grade_query(message: str, search_term: Optional[str]) -> bool:
    q = (message or "").lower()
    st = (search_term or "").lower()
    keywords = [
        "grade",
        "result",
        "exam",
        "score",
        "gpa",
        "cgpa",
        "성적",
        "점수",
        "학점",
        "평점",
    ]
    return any(k in q for k in keywords) or st in {
        "grades",
        "gpa",
        "cgpa",
        "result",
        "성적",
        "학점",
    }


def _is_personal_query(message: str, search_term: Optional[str]) -> bool:
    q = (message or "").lower()
    st = (search_term or "").lower()
    personal_patterns = [
        "my grade",
        "my gpa",
        "my result",
        "my profile",
        "my information",
        "my info",
        "my id",
        "my nationality",
        "my advisor",
        "my adviser",
        "my major",
        "my programme",
        "my program",
        "where am i from",
        "what is my nationality",
        "what's my nationality",
        "who is my advisor",
        "who is my adviser",
        "what is my major",
        "what's my major",
        "who am i",
        "내 정보",
        "내 프로필",
        "내 성적",
        "내 학점",
        "내 점수",
        "내 gpa",
        "내 국적",
        "내 전공",
        "내 학번",
        "나는 누구",
        "내 지도교수",
    ]
    if st in {
        "self",
        "my",
        "profile",
        "nationality",
        "advisor",
        "adviser",
        "major",
        "programme",
        "program",
        "내 정보",
        "내 성적",
        "국적",
        "전공",
        "학번",
    }:
        return True
    return any(p in q for p in personal_patterns)


def _normalize_suggestions(items: Any, limit: int = 3) -> List[str]:
    if not isinstance(items, list):
        return []
    out: List[str] = []
    seen = set()
    for item in items:
        text = re.sub(r"\s+", " ", str(item or "").strip())
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
        if len(out) >= max(1, int(limit)):
            break
    return out


def _has_ucsi_context(message: str) -> bool:
    q = (message or "").strip().lower()
    if not q:
        return False
    hints = [
        "ucsi",
        "university",
        "campus",
        "faculty",
        "school",
        "student",
        "staff",
        "lecturer",
        "professor",
        "dean",
        "advisor",
        "adviser",
        "programme",
        "program",
        "hostel",
        "tuition",
        "fee",
        "block",
        "building",
        "학교",
        "대학",
        "캠퍼스",
        "기숙사",
        "등록금",
        "학과",
        "교수",
        "직원",
    ]
    return any(_contains_token(q, token) for token in hints)


def _extract_person_candidate(message: str) -> Optional[str]:
    text = str(message or "").strip()
    if not text:
        return None

    patterns = [
        r"^\s*who is\s+(?P<name>.+?)\s*\??\s*$",
        r"^\s*who's\s+(?P<name>.+?)\s*\??\s*$",
        r"^\s*do you know\s+(?P<name>.+?)\s*\??\s*$",
        r"^\s*tell me about\s+(?P<name>.+?)\s*\??\s*$",
        r"^\s*tell me more about\s+(?P<name>.+?)\s*\??\s*$",
        r"^\s*what do you know about\s+(?P<name>.+?)\s*\??\s*$",
        r"^\s*(?P<name>[A-Za-z0-9가-힣.\-\'\s]+?)\s*(?:에 대해|에대해|에 대해서|에대해서|관련해서|에 관한)\s*(?:정보를\s*)?(?:알려줘|알려줄래|알려주세요|말해줘|말해줄래|설명해줘|소개해줘)?\s*\??\s*$",
        r"^\s*(?P<name>[A-Za-z0-9가-힣.\-\'\s]+?)\s*(?:누구야|누구예요|누군가요)\s*\??\s*$",
        r"^\s*(?P<name>[A-Za-z0-9가-힣.\-\'\s]+?)\s*(?:알아|알고 있어|알고 있니)\s*\??\s*$",
    ]

    fuzzy_patterns = [
        r"(?:about|regarding|on)\s+(?P<name>[A-Za-z][A-Za-z0-9 .'\-]{1,60})",
        r"(?P<name>[A-Za-z0-9가-힣.\-\'\s]{2,60})\s*(?:이라는|라는)\s*(?:사람|인물)?\s*(?:에 대해|에 대해서|관련해서|에 관한)",
    ]

    candidate = None
    for pattern in patterns:
        m = re.match(pattern, text, flags=re.IGNORECASE)
        if m:
            candidate = m.group("name")
            break

    if not candidate:
        for pattern in fuzzy_patterns:
            m = re.search(pattern, text, flags=re.IGNORECASE)
            if m:
                candidate = m.group("name")
                break
    if not candidate:
        return None

    candidate = re.sub(r"\s+", " ", str(candidate).strip())
    candidate = candidate.strip(" \t\r\n?!.,\"'`")
    candidate = re.sub(r"^(the|a|an)\s+", "", candidate, flags=re.IGNORECASE)
    candidate = re.sub(r"\s*(?:이라는|라는)\s*(?:사람|인물)?$", "", candidate, flags=re.IGNORECASE)
    candidate = re.sub(r"\s*(?:please|pls)$", "", candidate, flags=re.IGNORECASE)
    candidate = re.sub(r"(?:은|는|이|가|을|를|와|과|의)$", "", candidate)
    candidate = re.sub(r"\s+", " ", candidate).strip()
    if len(candidate) < 2:
        return None
    if len(candidate.split()) > 10:
        return None

    lowered = candidate.lower()
    reject_fragments = {
        "ucsi",
        "university",
        "hostel",
        "tuition",
        "fee",
        "fees",
        "block",
        "building",
        "campus",
        "faculty",
        "department",
        "program",
        "programme",
        "schedule",
        "gpa",
        "cgpa",
        "student id",
        "기숙사",
        "등록금",
        "전공",
        "학과",
        "학부",
        "프로그램",
        "시설",
        "도서관",
        "일정",
        "입학",
        "장학금",
        "캠퍼스",
        "교과",
        "학점",
        "성적",
    }
    if any(fragment in lowered for fragment in reject_fragments):
        return None

    return candidate


def _infer_preferred_labels(message: str, search_term: Optional[str]) -> List[str]:
    q = f"{message or ''} {search_term or ''}".lower()
    labels: List[str] = []

    def add_if_missing(label: str):
        if label not in labels:
            labels.append(label)

    if any(k in q for k in ["hostel", "dorm", "accommodation", "rent", "deposit", "room", "기숙사", "숙소", "룸", "보증금"]):
        add_if_missing("Hostel")
    if any(k in q for k in ["hostel faq", "refund", "installment", "policy"]):
        add_if_missing("HostelFAQ")
    if any(k in q for k in ["기숙사 환불", "분할 납부", "기숙사 정책"]):
        add_if_missing("HostelFAQ")
    if any(k in q for k in ["library", "gym", "cafeteria", "facility", "printer", "laundry", "prayer"]):
        add_if_missing("Facility")
    if any(k in q for k in ["도서관", "버스", "체육관", "시설", "프린터", "세탁", "기도실"]):
        add_if_missing("Facility")
    if any(k in q for k in ["schedule", "calendar", "event", "semester", "intake", "deadline"]):
        add_if_missing("Schedule")
    if any(k in q for k in ["학사일정", "일정", "학기", "입학시기", "마감"]):
        add_if_missing("Schedule")
    if any(
        k in q
        for k in [
            "programme",
            "program",
            "major",
            "course",
            "tuition",
            "fee",
            "scholarship",
            "faculty",
            "diploma",
            "foundation",
            "bachelor",
            "master",
            "phd",
            "medicine",
            "health sciences",
            "nursing",
            "pharmacy",
            "engineering",
            "business",
            "computer science",
        ]
    ):
        add_if_missing("Programme")
    if any(k in q for k in ["전공", "학과", "학부", "프로그램", "등록금", "입학", "의학", "보건", "간호", "약학", "공학", "경영"]):
        add_if_missing("Programme")
    if any(k in q for k in ["staff", "lecturer", "professor", "dean", "chancellor", "advisor"]):
        add_if_missing("Staff")
    if any(k in q for k in ["교수", "강사", "학장", "총장", "부총장", "직원", "지도교수"]):
        add_if_missing("Staff")
    if any(k in q for k in ["block", "building", "campus address", "where is block", "map"]):
        add_if_missing("CampusBlocks")
    if any(k in q for k in ["블록", "건물", "캠퍼스 위치", "지도", "어디"]):
        add_if_missing("CampusBlocks")

    return labels


def _looks_like_ucsi_domain_info_query(message: str) -> bool:
    q = str(message or "").strip().lower()
    if not q:
        return False

    info_patterns = [
        r"\btell me about\b",
        r"\binformation about\b",
        r"\bdetails about\b",
        r"에 대한 정보",
        r"정보를 알려줘",
        r"설명해줘",
    ]
    has_info_request = any(re.search(p, q) for p in info_patterns)

    domain_tokens = [
        "medicine",
        "health sciences",
        "nursing",
        "pharmacy",
        "engineering",
        "business",
        "computer science",
        "faculty",
        "foundation",
        "diploma",
        "bachelor",
        "master",
        "phd",
        "의학",
        "보건",
        "간호",
        "약학",
        "공학",
        "경영",
        "학부",
        "학과",
        "전공",
    ]
    has_domain_hint = any(token in q for token in domain_tokens)
    return has_info_request and has_domain_hint


def _extract_rag_meta(rag_result: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    result = rag_result or {}
    confidence = 0.0
    try:
        confidence = float(result.get("confidence") or 0.0)
    except Exception:
        confidence = 0.0
    sources = result.get("sources")
    if not isinstance(sources, list):
        sources = []

    return {
        "context": str(result.get("context") or ""),
        "has_relevant_data": bool(result.get("has_relevant_data")),
        "confidence": max(0.0, min(confidence, 1.2)),
        "sources": [str(s) for s in sources[:8]],
    }


def _should_force_rag(message: str) -> bool:
    q = (message or "").strip().lower()
    if not q:
        return False
    if _is_personal_query(q, None):
        return True
    if _infer_preferred_labels(q, None):
        return True
    if _looks_like_ucsi_domain_info_query(q):
        return True
    return any(_contains_token(q, kw) for kw in Config.RAG_FORCE_KEYWORDS)


def _compose_no_data_response(lang: str = "en") -> str:
    if lang == "ko":
        return (
            "현재 UCSI 지식베이스에서 관련 정보를 찾지 못했어요. "
            "프로그램명, 블록명, 입학 시기 등 구체적인 키워드로 다시 질문해 주세요."
        )
    return (
        "I could not find reliable information in the current UCSI knowledge base. "
        "Please ask with specific keywords (programme name, block, intake, staff role)."
    )


def _is_document_limited_answer(text: str) -> bool:
    value = str(text or "").lower()
    if not value:
        return False
    patterns = [
        "provided document",
        "provided documents",
        "knowledge base",
        "cannot find",
        "could not find",
        "in our database",
        "제공된 문서",
        "찾을 수 없습니다",
        "데이터베이스에서",
    ]
    return any(token in value for token in patterns)


def _detect_language(text: str) -> str:
    content = str(text or "").strip()
    if not content:
        return "en"

    korean_count = 0
    chinese_count = 0
    english_count = 0
    for ch in content:
        code = ord(ch)
        if (0xAC00 <= code <= 0xD7A3) or (0x1100 <= code <= 0x11FF):
            korean_count += 1
        elif (0x4E00 <= code <= 0x9FFF) or (0x3400 <= code <= 0x4DBF):
            chinese_count += 1
        elif ch.isalpha() and code < 128:
            english_count += 1

    if korean_count > chinese_count and korean_count > english_count * 0.3:
        return "ko"
    if chinese_count > korean_count and chinese_count > english_count * 0.3:
        return "zh"
    return "en"


def _is_capability_smalltalk_query(message: str) -> bool:
    q = str(message or "").strip().lower()
    q_compact = re.sub(r"\s+", "", q)
    if not q:
        return False
    if _is_personal_query(q, None) or _has_ucsi_context(q):
        return False

    english_pattern = (
        r"\b(can|could|do|will|would)\s+you\s+"
        r"(please\s+)?(?:(do|perform|try)\s+)?(a\s+)?"
        r"(dance|sing|jump|run|swim|stand|crawl|roll|fly|handstand)\b"
    )
    if re.search(english_pattern, q):
        return True
    if "handstand" in q:
        return True
    if "물구나무" in q_compact:
        return True

    ko_physical_stems = [
        "물구나무",
        "춤",
        "노래",
        "점프",
        "달려",
        "수영",
        "기어",
        "구르",
    ]
    ko_request_tokens = ["해", "해줘", "해봐", "해줄래", "가능해", "할수있어", "해라", "해볼래"]
    return any(stem in q_compact for stem in ko_physical_stems) and any(
        token in q_compact for token in ko_request_tokens
    )


def _capability_smalltalk_response(message: str) -> str:
    q = str(message or "").lower().strip()
    lang = _detect_language(message)
    is_handstand = ("handstand" in q) or ("물구나무" in q)

    # Greeting detection — hi, hello, hey, etc.
    greeting_tokens = {
        "hi", "hello", "hey", "hii", "hiii", "yo", "sup",
        "good morning", "good afternoon", "good evening", "good night",
        "안녕", "안녕하세요", "하이", "헬로", "반가워", "반갑습니다",
        "야", "이봐", "저기", "저기요", "ㅎㅇ", "ㅎㅎ", "ㅋㅋ",
        "하잉", "방가", "방가워",
    }
    q_stripped = re.sub(r"[!?.~,]+$", "", q).strip()
    is_greeting = q_stripped in greeting_tokens or any(q_stripped.startswith(g) for g in greeting_tokens if len(g) > 2)

    if is_greeting:
        if lang == "ko":
            return (
                "안녕하세요! 저는 UCSI Buddy예요 👋\n\n"
                "UCSI 대학교에 대해 궁금한 건 뭐든 물어보세요!\n"
                "프로그램, 기숙사, 시설, 학사 일정, 교직원 정보 등을 도와드릴 수 있어요."
            )
        return (
            "Hello! I'm UCSI Buddy 👋\n\n"
            "Feel free to ask me anything about UCSI University!\n"
            "I can help with programmes, hostel, facilities, schedules, staff info, and more."
        )

    # "What can you do" / "뭘 해줄 수 있어" type questions
    is_what_can = any(kw in q for kw in [
        "what can you", "what do you do", "how can you help",
        "what are you", "who are you", "help me",
        "뭘 해", "뭐 해", "무엇을 해", "도와", "도움",
        "할 수 있", "해줄 수", "뭐야", "누구야", "누구니",
    ])

    if is_what_can:
        if lang == "ko":
            return (
                "안녕하세요! 저는 UCSI Buddy예요. 이런 것들을 도와드릴 수 있어요:\n\n"
                "- UCSI 프로그램, 등록금, 입학 정보 안내\n"
                "- 기숙사 비용, 시설 정보\n"
                "- 캠퍼스 건물 위치, 지도\n"
                "- 교수/직원 정보\n"
                "- 학사 일정, 시험 일정\n"
                "- 로그인 후 내 성적, 프로필 조회\n\n"
                "궁금한 게 있으면 편하게 물어보세요!"
            )
        return (
            "Hi! I'm UCSI Buddy. I can help you with:\n\n"
            "- UCSI programmes, tuition fees, and admissions\n"
            "- Hostel fees and facilities\n"
            "- Campus building locations and maps\n"
            "- Staff and lecturer information\n"
            "- Academic schedules and exam dates\n"
            "- Your grades and profile (after login)\n\n"
            "Feel free to ask me anything!"
        )

    if lang == "ko":
        if is_handstand:
            return "저는 물리적인 몸이 없어서 물구나무를 설 수는 없어요. 대신 질문에는 정확하고 빠르게 답할 수 있어요."
        return "저는 실제 동작을 수행할 수는 없지만, 필요한 정보를 정확하게 정리해 드릴 수 있어요."

    if is_handstand:
        return "I do not have a physical body, so I cannot do a handstand. But I can answer your questions clearly."
    return "I cannot perform physical actions, but I can provide clear and accurate answers."


def _safe_text_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return re.sub(r"\s+", " ", value).strip()
    if isinstance(value, (dict, list)):
        try:
            return json.dumps(value, ensure_ascii=False)
        except Exception:
            return str(value)
    return str(value).strip()


def _pick_first_value(record: Dict[str, Any], keys: List[str]) -> str:
    for key in keys:
        if key in record:
            value = _safe_text_value(record.get(key))
            if value:
                return value
    return ""


def _requested_personal_fields(message: str, search_term: Optional[str]) -> Optional[set]:
    q = f"{message or ''} {search_term or ''}".lower()
    selected = set()

    if any(k in q for k in ["student number", "student id", "my id", "학번", "학생번호"]):
        selected.add("student_number")
    if any(k in q for k in ["my name", "who am i", "이름", "내 이름"]):
        selected.add("student_name")
    if any(k in q for k in ["nationality", "where am i from", "국적"]):
        selected.add("nationality")
    if any(k in q for k in ["gender", "성별"]):
        selected.add("gender")
    if any(k in q for k in ["programme", "program", "major", "전공", "학과"]):
        selected.add("programme")
    if any(k in q for k in ["status", "profile status", "상태"]):
        selected.add("profile_status")
    if any(k in q for k in ["intake", "입학"]):
        selected.add("intake")
    if any(k in q for k in ["birth", "birthday", "dob", "생년월일", "생일"]):
        selected.add("dob")
    if any(k in q for k in ["department", "faculty", "학부", "학과"]):
        selected.add("department")
    if any(k in q for k in ["gpa", "cgpa", "grade", "성적", "학점", "평점"]):
        selected.add("gpa")
    if any(k in q for k in ["advisor", "adviser", "지도교수"]):
        selected.add("advisor")

    return selected or None


def _format_personal_info(
    student_data: Dict[str, Any],
    message: str,
    search_term: Optional[str],
    allow_sensitive: bool = True,
) -> str:
    lang = _detect_language(message)
    requested = _requested_personal_fields(message, search_term)
    sensitive_hidden = False

    fields: List[Dict[str, Any]] = [
        {
            "id": "student_number",
            "label_en": "Student Number",
            "label_ko": "학번",
            "keys": ["STUDENT_NUMBER", "student_number"],
        },
        {
            "id": "student_name",
            "label_en": "Student Name",
            "label_ko": "이름",
            "keys": ["STUDENT_NAME", "NAME", "name"],
        },
        {
            "id": "nationality",
            "label_en": "Nationality",
            "label_ko": "국적",
            "keys": ["NATIONALITY", "nationality"],
        },
        {
            "id": "gender",
            "label_en": "Gender",
            "label_ko": "성별",
            "keys": ["GENDER", "gender"],
        },
        {
            "id": "programme",
            "label_en": "Programme",
            "label_ko": "전공/프로그램",
            "keys": [
                "PROGRAMME_NAME",
                "PROGRAMME",
                "PROGRAM_NAME",
                "MAJOR",
                "programme",
                "program",
                "major",
            ],
        },
        {
            "id": "profile_status",
            "label_en": "Profile Status",
            "label_ko": "상태",
            "keys": ["PROFILE_STATUS", "STATUS", "profile_status", "status"],
        },
        {
            "id": "intake",
            "label_en": "Intake",
            "label_ko": "입학 시기",
            "keys": ["INTAKE", "ADMISSION_INTAKE", "intake"],
        },
        {
            "id": "dob",
            "label_en": "Date of Birth",
            "label_ko": "생년월일",
            "keys": ["DATE_OF_BIRTH", "DOB", "BIRTH_DATE", "dob"],
        },
        {
            "id": "department",
            "label_en": "Department",
            "label_ko": "학과",
            "keys": ["DEPARTMENT", "DEPARTMENT_NAME", "FACULTY", "department", "faculty"],
        },
        {
            "id": "gpa",
            "label_en": "GPA",
            "label_ko": "GPA",
            "keys": ["GPA", "CGPA", "gpa", "cgpa"],
        },
        {
            "id": "advisor",
            "label_en": "Advisor",
            "label_ko": "지도교수",
            "keys": ["ADVISOR", "ADVISER", "advisor", "adviser"],
        },
    ]

    # Emoji icons for each field for better visual presentation
    field_icons = {
        "student_number": "🆔",
        "student_name": "👤",
        "nationality": "🌐",
        "gender": "⚧",
        "programme": "📚",
        "profile_status": "📋",
        "intake": "📅",
        "dob": "🎂",
        "department": "🏛",
        "gpa": "📊",
        "advisor": "👨‍🏫",
    }

    lines: List[str] = []
    for field in fields:
        if field["id"] == "gpa" and not allow_sensitive:
            if requested is None or field["id"] in requested:
                sensitive_hidden = True
            continue
        if requested and field["id"] not in requested:
            continue
        value = _pick_first_value(student_data, field["keys"])
        if not value:
            if requested and field["id"] in requested:
                label = field["label_ko"] if lang == "ko" else field["label_en"]
                missing = "정보 없음" if lang == "ko" else "Not available"
                icon = field_icons.get(field["id"], "")
                lines.append(f"{icon} {label}: {missing}")
            continue
        label = field["label_ko"] if lang == "ko" else field["label_en"]
        icon = field_icons.get(field["id"], "")
        lines.append(f"{icon} {label}: {value}")

    if not lines:
        if sensitive_hidden:
            if lang == "ko":
                return "🔒 GPA/성적 정보는 비밀번호 인증 후에 확인할 수 있어요."
            return "🔒 GPA/grade information is available after password verification."
        if lang == "ko":
            return "요청하신 학생 정보를 찾지 못했어요."
        return "I could not find your student profile details."

    header = "📋 학생 프로필 정보" if lang == "ko" else "📋 Student Profile"
    text = header + "\n\n" + "\n".join(lines)
    if sensitive_hidden:
        if lang == "ko":
            text += "\n\n🔒 GPA/성적 정보는 비밀번호 인증 후에 제공됩니다."
        else:
            text += "\n\n🔒 GPA/grade details are shown after password verification."
    return text


def _personal_info_suggestions(lang: str, allow_sensitive: bool = True) -> List[str]:
    if lang == "ko":
        if allow_sensitive:
            return ["내 GPA만 보여줘", "내 국적 알려줘", "내 지도교수가 누구야?"]
        return ["내 국적 알려줘", "내 전공 알려줘", "내 지도교수가 누구야?"]
    if allow_sensitive:
        return ["Show only my GPA", "What is my nationality?", "Who is my advisor?"]
    return ["What is my nationality?", "What is my programme?", "Who is my advisor?"]


def _capability_suggestions(lang: str) -> List[str]:
    if lang == "ko":
        return ["내 정보 보여줘", "UCSI 기숙사 정보 알려줘", "UCSI 등록금 정보 알려줘"]
    return ["Show my profile", "Tell me about UCSI hostel", "Tell me about UCSI tuition fees"]


def _extract_suggestion_tokens(text: str) -> List[str]:
    source = str(text or "").lower()
    if not source:
        return []

    raw_tokens = re.findall(r"[a-z0-9]{2,}|[가-힣]{2,}", source)
    en_stop = {
        "what",
        "where",
        "who",
        "when",
        "how",
        "why",
        "is",
        "are",
        "the",
        "a",
        "an",
        "to",
        "for",
        "of",
        "in",
        "on",
        "about",
        "please",
        "tell",
        "show",
        "me",
        "my",
        "can",
        "you",
    }
    ko_stop = {
        "알려줘",
        "알려",
        "말해줘",
        "말해",
        "뭐야",
        "무엇",
        "어디",
        "어떻게",
        "누구",
        "왜",
        "좀",
        "해줘",
        "해",
        "있어",
    }

    out: List[str] = []
    for tok in raw_tokens:
        if re.search(r"[a-z]", tok):
            if tok in en_stop:
                continue
        elif tok in ko_stop:
            continue
        out.append(tok)
    return out


def _infer_suggestion_bucket(
    *,
    user_message: str,
    search_term: Optional[str],
    retrieval_meta: Dict[str, Any],
    is_personal: bool,
    person_resolution: Optional[Dict[str, Any]],
) -> str:
    q = f"{user_message or ''} {search_term or ''}".lower()
    route = str((retrieval_meta or {}).get("route") or "")
    labels = retrieval_meta.get("preferred_labels") if isinstance(retrieval_meta, dict) else []
    labels = {str(x) for x in labels} if isinstance(labels, list) else set()
    match_type = str((person_resolution or {}).get("match_type") or "")

    if route == "capability_smalltalk":
        return "capability"
    if is_personal:
        if _is_grade_query(user_message, search_term):
            return "personal_grade"
        return "personal_profile"
    if match_type == "general_person":
        return "general_person"
    if match_type == "db_staff_match" or "Staff" in labels:
        return "staff"
    if "Hostel" in labels or any(k in q for k in ["hostel", "dorm", "accommodation", "기숙사"]):
        return "hostel"
    if "Facility" in labels or any(k in q for k in ["library", "gym", "printer", "facility", "시설"]):
        return "facility"
    if "Schedule" in labels or any(k in q for k in ["schedule", "calendar", "semester", "intake", "일정"]):
        return "schedule"
    if "Programme" in labels or any(
        k in q for k in ["programme", "program", "major", "course", "tuition", "fee", "전공", "학과", "등록금"]
    ):
        return "programme"
    if "CampusBlocks" in labels or any(k in q for k in ["block", "building", "map", "캠퍼스", "건물"]):
        return "campus_blocks"

    confidence = 0.0
    try:
        confidence = float((retrieval_meta or {}).get("confidence") or 0.0)
    except Exception:
        confidence = 0.0
    if route in {"rag", "planner_rag"} and confidence < 0.45:
        return "rag_no_data"
    if not _has_ucsi_context(user_message):
        return "general_world"
    return "general_ucsi"


def _bucket_templates(
    *,
    bucket: str,
    lang: str,
    person_resolution: Optional[Dict[str, Any]],
) -> List[str]:
    candidate = str((person_resolution or {}).get("candidate") or "").strip()

    if lang == "ko":
        templates = {
            "capability": ["내 정보 보여줘", "UCSI 프로그램 추천해줘", "UCSI 기숙사 정보 알려줘"],
            "personal_profile": ["내 국적 알려줘", "내 전공 알려줘", "내 지도교수가 누구야?"],
            "personal_grade": ["내 GPA와 CGPA 보여줘", "최근 성적 알려줘", "내 학번도 함께 보여줘"],
            "hostel": ["기숙사 비용 알려줘", "기숙사 보증금은 얼마야?", "기숙사 분할납부 가능해?"],
            "facility": ["도서관 위치 알려줘", "캠퍼스에 체육관 있어?", "프린터는 어디에 있어?"],
            "schedule": ["다음 학기 시작일 알려줘", "주요 학사 일정 알려줘", "시험 기간은 언제야?"],
            "programme": ["이 전공 등록금 알려줘", "입학 조건 알려줘", "어느 학부에서 운영해?"],
            "staff": ["이 교수의 역할이 뭐야?", "이 사람 연락처 알려줘", "해당 학부 학장은 누구야?"],
            "campus_blocks": ["Block A는 어디야?", "Block B는 어떻게 가?", "메인 오피스는 어느 블록이야?"],
            "general_person": ["대표작이 뭐야?", "최근 활동이 뭐야?", "언제 데뷔했어?"],
            "rag_no_data": ["정확한 전공명으로 다시 물어볼게", "건물명/블록명을 넣어서 물어볼게", "직책과 학부를 같이 넣어 물어볼게"],
            "general_world": ["머신러닝 쉽게 설명해줘", "말레이시아 수도가 어디야?", "파이썬이 뭐야?"],
            "general_ucsi": ["UCSI 프로그램 정보 알려줘", "캠퍼스 시설 알려줘", "등록금 구조 설명해줘"],
        }
    else:
        templates = {
            "capability": ["Show my profile", "Recommend a UCSI programme", "Tell me about UCSI hostel"],
            "personal_profile": ["What is my nationality?", "What is my programme?", "Who is my advisor?"],
            "personal_grade": ["Show my GPA and CGPA", "What is my latest result?", "Show my student number too"],
            "hostel": ["What are the hostel fees?", "How much is the hostel deposit?", "Can I pay hostel by installment?"],
            "facility": ["Where is the library?", "Is there a gym on campus?", "Where can I print documents?"],
            "schedule": ["When does the next semester start?", "What are the intake dates?", "When is the exam period?"],
            "programme": ["What is the tuition fee for this programme?", "What are the entry requirements?", "Which faculty offers it?"],
            "staff": ["What is this staff member's role?", "How can I contact this person?", "Who is the dean of this faculty?"],
            "campus_blocks": ["Where is Block A?", "How do I get to Block B?", "Which block has the main office?"],
            "general_person": ["What is this person's most well-known work?", "What are this person's recent activities?", "When did this person debut?"],
            "rag_no_data": ["Include the exact programme name", "Ask with block/building name", "Include staff role and faculty"],
            "general_world": ["Explain machine learning simply", "What is the capital of Malaysia?", "What is Python used for?"],
            "general_ucsi": ["Tell me about UCSI programmes", "Show campus facilities", "Explain tuition fee structure"],
        }

    picked = list(templates.get(bucket, templates.get("general_ucsi", [])))
    if bucket == "general_person" and candidate:
        if lang == "ko":
            picked.insert(0, f"{candidate}의 대표작은 뭐야?")
            picked.insert(1, f"{candidate}의 최근 활동 알려줘")
        else:
            picked.insert(0, f"What is {candidate}'s most well-known work?")
            picked.insert(1, f"What has {candidate} been doing recently?")
    return picked


def _generic_suggestion_fallback(lang: str) -> List[str]:
    if lang == "ko":
        return ["UCSI 기숙사 정보 알려줘", "UCSI 등록금 알려줘", "말레이시아 유학 관련 정보 알려줘"]
    return ["Tell me about UCSI hostel", "What are the tuition fees?", "Any tips for studying in Malaysia?"]


def _suggestion_score(
    *,
    suggestion: str,
    user_tokens: set,
    lang: str,
    bucket: str,
    candidate_index: int,
) -> float:
    text = str(suggestion or "").strip()
    if not text:
        return -999.0

    tokens = set(_extract_suggestion_tokens(text))
    overlap = len(tokens.intersection(user_tokens))
    score = float(overlap * 4)

    # Keep earlier candidates slightly preferred when scores tie.
    score += max(0.0, 2.0 - (candidate_index * 0.12))

    if len(text) < 6 or len(text) > 95:
        score -= 1.2

    sl = _detect_language(text)
    if lang == "ko" and sl != "ko":
        score -= 1.2
    if lang != "ko" and sl == "ko":
        score -= 1.2

    if bucket in {"personal_profile", "personal_grade"} and (
        ("my " in text.lower()) or ("내 " in text) or text.startswith("내")
    ):
        score += 1.0
    return score


def _is_redundant_person_suggestion(
    suggestion: str,
    user_message: str,
    candidate: str,
) -> bool:
    s = str(suggestion or "").strip().lower()
    u = str(user_message or "").strip().lower()
    c = str(candidate or "").strip().lower()
    if not s:
        return True
    if s == u:
        return True
    if not c:
        return False

    repetitive_patterns = [
        rf"^who is\s+{re.escape(c)}\??$",
        rf"^who's\s+{re.escape(c)}\??$",
        rf"^tell me about\s+{re.escape(c)}\??$",
        rf"^tell me more about\s+{re.escape(c)}\??$",
        rf"^{re.escape(c)}\s*(?:누구야|누구예요|누군가요)\??$",
        rf"^{re.escape(c)}\s*(?:에 대해|에대해|에 대해서|에대해서|관련해서|에 관한)\s*(?:정보를\s*)?(?:알려줘|알려줄래|알려주세요|말해줘|말해줄래|설명해줘|소개해줘)?\??$",
    ]
    return any(re.match(p, s, flags=re.IGNORECASE) for p in repetitive_patterns)


def _build_suggestions(
    *,
    user_message: str,
    user_lang: str,
    retrieval_meta: Dict[str, Any],
    ai_suggestions: Any,
    is_personal: bool,
    search_term: Optional[str],
    person_resolution: Optional[Dict[str, Any]],
    limit: int = 3,
) -> List[str]:
    bucket = _infer_suggestion_bucket(
        user_message=user_message,
        search_term=search_term,
        retrieval_meta=retrieval_meta,
        is_personal=is_personal,
        person_resolution=person_resolution,
    )
    candidate = str((person_resolution or {}).get("candidate") or "").strip()

    candidates: List[str] = []
    candidates.extend(_normalize_suggestions(ai_suggestions, limit=8))
    candidates.extend(
        _bucket_templates(bucket=bucket, lang=user_lang, person_resolution=person_resolution)
    )
    candidates.extend(_generic_suggestion_fallback(user_lang))

    user_key = re.sub(r"\s+", " ", str(user_message or "").lower()).strip(" ?!.,")
    user_tokens = set(_extract_suggestion_tokens(user_message))

    ranked: List[tuple] = []
    seen = set()
    for idx, raw in enumerate(candidates):
        text = re.sub(r"\s+", " ", str(raw or "").strip())
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        if key == user_key:
            continue
        if bucket == "general_person" and _is_redundant_person_suggestion(
            suggestion=text,
            user_message=user_message,
            candidate=candidate,
        ):
            continue
        score = _suggestion_score(
            suggestion=text,
            user_tokens=user_tokens,
            lang=user_lang,
            bucket=bucket,
            candidate_index=idx,
        )
        ranked.append((score, idx, text))

    ranked.sort(key=lambda x: (-x[0], x[1]))
    out = [text for _, _, text in ranked[: max(1, int(limit))]]
    return out


