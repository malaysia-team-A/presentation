import asyncio
import os
import re
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

import numpy as np

try:
    from sentence_transformers import SentenceTransformer
    HAS_ST = True
except Exception:
    SentenceTransformer = None
    HAS_ST = False

_st_model = None
_st_model_lock = threading.Lock()
_st_model_load_attempted = False


def _load_st_model() -> Optional[Any]:
    """Lazily load SentenceTransformer to avoid heavy import-time initialization."""
    global _st_model, _st_model_load_attempted

    if not HAS_ST:
        return None
    if _st_model is not None:
        return _st_model
    if _st_model_load_attempted:
        return None

    with _st_model_lock:
        if _st_model is not None:
            return _st_model
        if _st_model_load_attempted:
            return None

        _st_model_load_attempted = True
        try:
            _st_model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
            print("[SemanticRouter] SentenceTransformer model loaded.")
        except Exception as e:
            _st_model = None
            print(f"[SemanticRouter] SentenceTransformer load failed: {e}")
        return _st_model

from app.engines.db_engine_async import db_engine_async

# Constants
DEFAULT_COLLECTION = os.getenv("SEMANTIC_ROUTER_COLLECTION", "semantic_intents")
DEFAULT_INDEX = os.getenv("SEMANTIC_ROUTER_INDEX", "semantic_intent_vector_idx")
MIN_CONFIDENCE = float(os.getenv("SEMANTIC_ROUTER_MIN_CONFIDENCE", "0.53"))
ENABLED = str(os.getenv("SEMANTIC_ROUTER_ENABLED", "true")).strip().lower() in {"1", "true", "yes", "on"}
EMBED_DIM = 384  # all-MiniLM-L6-v2

SEED_SOURCE = "default_seed_st_v1"

DEFAULT_INTENT_EXAMPLES: Dict[str, List[str]] = {
    "personal_profile": [
        "show my profile", "show my student information", "what is my nationality",
        "내 정보 보여줘", "내 프로필 알려줘", "내 전공 알려줘",
    ],
    "personal_grade": [
        "show my gpa", "show my grades", "what is my cgpa",
        "내 gpa 알려줘", "내 성적 보여줘", "내 학점 알려줘",
    ],
    "ucsi_programme": [
        "tell me about ucsi programme", "tuition fee for this programme", "entry requirement for ucsi",
        "UCSI 전공 정보 알려줘", "등록금 알려줘", "입학 조건 알려줘",
    ],
    "ucsi_hostel": [
        "ucsi hostel fee", "hostel deposit", "hostel policy",
        "기숙사 비용 알려줘", "기숙사 보증금 얼마야", "기숙사 정책 알려줘",
    ],
    "ucsi_staff": [
        "who is the dean of this faculty", "staff contact in ucsi", "professor in computer science ucsi",
        "UCSI 교수 정보 알려줘", "학장 누구야", "직원 연락처 알려줘",
    ],
    "ucsi_facility": [
        "where is the library on campus", "campus facilities", "is there a gym in ucsi",
        "도서관 위치 알려줘", "캠퍼스 시설 알려줘", "프린터 어디 있어",
    ],
    "ucsi_schedule": [
        "semester schedule ucsi", "intake dates", "exam period",
        "학사 일정 알려줘", "입학 시기 알려줘", "시험 기간 언제야",
    ],
    "general_person": [
        "who is taylor swift", "tell me about albert einstein",
        "이순신에 대해서 알려줘", "김연아 누구야",
    ],
    "general_world": [
        "what is machine learning", "capital of malaysia",
        "양자역학이 뭐야", "말레이시아 수도는 어디야",
    ],
    "capability_smalltalk": [
        "can you do a handstand", "can you dance",
        "물구나무 설 수 있어", "춤출 수 있어",
    ],
}

PERSONAL_INTENTS = {"personal_profile", "personal_grade"}
UCSI_CONTEXT_INTENTS = {
    "ucsi_programme", "ucsi_hostel", "ucsi_staff", "ucsi_facility", "ucsi_schedule",
}


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.dot(a, b) / denom) if denom > 0 else 0.0


def _embed(text: str) -> Optional[List[float]]:
    model = _load_st_model()
    if model is None:
        return None
    txt = str(text or "").strip()
    if not txt:
        return None
    try:
        vec = model.encode(txt, show_progress_bar=False)
        return vec.tolist()
    except Exception as e:
        print(f"[SemanticRouter] Embed failed: {e}")
        return None


class AsyncSemanticRouter:
    def __init__(self):
        self.collection = None
        self._ready = False
        self._init_lock = asyncio.Lock()

    async def initialize(self) -> bool:
        if not ENABLED:
            return False
        if self._ready:
            return True
        async with self._init_lock:
            if self._ready:
                return True
            if not HAS_ST:
                print("[SemanticRouter] Disabled: sentence-transformers not installed")
                return False
            if _load_st_model() is None:
                print("[SemanticRouter] Disabled: sentence-transformers model unavailable")
                return False
            if db_engine_async.db is None:
                return False
            try:
                self.collection = db_engine_async.db[DEFAULT_COLLECTION]
                await self._ensure_seed_data()
                self._ready = True
                return True
            except Exception as e:
                print(f"[SemanticRouter] Init failed: {e}")
                self._ready = False
                return False

    async def _ensure_seed_data(self) -> None:
        if self.collection is None:
            return
        try:
            existing = await self.collection.count_documents({"source": SEED_SOURCE})
            if existing > 0:
                return
            # Remove old incompatible seeds
            await self.collection.delete_many(
                {"source": {"$in": ["default_seed_v1", "default_seed_genai_v1"]}}
            )
            docs = []
            for intent, examples in DEFAULT_INTENT_EXAMPLES.items():
                for text in examples:
                    vec = await asyncio.to_thread(_embed, text)
                    if not vec:
                        continue
                    docs.append({
                        "intent": intent,
                        "example": text,
                        "embedding": vec,
                        "source": SEED_SOURCE,
                        "created_at": datetime.now().isoformat(),
                    })
            if docs:
                await self.collection.insert_many(docs, ordered=False)
                print(f"[SemanticRouter] Seeded {len(docs)} intents with SentenceTransformer.")
        except Exception as e:
            print(f"[SemanticRouter] Seed error: {e}")

    def _extract_turn_text(self, raw_content: Any) -> str:
        text = re.sub(r"\s+", " ", str(raw_content or "")).strip()
        return text[:280]

    def _build_history_hint(self, conversation_history, user_message: str) -> str:
        if not conversation_history:
            return ""
        items = [i for i in conversation_history if isinstance(i, dict)]
        if not items:
            return ""
        if str(items[-1].get("role")).lower() == "user":
            tail = self._extract_turn_text(items[-1].get("content"))
            if tail == str(user_message).strip():
                items = items[:-1]
        picked = []
        uc = mc = 0
        for item in reversed(items):
            role = str(item.get("role")).lower()
            txt = self._extract_turn_text(item.get("content"))
            if not txt:
                continue
            if role == "user" and uc < 2:
                picked.append(txt)
                uc += 1
            elif role != "user" and mc < 1:
                picked.append(txt)
                mc += 1
            if uc >= 2 and mc >= 1:
                break
        picked.reverse()
        return " ".join(picked)[:240]

    def _should_blend_history(self, user_message: str) -> bool:
        text = str(user_message or "").strip()
        return len(text.split()) <= 7 or len(text) <= 40

    async def _vector_search_intents(self, query_vector: List[float], limit: int = 8) -> List[Dict]:
        if self.collection is None:
            return []
        try:
            pipeline = [
                {
                    "$vectorSearch": {
                        "index": DEFAULT_INDEX,
                        "path": "embedding",
                        "queryVector": query_vector,
                        "numCandidates": max(40, limit * 10),
                        "limit": limit,
                    }
                },
                {"$project": {"_id": 0, "intent": 1, "score": {"$meta": "vectorSearchScore"}}}
            ]
            return await self.collection.aggregate(pipeline).to_list(length=limit)
        except Exception:
            return []

    async def _local_similarity_fallback(self, query_vector: List[float], limit: int = 8) -> List[Dict]:
        if self.collection is None:
            return []
        try:
            docs = await self.collection.find(
                {"source": SEED_SOURCE},
                {"_id": 0, "intent": 1, "embedding": 1}
            ).to_list(length=500)
            qv = np.array(query_vector, dtype=np.float32)
            ranked = []
            for doc in docs:
                emb = doc.get("embedding")
                if not emb or len(emb) != EMBED_DIM:
                    continue
                score = _cosine(qv, np.array(emb, dtype=np.float32))
                ranked.append({"intent": doc.get("intent"), "score": score})
            ranked.sort(key=lambda x: x["score"], reverse=True)
            return ranked[:limit]
        except Exception:
            return []

    def _aggregate_intent_score(self, rows: List[Dict]) -> Dict[str, float]:
        stats: Dict[str, Dict] = {}
        for r in rows:
            intent = r.get("intent")
            score = float(r.get("score", 0.0))
            if not intent:
                continue
            s = stats.setdefault(intent, {"max": 0.0, "sum": 0.0, "count": 0})
            s["max"] = max(s["max"], score)
            s["sum"] += score
            s["count"] += 1
        return {k: (v["max"] * 0.8) + (v["sum"] / v["count"] * 0.2) for k, v in stats.items()}

    def _extract_entity(self, message: str) -> Optional[str]:
        m = re.search(r"who(?:'s| is)\s+(?P<name>.+?)\??$", str(message).strip(), re.I)
        return m.group("name").strip() if m else None

    async def classify(
        self,
        user_message: str,
        search_term: str = None,
        language: str = "en",
        conversation_history=None,
    ) -> Optional[Dict]:
        if not user_message:
            return None
        if not await self.initialize():
            return None

        query = str(user_message).strip()
        if search_term:
            query += f" {search_term}"

        qv = await asyncio.to_thread(_embed, query)
        if not qv:
            return None

        if self._should_blend_history(user_message):
            hint = self._build_history_hint(conversation_history, user_message)
            if hint:
                hv = await asyncio.to_thread(_embed, hint)
                if hv:
                    qv = (np.array(qv) * 0.7 + np.array(hv) * 0.3).tolist()

        rows = await self._vector_search_intents(qv)
        if not rows:
            rows = await self._local_similarity_fallback(qv)
        if not rows:
            return None

        scores = self._aggregate_intent_score(rows)
        if not scores:
            return None

        best_intent, best_score = max(scores.items(), key=lambda x: x[1])

        result: Dict[str, Any] = {
            "intent": best_intent,
            "confidence": best_score,
            "language": language,
            "is_personal": best_intent in PERSONAL_INTENTS,
            "needs_context": best_intent in UCSI_CONTEXT_INTENTS,
        }

        if best_intent == "general_person":
            result["entity"] = self._extract_entity(user_message)

        if result["confidence"] < MIN_CONFIDENCE:
            result["intent"] = "unknown"
            result["needs_context"] = False

        return result


semantic_router_async = AsyncSemanticRouter()
