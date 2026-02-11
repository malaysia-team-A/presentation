"""
Response Validator for UCSI Buddy Chatbot

Prevents hallucination by:
1. Source citation - adding references to responses
2. Number verification - checking amounts against DB
3. Grounding enforcement - ensuring claims match context
4. Confidence-based filtering - rejecting low-confidence answers
"""

import re
from typing import Any, Dict, List, Optional, Tuple


# =============================================================================
# CONFIGURATION
# =============================================================================

# Minimum confidence to trust a response
MIN_CONFIDENCE_THRESHOLD = 0.55

# Keywords that require strict verification
VERIFICATION_KEYWORDS = {
    # Amounts/Prices
    "rm", "usd", "dollar", "ringgit", "fee", "price", "cost", "tuition",
    "deposit", "payment", "refund", "scholarship",
    # Korean
    "원", "달러", "링깃", "비용", "가격", "등록금", "보증금", "장학금", "환불",
    # Numbers
    "percent", "percentage", "%", "퍼센트",
}

# Patterns that indicate potential hallucination
HALLUCINATION_PATTERNS = [
    r"(?:i think|i believe|probably|maybe|might be|could be)",
    r"(?:일반적으로|아마|보통|추정)",
    r"(?:typically|usually|often|sometimes)",
    r"(?:around|about|approximately)\s+\d+",
]

# No-data response templates
NO_DATA_RESPONSES = {
    "en": (
        "I could not find verified information about this in the UCSI knowledge base. "
        "Please contact the relevant department for accurate details."
    ),
    "ko": (
        "UCSI 지식베이스에서 검증된 정보를 찾지 못했습니다. "
        "정확한 내용은 해당 부서에 문의해 주세요."
    ),
}


# =============================================================================
# SOURCE CITATION
# =============================================================================

def add_source_citation(
    response_text: str,
    sources: List[str],
    language: str = "en",
) -> str:
    """
    Add source citation to response.

    Example:
        "The hostel fee is RM 450."
        "The hostel fee is RM 450. [Source: Hostel]"
    """
    if not response_text or not sources:
        return response_text

    # Clean and deduplicate sources
    clean_sources = []
    seen = set()
    for src in sources:
        # Extract collection name from source string
        name = str(src).strip()
        if ":" in name:
            name = name.split(":")[-1].strip()
        if name and name.lower() not in seen:
            seen.add(name.lower())
            clean_sources.append(name)

    if not clean_sources:
        return response_text

    # Format citation
    if len(clean_sources) == 1:
        citation = f"[Source: {clean_sources[0]}]"
    else:
        citation = f"[Sources: {', '.join(clean_sources[:3])}]"

    # Add citation at the end
    text = response_text.rstrip()

    # Don't add if already has citation
    if "[Source" in text or "[출처" in text:
        return response_text

    # Add appropriate punctuation
    if not text.endswith((".", "!", "?", "。")):
        text += "."

    if language == "ko":
        citation = citation.replace("Sources", "출처").replace("Source", "출처")

    return f"{text} {citation}"


# =============================================================================
# NUMBER VERIFICATION
# =============================================================================

def extract_numbers_from_text(text: str) -> List[Dict[str, Any]]:
    """
    Extract numbers and amounts from text.

    Returns list of:
        {"value": 450, "currency": "RM", "context": "fee is RM 450"}
    """
    results = []

    # Currency patterns
    patterns = [
        # RM 450, RM450, RM 1,500
        (r"RM\s*([\d,]+(?:\.\d{2})?)", "RM"),
        # $450, $ 450
        (r"\$\s*([\d,]+(?:\.\d{2})?)", "USD"),
        # 450 KRW, 1,500 KRW
        (r"([\d,]+)\s*(?:KRW|won)", "KRW"),
        # Percentages
        (r"([\d.]+)\s*%", "%"),
        (r"([\d.]+)\s*(?:percent|percentage)", "%"),
    ]

    for pattern, currency in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            value_str = match.group(1).replace(",", "")
            try:
                value = float(value_str)
                # Get surrounding context
                start = max(0, match.start() - 30)
                end = min(len(text), match.end() + 30)
                context = text[start:end].strip()

                results.append({
                    "value": value,
                    "currency": currency,
                    "context": context,
                    "match": match.group(0),
                })
            except ValueError:
                continue

    return results


def verify_numbers_against_context(
    response_text: str,
    context_text: str,
) -> Tuple[bool, List[str]]:
    """
    Verify that numbers in response match those in context.

    Returns:
        (is_valid, list of issues)
    """
    if not response_text or not context_text:
        return True, []

    response_numbers = extract_numbers_from_text(response_text)
    context_numbers = extract_numbers_from_text(context_text)

    if not response_numbers:
        return True, []

    issues = []
    context_values = {(n["value"], n["currency"]) for n in context_numbers}

    for num in response_numbers:
        key = (num["value"], num["currency"])

        # Check if this number exists in context
        if key not in context_values:
            # Allow small tolerance for rounding
            found = False
            for cv, cc in context_values:
                if cc == num["currency"] and abs(cv - num["value"]) / max(cv, 1) < 0.05:
                    found = True
                    break

            if not found and num["currency"] != "%":
                issues.append(
                    f"Number {num['match']} not found in source data"
                )

    return len(issues) == 0, issues


# =============================================================================
# HALLUCINATION DETECTION
# =============================================================================

def detect_hallucination_patterns(text: str) -> List[str]:
    """
    Detect patterns that might indicate hallucination.
    """
    warnings = []
    text_lower = text.lower()

    for pattern in HALLUCINATION_PATTERNS:
        if re.search(pattern, text_lower):
            match = re.search(pattern, text_lower)
            if match:
                warnings.append(f"Uncertain language detected: '{match.group()}'")

    return warnings


def check_grounding(
    response_text: str,
    context_text: str,
    strict_mode: bool = False,
) -> Tuple[bool, List[str]]:
    """
    Check if response is properly grounded in context.

    In strict mode, any uncertain language or unverified claims will fail.
    """
    issues = []

    # Check for hallucination patterns
    hall_warnings = detect_hallucination_patterns(response_text)
    if hall_warnings:
        issues.extend(hall_warnings)

    # Verify numbers
    nums_valid, num_issues = verify_numbers_against_context(response_text, context_text)
    if not nums_valid:
        issues.extend(num_issues)

    # In strict mode, any issue is a failure
    if strict_mode:
        return len(issues) == 0, issues

    # In normal mode, only critical issues fail
    critical_issues = [i for i in issues if "Number" in i]
    return len(critical_issues) == 0, issues


# =============================================================================
# RESPONSE VALIDATION
# =============================================================================

class ResponseValidator:
    """
    Validates and enhances LLM responses to prevent hallucination.
    """

    def __init__(self):
        self.min_confidence = MIN_CONFIDENCE_THRESHOLD

    def validate_response(
        self,
        response_text: str,
        context_text: str,
        sources: List[str],
        confidence: float,
        language: str = "en",
        strict_grounding: bool = False,
    ) -> Dict[str, Any]:
        """
        Validate a response and return enhanced version.

        Returns:
            {
                "text": str,           # Final response text
                "is_valid": bool,      # Whether response passed validation
                "warnings": list,      # List of warnings
                "modified": bool,      # Whether response was modified
                "citation_added": bool # Whether source citation was added
            }
        """
        result = {
            "text": response_text,
            "is_valid": True,
            "warnings": [],
            "modified": False,
            "citation_added": False,
        }

        # 1. Check confidence
        if confidence < self.min_confidence:
            result["warnings"].append(f"Low confidence: {confidence:.2f}")

            if strict_grounding:
                result["text"] = NO_DATA_RESPONSES.get(language, NO_DATA_RESPONSES["en"])
                result["is_valid"] = False
                result["modified"] = True
                return result

        # 2. Check grounding
        is_grounded, grounding_issues = check_grounding(
            response_text,
            context_text,
            strict_mode=strict_grounding,
        )

        if grounding_issues:
            result["warnings"].extend(grounding_issues)

        if not is_grounded and strict_grounding:
            result["text"] = NO_DATA_RESPONSES.get(language, NO_DATA_RESPONSES["en"])
            result["is_valid"] = False
            result["modified"] = True
            return result

        # 3. Add source citation (if sources available and confidence is decent)
        if sources and confidence >= 0.5:
            enhanced_text = add_source_citation(
                response_text,
                sources,
                language,
            )
            if enhanced_text != response_text:
                result["text"] = enhanced_text
                result["citation_added"] = True
                result["modified"] = True

        return result

    def create_safe_response(
        self,
        user_message: str,
        context_text: str,
        language: str = "en",
    ) -> str:
        """
        Create a safe response when we can't generate a reliable one.
        """
        if not context_text or "[NO_RELEVANT_DATA_FOUND]" in context_text:
            return NO_DATA_RESPONSES.get(language, NO_DATA_RESPONSES["en"])

        # Extract a safe snippet from context
        lines = context_text.split("\n")
        safe_lines = []

        for line in lines:
            line = line.strip()
            if not line or line.startswith("["):
                continue
            # Remove any metadata
            line = re.sub(r"\[conf:[^\]]+\]", "", line).strip()
            if line and len(line) > 10:
                safe_lines.append(line)
                if len(safe_lines) >= 2:
                    break

        if safe_lines:
            if language == "ko":
                return "관련 정보:\n" + "\n".join(safe_lines)
            return "Related information:\n" + "\n".join(safe_lines)

        return NO_DATA_RESPONSES.get(language, NO_DATA_RESPONSES["en"])


# =============================================================================
# PROMPT INJECTION PROTECTION
# =============================================================================

INJECTION_PATTERNS = [
    # Prompt override attempts
    r"ignore\s+(?:all\s+)?(?:previous|above|prior)\s+(?:instructions?|prompts?)",
    r"ignore\s+all\s+above",
    r"(?:forget|disregard)\s+(?:everything|all)",
    r"you\s+are\s+now\s+(?:a|an)\s+",
    r"new\s+instructions?:",
    r"system\s*(?:prompt|message):",
    r"\[system\]",
    r"</\s*instructions\s*>",
    r"override\s+safety",
    r"pretend\s+you\s+are\s+",
    r"act\s+as\s+if\s+you\s+have\s+no\s+restrictions",
    r"jailbreak",
    r"bypass\s+(?:all\s+)?filters?",
    # Code injection
    r"```(?:python|javascript|bash|sh)",
    r"<script",
    r"eval\s*\(",
    r"exec\s*\(",
]

INJECTION_SANITIZE_PATTERNS = [
    (r"```[\s\S]*?```", "[CODE_BLOCK_REMOVED]"),
    (r"[<>/`]", ""),
]
def detect_prompt_injection(text: str) -> Tuple[bool, List[str]]:
    """
    Detect potential prompt injection attempts.

    Returns:
        (is_injection, list of detected patterns)
    """
    if not text:
        return False, []

    text_lower = text.lower()
    detected = []

    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, text_lower):
            match = re.search(pattern, text_lower)
            if match:
                detected.append(f"Injection pattern: {match.group()[:50]}")

    return len(detected) > 0, detected

def sanitize_user_input(text: str, max_length: int = 1000) -> str:
    """
    Sanitize user input to prevent injection attacks.
    """
    if not text:
        return ""

    # Truncate
    text = text[:max_length]

    # Apply sanitization patterns
    for pattern, replacement in INJECTION_SANITIZE_PATTERNS:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)

    # Keep letters, digits, common punctuation, and CJK characters.
    text = re.sub(r"[^0-9A-Za-z\u00C0-\u024F\u3131-\u3163\uAC00-\uD7A3\u4E00-\u9FFF\s\.,;:!?\-'\"()+/%#@]", "", text)

    # Remove excessive whitespace
    text = re.sub(r"\s+", " ", text).strip()

    return text


# Singleton instance
response_validator = ResponseValidator()

