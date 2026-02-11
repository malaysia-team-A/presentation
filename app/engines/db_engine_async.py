import os
import re
import motor.motor_asyncio
from typing import Optional, Dict, List, Any
from datetime import datetime
from app.config import Config

_QUERY_TOKEN_RE = re.compile(r"[a-z0-9가-힣]{2,}")
_QUERY_STOPWORDS = {
    "what",
    "who",
    "when",
    "where",
    "why",
    "how",
    "is",
    "are",
    "was",
    "were",
    "the",
    "a",
    "an",
    "to",
    "for",
    "of",
    "in",
    "on",
    "about",
    "tell",
    "show",
    "please",
    "can",
    "you",
    "do",
    "did",
    "me",
    "my",
    "정보",
    "알려줘",
    "말해줘",
    "대해",
    "대해서",
    "관련",
    "좀",
    "해줘",
    "해줘요",
    "부탁",
}

FEEDBACK_COLLECTION = "Feedback"
LEGACY_FEEDBACK_COLLECTION = "feedbacks"
UNANSWERED_COLLECTION = "unanswered"
LEARNED_QA_COLLECTION = "LearnedQA"
BAD_QA_COLLECTION = "BadQA"


def _env_bool(name: str, default: bool = False) -> bool:
    raw = str(os.getenv(name, "true" if default else "false")).strip().lower()
    return raw in {"1", "true", "yes", "on"}


USE_LEGACY_FEEDBACK_COLLECTION = _env_bool("USE_LEGACY_FEEDBACK_COLLECTION", False)
USE_LEGACY_QA_COLLECTIONS = _env_bool("USE_LEGACY_QA_COLLECTIONS", False)


def _feedback_collections() -> List[str]:
    collections = [FEEDBACK_COLLECTION]
    if USE_LEGACY_FEEDBACK_COLLECTION:
        collections.append(LEGACY_FEEDBACK_COLLECTION)
    return collections

_FEEDBACK_POLICY_TAG_RULES = {
    "no_hallucination": [
        "halluc",
        "fabricat",
        "made up",
        "invent",
        "없는",
        "지어",
        "추측",
        "가짜",
    ],
    "grounded_to_db": [
        "db",
        "database",
        "source",
        "citation",
        "근거",
        "출처",
        "데이터",
        "정확",
    ],
    "verify_numbers": [
        "wrong number",
        "incorrect number",
        "price",
        "fee",
        "tuition",
        "금액",
        "숫자",
        "비용",
        "학비",
    ],
    "more_specific": [
        "generic",
        "too broad",
        "vague",
        "모호",
        "구체",
        "자세",
        "too generic",
    ],
    "concise_format": [
        "too long",
        "verbose",
        "길어",
        "장황",
        "요약",
        "간단",
    ],
}


def _normalize_query_text(query: str) -> str:
    text = str(query or "").strip().lower()
    if not text:
        return ""
    text = text.replace("_", " ")
    text = re.sub(r"[\t\r\n]+", " ", text)
    text = re.sub(r"[^\w가-힣\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _extract_query_tokens(query: str) -> List[str]:
    norm = _normalize_query_text(query)
    if not norm:
        return []
    out: List[str] = []
    seen = set()
    for tok in _QUERY_TOKEN_RE.findall(norm):
        if tok in _QUERY_STOPWORDS:
            continue
        if tok in seen:
            continue
        seen.add(tok)
        out.append(tok)
    return out[:24]


def _token_overlap_score(query_tokens: List[str], candidate_tokens: List[str]) -> float:
    q = [str(t).strip().lower() for t in (query_tokens or []) if str(t).strip()]
    c = [str(t).strip().lower() for t in (candidate_tokens or []) if str(t).strip()]
    if not q or not c:
        return 0.0

    q_set = set(q)
    c_set = set(c)
    intersection = len(q_set.intersection(c_set))
    if intersection == 0:
        return 0.0

    precision = intersection / max(1, len(c_set))
    recall = intersection / max(1, len(q_set))
    jaccard = intersection / max(1, len(q_set.union(c_set)))

    score = (precision * 0.35) + (recall * 0.45) + (jaccard * 0.20)
    if intersection >= 3:
        score += 0.08
    return min(score, 1.0)


def _derive_feedback_policy_tags(comment: Any, ai_response: Any) -> List[str]:
    text = f"{str(comment or '')} {str(ai_response or '')}".strip().lower()
    if not text:
        return []
    tags: List[str] = []
    for tag, keywords in _FEEDBACK_POLICY_TAG_RULES.items():
        if any(k in text for k in keywords):
            tags.append(tag)
    return tags


class AsyncDatabaseEngine:
    def __init__(self):
        self.client = None
        self.db = None
        self.student_collection_name = "UCSI"  # Default
        
    async def connect(self):
        """Establish connection to MongoDB Atlas"""
        try:
            uri = Config.MONGO_URI
            if not uri:
                print("Error: MONGO_URI not found in .env")
                return

            self.client = motor.motor_asyncio.AsyncIOMotorClient(uri, serverSelectionTimeoutMS=5000)
            
            # Verify connection
            await self.client.admin.command('ping')
            
            # Get Database
            db_name = uri.split('/')[-1].split('?')[0] or "UCSI_DB"
            self.db = self.client[db_name]
            print(f"[AsyncDB] Successfully connected to MongoDB: {db_name}")

            # Smart detection of Student Collection
            try:
                colls = await self.db.list_collection_names()
                candidates = ["UCSI", "students", "Students", "UCSI_STUDENTS"]
                found = False
                for c in candidates:
                    if c in colls:
                        self.student_collection_name = c
                        found = True
                        break
                
                if not found:
                    for c in colls:
                        if "student" in c.lower() or "ucsi" in c.lower():
                            self.student_collection_name = c
                            found = True
                            print(f"DEBUG: Auto-detected student collection: {c}")
                            break
                            
                if found or colls:
                    target = self.student_collection_name if found else colls[0]
                    # Check if empty? No, just assume it's valid for now
                    print(f"DEBUG: Using collection '{target}' for student data.")
                    self.student_collection_name = target
            except Exception as e:
                print(f"Warning: Could not auto-detect collections: {e}")

            await self._ensure_runtime_indexes()
            
        except Exception as e:
            print(f"[AsyncDB][ERROR] Database connection failed: {e}")

    async def _ensure_runtime_indexes(self) -> None:
        """Create frequently used indexes for stable runtime latency."""
        if self.db is None:
            return
        for coll_name in _feedback_collections():
            try:
                await self.db[coll_name].create_index(
                    [("query_norm", 1), ("rating", 1), ("timestamp", -1)],
                    name=f"{coll_name.lower()}_query_rating_ts",
                )
                await self.db[coll_name].create_index(
                    [("timestamp", -1)],
                    name=f"{coll_name.lower()}_timestamp_desc",
                )
                await self.db[coll_name].create_index(
                    [("reward", 1), ("timestamp", -1)],
                    name=f"{coll_name.lower()}_reward_ts",
                )
            except Exception as e:
                print(f"{coll_name} index ensure error: {e}")

        try:
            await self.db[UNANSWERED_COLLECTION].create_index(
                [("timestamp", -1)],
                name="unanswered_timestamp_desc",
            )
        except Exception as e:
            print(f"Unanswered index ensure error: {e}")

        if USE_LEGACY_QA_COLLECTIONS:
            try:
                await self.db[LEARNED_QA_COLLECTION].create_index(
                    [("query_norm", 1)],
                    name="learnedqa_query_norm",
                )
            except Exception as e:
                print(f"LearnedQA index ensure error: {e}")

            try:
                await self.db[BAD_QA_COLLECTION].create_index(
                    [("query_norm", 1)],
                    name="badqa_query_norm",
                )
            except Exception as e:
                print(f"BadQA index ensure error: {e}")

    @property
    def student_coll(self):
        if self.db is not None:
            return self.db[self.student_collection_name]
        return None

    def query_metadata(self, query: str) -> Dict[str, Any]:
        query_norm = _normalize_query_text(query)
        return {
            "query_norm": query_norm,
            "query_tokens": _extract_query_tokens(query_norm),
        }

    def _compose_rlhf_policy_hint(self, policy: Dict[str, Any]) -> Optional[str]:
        if not isinstance(policy, dict) or not policy.get("has_signal"):
            return None

        instructions: List[str] = []
        if policy.get("strict_grounding"):
            instructions.append("Use only verified context; if confidence is low, answer no-data.")

        for tag in policy.get("top_tags", [])[:3]:
            if tag == "no_hallucination":
                instructions.append("Avoid speculative or fabricated claims.")
            elif tag == "grounded_to_db":
                instructions.append("Anchor claims to retrieved DB evidence.")
            elif tag == "verify_numbers":
                instructions.append("Double-check all numbers, fees, and dates before answering.")
            elif tag == "more_specific":
                instructions.append("Be concrete and specific; avoid generic statements.")
            elif tag == "concise_format":
                instructions.append("Keep responses concise and structured.")

        avoid = [str(x).strip() for x in (policy.get("avoid_responses") or []) if str(x).strip()]
        if avoid:
            instructions.append(
                "Do not repeat these downrated styles: "
                + " | ".join(avoid[:2])
            )

        if not instructions:
            return None
        return "RLHF policy hint:\n- " + "\n- ".join(instructions[:6])

    async def get_student_by_number(self, student_number: str) -> Optional[Dict]:
        if self.student_coll is None: return None
        try:
            # Try string
            student = await self.student_coll.find_one({"STUDENT_NUMBER": str(student_number)})
            if student: return student
            
            # Try int
            if str(student_number).isdigit():
                student = await self.student_coll.find_one({"STUDENT_NUMBER": int(student_number)})
                if student: return student
                    
            return None
        except Exception as e:
            print(f"DB Error: {e}")
            return None

    async def get_student_by_name(self, name: str) -> Optional[Dict]:
        if self.student_coll is None: return None
        try:
            escaped_name = re.escape(str(name or "").strip())
            if not escaped_name:
                return None
            return await self.student_coll.find_one({
                "STUDENT_NAME": {"$regex": f"^{escaped_name}$", "$options": "i"}
            })
        except Exception as e:
            print(f"DB Error: {e}")
            return None

    async def search_programme_by_keywords(self, keywords: List[str], limit: int = 5) -> List[Dict]:
        if self.student_coll is None: return []
        
        sanitized = []
        for k in (keywords or []):
            kw_clean = str(k).strip()
            if len(kw_clean) >= 3:
                sanitized.append(kw_clean)
        if not sanitized: return []

        or_conditions = []
        fields = ["PROGRAMME_NAME", "PROGRAMME", "PROGRAMME_TITLE"]
        for kw in sanitized:
            regex = {"$regex": re.escape(kw), "$options": "i"}
            for field in fields:
                or_conditions.append({field: regex})
        
        if not or_conditions: return []

        try:
            cursor = self.student_coll.find({"$or": or_conditions}, {"_id": 0}).limit(limit * 3)
            return await cursor.to_list(length=limit * 3)
        except Exception as e:
            print(f"DB Error: {e}")
            return []

    async def find_staff_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """
        Find a public staff profile candidate from UCSI_STAFF by name.
        Returns minimal safe profile fields or None.
        """
        if self.db is None:
            return None

        candidate = str(name or "").strip()
        if len(candidate) < 2:
            return None

        coll = self.db["UCSI_STAFF"]

        try:
            escaped = re.escape(candidate)
            patterns = [rf"^{escaped}$", escaped]

            for pattern in patterns:
                name_filter = {"$regex": pattern, "$options": "i"}
                doc = await coll.find_one(
                    {"staff_members.name": name_filter},
                    {
                        "_id": 0,
                        "major": 1,
                        "staff_members": {"$elemMatch": {"name": name_filter}},
                    },
                )
                if not doc:
                    continue

                members = doc.get("staff_members") or []
                member = members[0] if members else {}
                if not isinstance(member, dict):
                    member = {}

                staff_name = str(member.get("name") or "").strip()
                if not staff_name:
                    continue

                return {
                    "name": staff_name,
                    "role": str(member.get("role") or "").strip(),
                    "email": str(member.get("email") or "").strip(),
                    "profile_url": str(member.get("profile_url") or "").strip(),
                    "major": str(doc.get("major") or "").strip(),
                }
        except Exception as e:
            print(f"Staff lookup error: {e}")

        return None

    async def search_by_name(self, query: str) -> Optional[Dict[str, Any]]:
        """Search student and staff collections using name/keyword extracted from the query.

        Runs in parallel with RAG to catch exact-name queries that vector search might miss.
        Returns formatted context dict or None.
        """
        if self.db is None:
            return None

        # Strip common question words to extract the entity name/keyword
        candidate = re.sub(
            r"(?i)\b(tell|me|about|who|is|what|show|find|information|info|can|are|does|do|"
            r"the|a|an|for|please|give|get|look|up|search|describe|explain|details|detail)\b",
            " ", query,
        )
        candidate = re.sub(
            r"(알려줘|알려주세요|누구야|누구예요|누구인가요|누구니|에\s*대해|정보|관련|알려|"
            r"보여줘|보여주세요|이야기해줘|설명해줘)",
            " ", candidate,
        )
        candidate = re.sub(r"\s+", " ", candidate).strip(" ?.,!")

        if len(candidate) < 2:
            return None

        contexts: List[str] = []
        sources: List[str] = []

        # 1. Student search (exclude sensitive fields)
        if self.student_coll is not None:
            try:
                escaped = re.escape(candidate)
                student = await self.student_coll.find_one(
                    {"STUDENT_NAME": {"$regex": escaped, "$options": "i"}},
                    {"_id": 0, "Password": 0, "GPA": 0, "CGPA": 0, "DOB": 0, "STUDENT_NUMBER": 0},
                )
                if student:
                    parts = ["[Student]"] + [f"{k}: {v}" for k, v in student.items() if v is not None]
                    contexts.append(" | ".join(parts))
                    sources.append(f"MongoDB:{self.student_collection_name}")
            except Exception as e:
                print(f"[DB] search_by_name student error: {e}")

        # 2. Staff search
        staff = await self.find_staff_by_name(candidate)
        if staff:
            parts = ["[Staff]"] + [f"{k}: {v}" for k, v in staff.items() if v]
            contexts.append(" | ".join(parts))
            sources.append("MongoDB:UCSI_STAFF")

        if not contexts:
            return None

        return {
            "context": "\n\n".join(contexts),
            "sources": sources,
        }

    async def save_feedback(self, feedback_data: Dict) -> bool:
        if self.db is None:
            return False
        try:
            user_message = str(feedback_data.get("user_message") or "").strip()
            ai_response = str(feedback_data.get("ai_response") or "").strip()
            if not user_message or not ai_response:
                return False

            rating = str(feedback_data.get("rating") or "").strip().lower()
            if rating not in {"positive", "negative"}:
                return False

            session_id = str(
                feedback_data.get("session_id")
                or feedback_data.get("conversation_id")
                or "guest_session"
            ).strip() or "guest_session"

            comment = feedback_data.get("comment")
            comment_norm = None if comment is None else str(comment).strip() or None
            timestamp = str(feedback_data.get("timestamp") or datetime.now().isoformat())
            meta = self.query_metadata(user_message)
            policy_tags = _derive_feedback_policy_tags(comment_norm, ai_response)
            reward = 1.0 if rating == "positive" else -1.0

            payload = {
                "user_message": user_message,
                "ai_response": ai_response,
                "rating": rating,
                "reward": reward,
                "comment": comment_norm,
                "session_id": session_id,
                "timestamp": timestamp,
                "query_norm": meta["query_norm"],
                "query_tokens": meta["query_tokens"],
                "policy_tags": policy_tags,
            }
            await self.db[FEEDBACK_COLLECTION].insert_one(payload)
            return True
        except Exception as e:
            print(f"Feedback save error: {e}")
            return False

    async def log_unanswered(self, question_data: Dict) -> bool:
        if self.db is None:
            return False
        try:
            await self.db[UNANSWERED_COLLECTION].insert_one(question_data)
            return True
        except Exception as e:
            print(f"Unanswered log error: {e}")
            return False

    async def save_learned_response(self, query: str, answer: str) -> bool:
        if self.db is None:
            return False
        try:
            meta = self.query_metadata(query)
            query_norm = meta["query_norm"] or str(query or "").strip().lower()
            now = datetime.now()

            # Canonical memory path: keep learned signal in Feedback.
            await self.db[FEEDBACK_COLLECTION].update_one(
                {"query_norm": query_norm, "rating": "positive"},
                {
                    "$set": {
                        "user_message": str(query or "").strip(),
                        "ai_response": str(answer or "").strip(),
                        "rating": "positive",
                        "reward": 1.0,
                        "query_norm": query_norm,
                        "query_tokens": meta["query_tokens"],
                        "memory_source": "learned_positive_feedback",
                        "timestamp": now,
                    },
                    "$setOnInsert": {
                        "session_id": "system_memory",
                        "comment": "Auto-promoted from positive feedback",
                    },
                },
                upsert=True,
            )

            # Optional legacy compatibility write.
            if USE_LEGACY_QA_COLLECTIONS:
                await self.db[LEARNED_QA_COLLECTION].update_one(
                    {"query_norm": query_norm},
                    {
                        "$set": {
                            "query": query_norm,
                            "query_norm": query_norm,
                            "query_tokens": meta["query_tokens"],
                            "answer": str(answer or "").strip(),
                            "timestamp": now,
                            "source": "user_feedback",
                        }
                    },
                    upsert=True,
                )
            return True
        except Exception as e:
            print(f"Learned response save error: {e}")
            return False

    async def search_learned_response(self, query: str) -> Optional[str]:
        if self.db is None:
            return None

        meta = self.query_metadata(query)
        q_norm = meta["query_norm"]
        q_raw = str(query or "").strip().lower()
        q_tokens = meta["query_tokens"]
        if not q_norm:
            return None

        try:
            # 1) Canonical lookup from Feedback positive samples.
            escaped = re.escape(q_raw.rstrip("?.!"))
            exact_or = [{"query_norm": q_norm}]
            if q_raw:
                exact_or.append({"user_message": {"$regex": f"^{escaped}[?.!]*$", "$options": "i"}})

            docs = await self.db[FEEDBACK_COLLECTION].find(
                {"rating": "positive", "$or": exact_or},
                {"_id": 0, "ai_response": 1, "timestamp": 1},
            ).sort("timestamp", -1).limit(1).to_list(length=1)
            if docs:
                answer = str((docs[0] or {}).get("ai_response") or "").strip()
                if answer:
                    return answer

            # 2) Fuzzy positive feedback matching.
            feedback_rows = await self.db[FEEDBACK_COLLECTION].find(
                {"rating": "positive"},
                {"_id": 0, "ai_response": 1, "query_norm": 1, "query_tokens": 1, "user_message": 1},
            ).sort("timestamp", -1).limit(160).to_list(length=160)

            best_answer = None
            best_score = 0.0
            for row in feedback_rows:
                answer = str(row.get("ai_response") or "").strip()
                if not answer:
                    continue
                candidate_norm = str(row.get("query_norm") or row.get("user_message") or "").strip().lower()
                candidate_tokens = row.get("query_tokens")
                if not isinstance(candidate_tokens, list):
                    candidate_tokens = _extract_query_tokens(candidate_norm)

                score = _token_overlap_score(q_tokens, candidate_tokens)
                if candidate_norm and (q_norm in candidate_norm or candidate_norm in q_norm):
                    score = max(score, 0.90 if min(len(q_norm), len(candidate_norm)) >= 8 else 0.78)
                if score > best_score:
                    best_score = score
                    best_answer = answer

            threshold = 0.86 if len(q_tokens) <= 2 else 0.62
            if best_answer and best_score >= threshold:
                return best_answer

            # 3) Optional legacy fallback (read-only compatibility).
            if USE_LEGACY_QA_COLLECTIONS:
                doc = await self.db[LEARNED_QA_COLLECTION].find_one(
                    {"$or": [{"query_norm": q_norm}, {"query": q_norm}, {"query": q_raw}]},
                    {"_id": 0, "answer": 1},
                )
                if not doc and q_raw:
                    legacy_escaped = re.escape(q_raw.rstrip("?.!"))
                    if legacy_escaped:
                        doc = await self.db[LEARNED_QA_COLLECTION].find_one(
                            {"query": {"$regex": f"^{legacy_escaped}[?.!]*$", "$options": "i"}},
                            {"_id": 0, "answer": 1},
                        )
                if doc:
                    answer = str(doc.get("answer") or "").strip()
                    if answer:
                        return answer
            return None
        except Exception as e:
            print(f"Learned response search error: {e}")
            return None

    async def save_bad_response(self, query: str, bad_answer: str, reason: str = "") -> bool:
        if self.db is None:
            return False
        try:
            meta = self.query_metadata(query)
            query_norm = meta["query_norm"] or str(query or "").strip().lower()
            now = datetime.now()

            # Canonical memory path: keep negative signal in Feedback.
            await self.db[FEEDBACK_COLLECTION].update_one(
                {"query_norm": query_norm, "rating": "negative"},
                {
                    "$set": {
                        "user_message": str(query or "").strip(),
                        "ai_response": str(bad_answer or "").strip(),
                        "rating": "negative",
                        "reward": -1.0,
                        "query_norm": query_norm,
                        "query_tokens": meta["query_tokens"],
                        "comment": str(reason or "").strip() or "User marked as incorrect",
                        "memory_source": "negative_feedback_guard",
                        "timestamp": now,
                    },
                    "$setOnInsert": {"session_id": "system_memory"},
                },
                upsert=True,
            )

            # Optional legacy compatibility write.
            if USE_LEGACY_QA_COLLECTIONS:
                await self.db[BAD_QA_COLLECTION].update_one(
                    {"query_norm": query_norm},
                    {
                        "$set": {
                            "query": query_norm,
                            "query_norm": query_norm,
                            "query_tokens": meta["query_tokens"],
                            "bad_answer": str(bad_answer or "").strip(),
                            "reason": str(reason or "").strip(),
                            "timestamp": now,
                        },
                        "$inc": {"count": 1},
                    },
                    upsert=True,
                )
            return True
        except Exception as e:
            print(f"Bad response save error: {e}")
            return False

    async def has_bad_response(self, query: str) -> bool:
        if self.db is None:
            return False
        meta = self.query_metadata(query)
        q_norm = meta["query_norm"]
        q_tokens = meta["query_tokens"]
        if not q_norm:
            return False
        try:
            query_escaped = re.escape(str(query or "").strip())
            for feedback_coll in _feedback_collections():
                feedback_hit = await self.db[feedback_coll].find_one(
                    {
                        "rating": "negative",
                        "$or": [
                            {"query_norm": q_norm},
                            {"user_message": {"$regex": f"^{query_escaped}$", "$options": "i"}},
                        ],
                    },
                    {"_id": 1},
                )
                if feedback_hit:
                    return True

            if q_tokens:
                for feedback_coll in _feedback_collections():
                    fb_rows = await self.db[feedback_coll].find(
                        {"rating": "negative"},
                        {"_id": 0, "query_norm": 1, "query_tokens": 1, "user_message": 1},
                    ).sort("timestamp", -1).limit(200).to_list(length=200)
                    for row in fb_rows:
                        candidate_norm = str(row.get("query_norm") or row.get("user_message") or "").strip().lower()
                        candidate_tokens = row.get("query_tokens")
                        if not isinstance(candidate_tokens, list):
                            candidate_tokens = _extract_query_tokens(candidate_norm)
                        score = _token_overlap_score(q_tokens, candidate_tokens)
                        if candidate_norm and (q_norm in candidate_norm or candidate_norm in q_norm):
                            score = max(score, 0.88 if min(len(q_norm), len(candidate_norm)) >= 8 else 0.74)
                        if score >= 0.70:
                            return True

            if USE_LEGACY_QA_COLLECTIONS:
                bad_exact = await self.db[BAD_QA_COLLECTION].find_one(
                    {"$or": [{"query_norm": q_norm}, {"query": q_norm}]},
                    {"_id": 1},
                )
                if bad_exact:
                    return True

                if q_tokens:
                    bad_rows = await self.db[BAD_QA_COLLECTION].find(
                        {},
                        {"_id": 0, "query_norm": 1, "query_tokens": 1, "query": 1},
                    ).sort("timestamp", -1).limit(120).to_list(length=120)
                    for row in bad_rows:
                        candidate_norm = str(row.get("query_norm") or row.get("query") or "").strip().lower()
                        candidate_tokens = row.get("query_tokens")
                        if not isinstance(candidate_tokens, list):
                            candidate_tokens = _extract_query_tokens(candidate_norm)
                        score = _token_overlap_score(q_tokens, candidate_tokens)
                        if candidate_norm and (q_norm in candidate_norm or candidate_norm in q_norm):
                            score = max(score, 0.90 if min(len(q_norm), len(candidate_norm)) >= 8 else 0.76)
                        if score >= 0.66:
                            return True

            return False
        except Exception as e:
            print(f"Bad response check error: {e}")
            return False

    async def get_rlhf_policy(self, query: str, limit_per_collection: int = 180) -> Dict[str, Any]:
        if self.db is None:
            return {"has_signal": False}

        meta = self.query_metadata(query)
        q_norm = meta.get("query_norm", "")
        q_tokens = meta.get("query_tokens", [])
        if not q_norm:
            return {"has_signal": False}

        positive_weight = 0.0
        negative_weight = 0.0
        signal_count = 0
        tag_weights: Dict[str, float] = {}
        bad_examples: Dict[str, float] = {}
        good_examples: Dict[str, float] = {}

        for coll_name in _feedback_collections():
            try:
                rows = await self.db[coll_name].find(
                    {},
                    {
                        "_id": 0,
                        "rating": 1,
                        "reward": 1,
                        "user_message": 1,
                        "ai_response": 1,
                        "query_norm": 1,
                        "query_tokens": 1,
                        "policy_tags": 1,
                        "comment": 1,
                        "timestamp": 1,
                    },
                ).sort("timestamp", -1).limit(max(20, int(limit_per_collection))).to_list(length=max(20, int(limit_per_collection)))
            except Exception:
                continue

            for row in rows:
                rating = str(row.get("rating") or "").strip().lower()
                if rating not in {"positive", "negative"}:
                    continue

                candidate_norm = str(row.get("query_norm") or row.get("user_message") or "").strip().lower()
                candidate_tokens = row.get("query_tokens")
                if not isinstance(candidate_tokens, list):
                    candidate_tokens = _extract_query_tokens(candidate_norm)

                score = _token_overlap_score(q_tokens, candidate_tokens)
                if candidate_norm and (q_norm in candidate_norm or candidate_norm in q_norm):
                    score = max(score, 0.88 if min(len(q_norm), len(candidate_norm)) >= 8 else 0.74)
                if score < 0.35:
                    continue

                weight = max(0.15, min(score, 1.0))
                signal_count += 1
                if rating == "positive":
                    positive_weight += weight
                else:
                    negative_weight += weight

                tags = row.get("policy_tags")
                if not isinstance(tags, list) or not tags:
                    tags = _derive_feedback_policy_tags(row.get("comment"), row.get("ai_response"))
                for tag in tags:
                    t = str(tag).strip()
                    if not t:
                        continue
                    tag_weights[t] = tag_weights.get(t, 0.0) + weight

                ai_response = str(row.get("ai_response") or "").strip()
                if ai_response:
                    if rating == "negative" and score >= 0.55:
                        bad_examples[ai_response] = max(weight, bad_examples.get(ai_response, 0.0))
                    if rating == "positive" and score >= 0.62:
                        good_examples[ai_response] = max(weight, good_examples.get(ai_response, 0.0))

        if signal_count == 0:
            return {"has_signal": False}

        top_tags = [k for k, _ in sorted(tag_weights.items(), key=lambda kv: kv[1], reverse=True)[:4]]
        avoid_responses = [k for k, _ in sorted(bad_examples.items(), key=lambda kv: kv[1], reverse=True)[:3]]
        preferred_responses = [k for k, _ in sorted(good_examples.items(), key=lambda kv: kv[1], reverse=True)[:2]]

        strict_grounding = (
            signal_count >= 2
            and (
                negative_weight >= (positive_weight * 1.10)
                or "no_hallucination" in top_tags
                or "grounded_to_db" in top_tags
            )
        )

        policy = {
            "has_signal": True,
            "signal_count": signal_count,
            "positive_weight": round(float(positive_weight), 4),
            "negative_weight": round(float(negative_weight), 4),
            "strict_grounding": bool(strict_grounding),
            "top_tags": top_tags,
            "avoid_responses": avoid_responses,
            "preferred_responses": preferred_responses,
        }
        policy["policy_hint"] = self._compose_rlhf_policy_hint(policy)
        return policy

    async def get_student_stats(self) -> Dict:
        """Aggregate high-level student statistics."""
        if self.student_coll is None:
            return {"total_students": 0, "gender": {}, "top_nationalities": {}}

        try:
            total_students = await self.student_coll.count_documents({})

            gender_pipeline = [
                {"$group": {"_id": "$GENDER", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}}
            ]
            nationality_pipeline = [
                {"$group": {"_id": "$NATIONALITY", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}},
                {"$limit": 10}
            ]

            gender_rows = await self.student_coll.aggregate(gender_pipeline).to_list(length=None)
            nationality_rows = await self.student_coll.aggregate(nationality_pipeline).to_list(length=10)

            gender = {str(r.get("_id", "Unknown")): r.get("count", 0) for r in gender_rows}
            top_nationalities = {str(r.get("_id", "Unknown")): r.get("count", 0) for r in nationality_rows}

            return {
                "total_students": total_students,
                "gender": gender,
                "top_nationalities": top_nationalities
            }
        except Exception as e:
            print(f"Student stats error: {e}")
            return {"total_students": 0, "gender": {}, "top_nationalities": {}}

# Singleton
db_engine_async = AsyncDatabaseEngine()
