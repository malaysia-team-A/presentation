"""
FAQ Cache Engine - High-frequency questions rule-based processing
자주 묻는 질문 캐싱으로 AI 호출 없이 즉시 응답
"""
import json
import os
from typing import Optional, Dict, List
from datetime import datetime
from collections import Counter

FAQ_CACHE_FILE = "data/faq_cache.json"
QUESTION_LOG_FILE = "data/question_log.json"
UNANSWERED_FILE = "data/unanswered_questions.json"

class FAQCacheEngine:
    def __init__(self):
        self.cache = {}  # {normalized_question: {"answer": str, "hits": int, "created": str}}
        self.question_counts = Counter()  # Track question frequency
        self.threshold = 3  # Questions asked 3+ times become cached
        self._load_cache()
    
    def _load_cache(self):
        """Load FAQ cache from file"""
        if os.path.exists(FAQ_CACHE_FILE):
            try:
                with open(FAQ_CACHE_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.cache = data.get("faqs", {})
                    self.question_counts = Counter(data.get("counts", {}))
            except:
                self.cache = {}
                self.question_counts = Counter()
    
    def _save_cache(self):
        """Save FAQ cache to file"""
        try:
            with open(FAQ_CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump({
                    "faqs": self.cache,
                    "counts": dict(self.question_counts),
                    "updated": datetime.now().isoformat()
                }, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"FAQ cache save error: {e}")
    
    def _normalize_question(self, question: str) -> str:
        """Normalize question for matching"""
        # Remove punctuation and lowercase
        import re
        normalized = re.sub(r'[^\w\s]', '', question.lower().strip())
        # Remove common filler words
        fillers = ['please', 'can you', 'could you', 'tell me', 'what is', 'how do i', '알려줘', '뭐야', '어떻게']
        for filler in fillers:
            normalized = normalized.replace(filler, '')
        return ' '.join(normalized.split())  # Normalize whitespace
    
    def get_cached_answer(self, question: str) -> Optional[Dict]:
        """
        Check if question has a cached answer
        Returns {"answer": str, "suggestions": list} or None
        """
        normalized = self._normalize_question(question)
        
        # Track question frequency
        self.question_counts[normalized] += 1
        self._save_cache()
        
        if normalized in self.cache:
            self.cache[normalized]["hits"] += 1
            self._save_cache()
            return {
                "answer": self.cache[normalized]["answer"],
                "suggestions": self.cache[normalized].get("suggestions", []),
                "from_cache": True
            }
        return None
    
    def add_to_cache(self, question: str, answer: str, suggestions: List[str] = None):
        """
        Add a Q&A pair to cache (manual or automatic)
        """
        normalized = self._normalize_question(question)
        self.cache[normalized] = {
            "answer": answer,
            "suggestions": suggestions or [],
            "hits": 0,
            "created": datetime.now().isoformat(),
            "original_question": question
        }
        self._save_cache()
    
    def should_cache(self, question: str) -> bool:
        """Check if question should be auto-cached (high frequency)"""
        normalized = self._normalize_question(question)
        return self.question_counts[normalized] >= self.threshold
    
    def auto_cache_if_needed(self, question: str, answer: str, suggestions: List[str] = None):
        """Auto-cache if question is frequently asked"""
        if self.should_cache(question) and self._normalize_question(question) not in self.cache:
            self.add_to_cache(question, answer, suggestions)
            return True
        return False
    
    def get_stats(self) -> Dict:
        """Get FAQ cache statistics"""
        total_hits = sum(item.get("hits", 0) for item in self.cache.values())
        return {
            "cached_questions": len(self.cache),
            "total_hits": total_hits,
            "unique_questions_seen": len(self.question_counts),
            "top_questions": self.question_counts.most_common(10)
        }
    
    def get_all_faqs(self) -> List[Dict]:
        """Get all cached FAQs for admin panel"""
        return [
            {
                "question": data.get("original_question", key),
                "answer": data["answer"],
                "hits": data.get("hits", 0),
                "created": data.get("created", "")
            }
            for key, data in self.cache.items()
        ]
    
    def delete_faq(self, question: str) -> bool:
        """Delete a cached FAQ"""
        normalized = self._normalize_question(question)
        if normalized in self.cache:
            del self.cache[normalized]
            self._save_cache()
            return True
        return False


class UnansweredQuestionManager:
    """Manage questions that couldn't be answered"""
    
    def __init__(self):
        self.unanswered = []
        self._load()
    
    def _load(self):
        if os.path.exists(UNANSWERED_FILE):
            try:
                with open(UNANSWERED_FILE, 'r', encoding='utf-8') as f:
                    self.unanswered = json.load(f)
            except:
                self.unanswered = []
    
    def _save(self):
        try:
            with open(UNANSWERED_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.unanswered, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Unanswered save error: {e}")
    
    def log_unanswered(self, question: str, context: str = "", reason: str = "no_match"):
        """Log an unanswered question"""
        entry = {
            "id": len(self.unanswered) + 1,
            "question": question,
            "context": context[:500] if context else "",
            "reason": reason,
            "timestamp": datetime.now().isoformat(),
            "resolved": False
        }
        self.unanswered.append(entry)
        self._save()
        return entry["id"]
    
    def get_unresolved(self) -> List[Dict]:
        """Get all unresolved questions"""
        return [q for q in self.unanswered if not q.get("resolved", False)]
    
    def get_all(self) -> List[Dict]:
        """Get all unanswered questions"""
        return self.unanswered
    
    def resolve(self, question_id: int, answer: str = ""):
        """Mark a question as resolved"""
        for q in self.unanswered:
            if q.get("id") == question_id:
                q["resolved"] = True
                q["resolved_at"] = datetime.now().isoformat()
                q["resolution"] = answer
                self._save()
                return True
        return False
    
    def get_stats(self) -> Dict:
        """Get unanswered question statistics"""
        unresolved = len([q for q in self.unanswered if not q.get("resolved", False)])
        return {
            "total": len(self.unanswered),
            "unresolved": unresolved,
            "resolved": len(self.unanswered) - unresolved
        }


# Singleton instances
faq_cache = FAQCacheEngine()
unanswered_manager = UnansweredQuestionManager()


if __name__ == "__main__":
    # Test
    print("FAQ Cache Stats:", faq_cache.get_stats())
    print("Unanswered Stats:", unanswered_manager.get_stats())
