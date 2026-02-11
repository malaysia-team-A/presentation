"""
Semantic Cache Engine - SentenceTransformer-powered Query Caching
Uses local all-MiniLM-L6-v2 embeddings to match similar queries and return cached responses.
"""
import hashlib
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np

try:
    from sentence_transformers import SentenceTransformer
    _st_model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
    HAS_ST = True
except Exception:
    _st_model = None
    HAS_ST = False


def _compute_embedding(text: str) -> Optional[np.ndarray]:
    if not HAS_ST or _st_model is None:
        return None
    try:
        vec = _st_model.encode(str(text), show_progress_bar=False)
        return vec.astype(np.float32)
    except Exception as e:
        print(f"[SemanticCache] Embedding error: {e}")
        return None


class SemanticCache:
    def __init__(
        self,
        similarity_threshold: float = 0.92,
        max_cache_size: int = 1000,
        ttl_seconds: int = 3600,
    ):
        self.similarity_threshold = similarity_threshold
        self.max_cache_size = max_cache_size
        self.ttl_seconds = ttl_seconds

        # {cache_key: {embedding, response, timestamp, query, hit_count}}
        self.cache: Dict[str, Dict] = {}
        self.embeddings_matrix: Optional[np.ndarray] = None
        self.cache_keys: List[str] = []

        self.stats = {"hits": 0, "misses": 0, "evictions": 0}

        if not HAS_ST:
            print("[SemanticCache] Disabled - sentence-transformers not installed")
        else:
            print("[SemanticCache] Initialized with all-MiniLM-L6-v2")

    def _generate_cache_key(self, query: str) -> str:
        return hashlib.md5(query.lower().strip().encode()).hexdigest()

    def _cosine_similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        norm_a, norm_b = np.linalg.norm(a), np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))

    def _find_similar(self, query_embedding: np.ndarray) -> Optional[Tuple[str, float]]:
        if not self.cache_keys or self.embeddings_matrix is None:
            return None
        # Normalized matrix dot product for batch cosine similarity
        q_norm = np.linalg.norm(query_embedding)
        if q_norm == 0:
            return None
        similarities = np.dot(self.embeddings_matrix, query_embedding) / q_norm
        max_idx = int(np.argmax(similarities))
        max_sim = float(similarities[max_idx])
        if max_sim >= self.similarity_threshold:
            return (self.cache_keys[max_idx], max_sim)
        return None

    def _rebuild_embeddings_matrix(self) -> None:
        if not self.cache:
            self.embeddings_matrix = None
            self.cache_keys = []
            return
        self.cache_keys = list(self.cache.keys())
        mat = np.vstack([self.cache[k]["embedding"] for k in self.cache_keys])
        norms = np.linalg.norm(mat, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        self.embeddings_matrix = mat / norms

    def _evict_expired(self) -> None:
        now = datetime.now()
        expired = [
            k for k, v in self.cache.items()
            if (now - v["timestamp"]).total_seconds() > self.ttl_seconds
        ]
        for key in expired:
            del self.cache[key]
            self.stats["evictions"] += 1
        if expired:
            self._rebuild_embeddings_matrix()

    def _evict_lru(self) -> None:
        if len(self.cache) < self.max_cache_size:
            return
        sorted_entries = sorted(
            self.cache.items(),
            key=lambda x: (x[1]["hit_count"], x[1]["timestamp"])
        )
        for key, _ in sorted_entries[:max(1, len(self.cache) // 10)]:
            del self.cache[key]
            self.stats["evictions"] += 1
        self._rebuild_embeddings_matrix()

    def get(self, query: str) -> Optional[Dict]:
        if not HAS_ST:
            return None
        self._evict_expired()
        query_embedding = _compute_embedding(query)
        if query_embedding is None:
            return None
        result = self._find_similar(query_embedding)
        if result:
            cache_key, similarity = result
            entry = self.cache[cache_key]
            entry["hit_count"] += 1
            self.stats["hits"] += 1
            print(f"[SemanticCache] HIT! Sim: {similarity:.3f} | Orig: '{entry['query'][:30]}...'")
            return {
                "response": entry["response"],
                "original_query": entry["query"],
                "similarity": similarity,
                "from_cache": True,
            }
        self.stats["misses"] += 1
        return None

    def put(self, query: str, response: str) -> None:
        if not HAS_ST:
            return
        if not response or len(response) < 20:
            return
        if "error" in response.lower() or "couldn't find" in response.lower():
            return
        self._evict_lru()
        embedding = _compute_embedding(query)
        if embedding is None:
            return
        cache_key = self._generate_cache_key(query)
        self.cache[cache_key] = {
            "embedding": embedding,
            "query": query,
            "response": response,
            "timestamp": datetime.now(),
            "hit_count": 0,
        }
        self._rebuild_embeddings_matrix()

    def get_stats(self) -> Dict:
        return self.stats

    def clear(self) -> None:
        self.cache.clear()
        self.embeddings_matrix = None
        self.cache_keys = []
        print("[SemanticCache] Cleared")


semantic_cache = SemanticCache()
