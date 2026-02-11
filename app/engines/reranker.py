"""
Lightweight Re-ranker - Keyword-based precision re-ranking
Refactored to remove heavy HuggingFace dependencies.
Uses keyword overlap and simple scoring heuristics.
"""

from typing import List, Dict, Tuple, Optional
import re

class LightweightReranker:
    """
    Lightweight reranker using keyword overlap and TF-IDF-like heuristics.
    Used to refine search results without heavy ML models.
    """
    
    def __init__(self):
        self.initialized = True
        self.stopwords = {
            'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been',
            'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will',
            'would', 'could', 'should', 'may', 'might', 'can', 'of', 'to',
            'in', 'for', 'on', 'with', 'at', 'by', 'from', 'as', 'into',
            'and', 'or', 'but', 'so', 'yet', 'nor'
        }
    
    def _tokenize(self, text: str) -> set:
        """Simple tokenization"""
        words = re.findall(r'\b\w+\b', text.lower())
        return set(w for w in words if w not in self.stopwords and len(w) > 2)
    
    def rerank(self, query: str, documents: List[str], top_k: int = 5) -> List[Tuple[int, str, float]]:
        """Rerank using keyword overlap scoring"""
        query_tokens = self._tokenize(query)
        if not query_tokens:
            return [(i, doc, 0.5) for i, doc in enumerate(documents[:top_k])]
        
        scored = []
        for i, doc in enumerate(documents):
            doc_tokens = self._tokenize(doc)
            
            if not doc_tokens:
                overlap = 0.0
            else:
                # Jaccard-like similarity
                intersection = len(query_tokens & doc_tokens)
                # Weighted score: intersection ratio relative to query length
                score = intersection / len(query_tokens)
                
                # Boost for high overlap
                if intersection >= len(query_tokens) * 0.8:
                    score *= 1.5
                elif intersection >= 2:
                    score *= 1.2
                
                overlap = min(score, 1.0)
            
            scored.append((i, doc, overlap))
        
        # Sort by score (descending)
        scored.sort(key=lambda x: x[2], reverse=True)
        return scored[:top_k]

    def score_pair(self, query: str, document: str) -> float:
        """Score a single pair"""
        q_tok = self._tokenize(query)
        d_tok = self._tokenize(document)
        if not q_tok or not d_tok:
            return 0.0
        
        intersection = len(q_tok & d_tok)
        return min(1.0, intersection / len(q_tok))

# Singleton instance
reranker = LightweightReranker()
