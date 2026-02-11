"""
Unanswered Questions Analyzer for UCSI Buddy Chatbot

Analyzes unanswered questions to:
1. Identify knowledge gaps
2. Prioritize data additions
3. Generate weekly reports
4. Track improvement trends
"""

import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from collections import defaultdict


# =============================================================================
# ANALYSIS FUNCTIONS
# =============================================================================

def normalize_question(text: str) -> str:
    """Normalize a question for comparison."""
    text = str(text or "").strip().lower()
    # Remove punctuation
    text = re.sub(r"[?!.,;:\"'`]", "", text)
    # Normalize whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def extract_keywords(text: str) -> List[str]:
    """Extract meaningful keywords from a question."""
    stopwords = {
        "what", "where", "when", "how", "why", "who", "which",
        "is", "are", "was", "were", "the", "a", "an", "to", "for",
        "of", "in", "on", "about", "tell", "me", "please", "can", "you",
        "do", "does", "did", "my", "i", "알려", "줘", "해줘", "뭐",
        "어디", "언제", "어떻게", "왜", "누구", "좀", "가",
    }

    text = normalize_question(text)
    words = re.findall(r"[a-z0-9가-힣]+", text)
    keywords = [w for w in words if len(w) > 1 and w not in stopwords]
    return keywords[:10]


def calculate_similarity(keywords1: List[str], keywords2: List[str]) -> float:
    """Calculate similarity between two keyword sets."""
    if not keywords1 or not keywords2:
        return 0.0

    set1, set2 = set(keywords1), set(keywords2)
    intersection = len(set1 & set2)
    union = len(set1 | set2)

    if union == 0:
        return 0.0

    return intersection / union


# =============================================================================
# UNANSWERED ANALYZER CLASS
# =============================================================================

class UnansweredAnalyzer:
    """
    Analyzes unanswered questions to identify patterns and priorities.
    """

    def __init__(self):
        self.category_keywords = {
            "hostel": ["hostel", "dorm", "room", "accommodation", "기숙사", "숙소", "방"],
            "fees": ["fee", "tuition", "cost", "price", "payment", "등록금", "비용", "학비"],
            "programme": ["programme", "program", "course", "major", "전공", "학과", "프로그램"],
            "staff": ["staff", "professor", "lecturer", "dean", "교수", "강사", "직원"],
            "facility": ["library", "gym", "cafeteria", "facility", "도서관", "시설", "체육관"],
            "schedule": ["schedule", "calendar", "semester", "exam", "일정", "학기", "시험"],
            "admission": ["admission", "apply", "requirement", "입학", "지원", "조건"],
        }

    async def analyze(
        self,
        days: int = 7,
        limit: int = 100,
    ) -> Dict[str, Any]:
        """
        Analyze unanswered questions from the database.

        Returns:
            {
                "summary": {...},
                "by_category": {...},
                "top_questions": [...],
                "trends": {...},
                "recommendations": [...]
            }
        """
        from app.engines.db_engine_async import db_engine_async

        if db_engine_async.db is None:
            return {"error": "Database not connected"}

        # Fetch unanswered questions
        cutoff = datetime.now() - timedelta(days=days)
        try:
            questions = await db_engine_async.db["unanswered"].find(
                {"timestamp": {"$gte": cutoff.isoformat()}},
                {"_id": 0},
            ).sort("timestamp", -1).limit(limit).to_list(length=limit)
        except Exception as e:
            return {"error": str(e)}

        if not questions:
            return {
                "summary": {"total": 0, "period_days": days},
                "by_category": {},
                "top_questions": [],
                "recommendations": [],
            }

        # Analyze
        by_category = self._categorize_questions(questions)
        clusters = self._cluster_similar_questions(questions)
        trends = self._analyze_trends(questions)
        recommendations = self._generate_recommendations(by_category, clusters)

        return {
            "summary": {
                "total": len(questions),
                "period_days": days,
                "unique_topics": len(clusters),
                "analyzed_at": datetime.now().isoformat(),
            },
            "by_category": by_category,
            "top_questions": clusters[:10],
            "trends": trends,
            "recommendations": recommendations,
        }

    def _categorize_questions(
        self,
        questions: List[Dict[str, Any]],
    ) -> Dict[str, Dict[str, Any]]:
        """Categorize questions by topic."""
        categories = defaultdict(lambda: {"count": 0, "examples": []})

        for q in questions:
            text = str(q.get("question") or q.get("search_query") or "").lower()
            matched = False

            for category, keywords in self.category_keywords.items():
                if any(kw in text for kw in keywords):
                    categories[category]["count"] += 1
                    if len(categories[category]["examples"]) < 3:
                        categories[category]["examples"].append(text[:100])
                    matched = True
                    break

            if not matched:
                categories["other"]["count"] += 1
                if len(categories["other"]["examples"]) < 3:
                    categories["other"]["examples"].append(text[:100])

        # Sort by count
        return dict(sorted(categories.items(), key=lambda x: x[1]["count"], reverse=True))

    def _cluster_similar_questions(
        self,
        questions: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Cluster similar questions together."""
        clusters = []
        processed = set()

        for i, q in enumerate(questions):
            if i in processed:
                continue

            text = str(q.get("question") or q.get("search_query") or "")
            keywords = extract_keywords(text)

            if not keywords:
                continue

            # Find similar questions
            cluster = {
                "representative": text[:150],
                "keywords": keywords[:5],
                "count": 1,
                "avg_confidence": q.get("confidence", 0),
                "examples": [text[:100]],
            }
            processed.add(i)

            for j, other in enumerate(questions[i + 1:], i + 1):
                if j in processed:
                    continue

                other_text = str(other.get("question") or other.get("search_query") or "")
                other_keywords = extract_keywords(other_text)

                similarity = calculate_similarity(keywords, other_keywords)
                if similarity >= 0.5:
                    cluster["count"] += 1
                    cluster["avg_confidence"] += other.get("confidence", 0)
                    if len(cluster["examples"]) < 5:
                        cluster["examples"].append(other_text[:100])
                    processed.add(j)

            cluster["avg_confidence"] = round(
                cluster["avg_confidence"] / cluster["count"], 3
            )
            clusters.append(cluster)

        # Sort by count
        clusters.sort(key=lambda x: x["count"], reverse=True)
        return clusters

    def _analyze_trends(
        self,
        questions: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Analyze trends in unanswered questions."""
        by_day = defaultdict(int)
        by_hour = defaultdict(int)
        confidence_sum = 0
        confidence_count = 0

        for q in questions:
            timestamp = q.get("timestamp")
            if timestamp:
                try:
                    if isinstance(timestamp, str):
                        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                    else:
                        dt = timestamp

                    by_day[dt.strftime("%Y-%m-%d")] += 1
                    by_hour[dt.hour] += 1
                except Exception:
                    pass

            confidence = q.get("confidence", 0)
            if confidence:
                confidence_sum += confidence
                confidence_count += 1

        # Find peak hour
        peak_hour = max(by_hour.items(), key=lambda x: x[1])[0] if by_hour else None

        return {
            "by_day": dict(sorted(by_day.items())),
            "peak_hour": peak_hour,
            "avg_confidence": round(confidence_sum / max(1, confidence_count), 3),
            "daily_average": round(len(questions) / max(1, len(by_day)), 1),
        }

    def _generate_recommendations(
        self,
        by_category: Dict[str, Dict[str, Any]],
        clusters: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Generate actionable recommendations."""
        recommendations = []

        # Recommend adding data for top categories
        for category, data in list(by_category.items())[:3]:
            if data["count"] >= 3:
                recommendations.append({
                    "priority": "high" if data["count"] >= 5 else "medium",
                    "type": "add_data",
                    "category": category,
                    "description": f"Add more {category} information to the knowledge base",
                    "example_questions": data["examples"][:2],
                    "impact": f"Could resolve ~{data['count']} questions",
                })

        # Recommend specific topics from clusters
        for cluster in clusters[:3]:
            if cluster["count"] >= 2:
                recommendations.append({
                    "priority": "high" if cluster["count"] >= 4 else "medium",
                    "type": "add_topic",
                    "topic": ", ".join(cluster["keywords"][:3]),
                    "description": f"Add information about: {cluster['representative'][:80]}",
                    "frequency": cluster["count"],
                })

        # Sort by priority
        priority_order = {"high": 0, "medium": 1, "low": 2}
        recommendations.sort(key=lambda x: priority_order.get(x["priority"], 2))

        return recommendations[:5]

    async def generate_report(
        self,
        days: int = 7,
        format: str = "text",
    ) -> str:
        """
        Generate a human-readable report.

        Args:
            days: Number of days to analyze
            format: "text" or "markdown"

        Returns:
            Formatted report string
        """
        analysis = await self.analyze(days=days)

        if "error" in analysis:
            return f"Error generating report: {analysis['error']}"

        summary = analysis["summary"]
        by_category = analysis["by_category"]
        recommendations = analysis["recommendations"]

        if format == "markdown":
            return self._format_markdown_report(summary, by_category, recommendations)
        else:
            return self._format_text_report(summary, by_category, recommendations)

    def _format_text_report(
        self,
        summary: Dict,
        by_category: Dict,
        recommendations: List,
    ) -> str:
        """Format report as plain text."""
        lines = [
            "=" * 50,
            "UNANSWERED QUESTIONS REPORT",
            "=" * 50,
            "",
            f"Period: Last {summary['period_days']} days",
            f"Total unanswered: {summary['total']}",
            f"Unique topics: {summary['unique_topics']}",
            "",
            "-" * 30,
            "BY CATEGORY:",
            "-" * 30,
        ]

        for category, data in by_category.items():
            lines.append(f"  {category}: {data['count']}")

        lines.extend([
            "",
            "-" * 30,
            "RECOMMENDATIONS:",
            "-" * 30,
        ])

        for i, rec in enumerate(recommendations, 1):
            lines.append(f"  {i}. [{rec['priority'].upper()}] {rec['description']}")

        lines.append("")
        lines.append(f"Generated: {summary.get('analyzed_at', 'N/A')}")

        return "\n".join(lines)

    def _format_markdown_report(
        self,
        summary: Dict,
        by_category: Dict,
        recommendations: List,
    ) -> str:
        """Format report as Markdown."""
        lines = [
            "# Unanswered Questions Report",
            "",
            "## Summary",
            "",
            f"- **Period**: Last {summary['period_days']} days",
            f"- **Total unanswered**: {summary['total']}",
            f"- **Unique topics**: {summary['unique_topics']}",
            "",
            "## By Category",
            "",
            "| Category | Count |",
            "|----------|-------|",
        ]

        for category, data in by_category.items():
            lines.append(f"| {category} | {data['count']} |")

        lines.extend([
            "",
            "## Recommendations",
            "",
        ])

        for i, rec in enumerate(recommendations, 1):
            priority_emoji = "🔴" if rec["priority"] == "high" else "🟡"
            lines.append(f"{i}. {priority_emoji} **{rec['description']}**")
            if "example_questions" in rec:
                for ex in rec["example_questions"][:2]:
                    lines.append(f"   - Example: _{ex}_")

        lines.extend([
            "",
            "---",
            f"_Generated: {summary.get('analyzed_at', 'N/A')}_",
        ])

        return "\n".join(lines)


# Singleton instance
unanswered_analyzer = UnansweredAnalyzer()
