"""
Query Rewriter Engine - Transform queries for optimal retrieval
Expands, normalizes, and enriches user queries to improve RAG accuracy.
Inspired by: Google Search Query Understanding, Elasticsearch Query DSL
"""
import re
from typing import List, Dict, Tuple, Optional


class QueryRewriter:
    """
    World-class Query Rewriting Pipeline
    
    Transforms user queries through multiple stages:
    1. Normalization - Clean and standardize
    2. Expansion - Add synonyms and related terms
    3. Entity Recognition - Identify key entities
    4. Multi-Query Generation - Create multiple search queries
    """
    
    def __init__(self):
        # Synonym mappings for query expansion
        self.synonyms = {
            # Fees
            "fee": ["cost", "price", "tuition", "payment", "charge"],
            "cost": ["fee", "price", "tuition", "payment"],
            "tuition": ["fee", "cost", "price"],
            "비용": ["학비", "가격", "요금", "등록금"],
            "학비": ["비용", "등록금", "수업료"],
            
            # Accommodation
            "hostel": ["dormitory", "dorm", "accommodation", "residence", "housing"],
            "dormitory": ["hostel", "dorm", "accommodation", "residence"],
            "기숙사": ["숙소", "레지던스", "하숙"],
            
            # Location
            "location": ["where", "place", "address", "situated", "find"],
            "where": ["location", "place", "situated"],
            "어디": ["위치", "장소", "어느"],
            
            # Schedule
            "schedule": ["timetable", "timing", "hours", "when"],
            "timetable": ["schedule", "timing", "hours"],
            "시간표": ["스케줄", "일정"],
            
            # Staff
            "professor": ["lecturer", "teacher", "instructor", "faculty", "dr"],
            "lecturer": ["professor", "teacher", "instructor"],
            "교수": ["강사", "선생님", "교수님"],
            
            # Programs
            "course": ["program", "programme", "major", "degree", "subject"],
            "major": ["program", "course", "degree", "field"],
            "전공": ["학과", "프로그램", "학부"],
        }
        
        # Entity patterns for recognition
        self.entity_patterns = {
            "building": r'\b(?:Block|Building|Hall|Wing|Level|Floor|Room|Lab)\s*[A-Z0-9]+\b',
            "course_code": r'\b[A-Z]{2,4}\s*\d{2,4}\b',
            "money": r'\bRM\s*[\d,\.]+\b',
            "department": r'\b(?:Faculty|Department|School)\s+of\s+\w+(?:\s+\w+)*\b',
        }
        
        # Common query templates for expansion
        self.query_templates = {
            "location": [
                "{entity} location",
                "where is {entity}",
                "{entity} address",
                "{entity} situated"
            ],
            "fee": [
                "{entity} fee",
                "{entity} cost",
                "how much {entity}",
                "{entity} price"
            ],
            "schedule": [
                "{entity} schedule",
                "{entity} timetable",
                "{entity} hours",
                "when {entity}"
            ]
        }
    
    def normalize(self, query: str) -> str:
        """
        Stage 1: Normalize the query
        - Lowercase for matching
        - Remove extra whitespace
        - Fix common typos
        - Preserve important entities (Block A, etc.)
        """
        # Preserve entities before lowercasing
        entities = self._extract_entities(query)
        
        # Basic normalization
        normalized = query.strip()
        normalized = re.sub(r'\s+', ' ', normalized)  # Multiple spaces to single
        normalized = re.sub(r'[?!.,]+$', '', normalized)  # Remove trailing punctuation
        
        # Common typo fixes
        typo_fixes = {
            "univesity": "university",
            "accomodation": "accommodation",
            "tution": "tuition",
            "shcedule": "schedule",
            "libary": "library",
        }
        
        for typo, fix in typo_fixes.items():
            normalized = re.sub(rf'\b{typo}\b', fix, normalized, flags=re.IGNORECASE)
        
        return normalized
    
    def _extract_entities(self, query: str) -> Dict[str, List[str]]:
        """Extract named entities from query"""
        entities = {}
        
        for entity_type, pattern in self.entity_patterns.items():
            matches = re.findall(pattern, query, re.IGNORECASE)
            if matches:
                entities[entity_type] = matches
        
        return entities
    
    def expand(self, query: str) -> List[str]:
        """
        Stage 2: Expand query with synonyms
        Returns list of expanded query variations
        """
        expanded = [query]  # Original query first
        query_lower = query.lower()
        
        # Add synonym expansions
        for term, synonyms in self.synonyms.items():
            if term.lower() in query_lower:
                for synonym in synonyms[:2]:  # Top 2 synonyms only
                    expanded_query = re.sub(
                        rf'\b{re.escape(term)}\b', 
                        synonym, 
                        query, 
                        flags=re.IGNORECASE
                    )
                    if expanded_query != query:
                        expanded.append(expanded_query)
        
        return list(dict.fromkeys(expanded))  # Deduplicate preserving order
    
    def generate_search_queries(self, query: str) -> List[str]:
        """
        Stage 3: Generate multiple optimized search queries
        """
        queries = []
        normalized = self.normalize(query)
        
        # Start with normalized query
        queries.append(normalized)
        
        # Add expanded variations
        expanded = self.expand(normalized)
        queries.extend(expanded)
        
        # Extract key entities and generate focused queries
        entities = self._extract_entities(query)
        
        for entity_type, entity_list in entities.items():
            for entity in entity_list:
                # Just the entity itself is often a good search term
                queries.append(entity)
        
        # Extract important keywords
        keywords = self._extract_keywords(normalized)
        if keywords:
            # Keyword-only query
            queries.append(" ".join(keywords[:3]))
        
        return list(dict.fromkeys(queries))[:5]  # Return top 5 unique queries
    
    def _extract_keywords(self, query: str) -> List[str]:
        """Extract important keywords from query"""
        stopwords = {
            'what', 'where', 'which', 'how', 'is', 'are', 'the', 'a', 'an',
            'of', 'in', 'on', 'at', 'to', 'for', 'do', 'does', 'can', 'i',
            'you', 'there', 'have', 'has', 'my', 'about', 'tell', 'me',
            'please', 'could', 'would', 'want', 'know', 'find', 'get'
        }
        
        # Extract words
        words = re.findall(r'\b\w+\b', query.lower())
        keywords = [w for w in words if w not in stopwords and len(w) > 2]
        
        return keywords
    
    def rewrite(self, query: str) -> Dict:
        """
        Main rewriting method - Full pipeline
        
        Returns:
            {
                "original": str,
                "normalized": str,
                "search_queries": List[str],
                "entities": Dict[str, List[str]],
                "keywords": List[str]
            }
        """
        normalized = self.normalize(query)
        entities = self._extract_entities(query)
        keywords = self._extract_keywords(normalized)
        search_queries = self.generate_search_queries(query)
        
        return {
            "original": query,
            "normalized": normalized,
            "search_queries": search_queries,
            "entities": entities,
            "keywords": keywords,
            "primary_query": search_queries[0] if search_queries else normalized
        }


# Singleton
query_rewriter = QueryRewriter()


if __name__ == "__main__":
    # Test the query rewriter
    rewriter = QueryRewriter()
    
    test_queries = [
        "Where is Block A?",
        "How much is the hostel fee?",
        "기숙사 비용이 얼마예요?",
        "CS101 course schedule",
        "who is the professor for computer science"
    ]
    
    for query in test_queries:
        print(f"\n{'='*50}")
        print(f"Original: {query}")
        result = rewriter.rewrite(query)
        print(f"Normalized: {result['normalized']}")
        print(f"Search queries: {result['search_queries']}")
        print(f"Entities: {result['entities']}")
        print(f"Keywords: {result['keywords']}")
