"""
Monitoring System for UCSI Buddy Chatbot

Tracks:
1. Response metrics (latency, success rate)
2. RAG hit rates
3. LLM API usage
4. User satisfaction
5. System health
"""

import asyncio
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from collections import defaultdict
import statistics


# =============================================================================
# METRICS STORAGE
# =============================================================================

class MetricsStore:
    """In-memory metrics storage with time-based cleanup."""

    def __init__(self, max_age_hours: int = 24):
        self.max_age_hours = max_age_hours
        self.metrics: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def record(self, metric_name: str, value: Any, metadata: Dict[str, Any] = None):
        """Record a metric value."""
        async with self._lock:
            self.metrics[metric_name].append({
                "timestamp": datetime.now(),
                "value": value,
                "metadata": metadata or {},
            })

    async def get_recent(
        self,
        metric_name: str,
        hours: int = 1,
    ) -> List[Dict[str, Any]]:
        """Get recent metric values."""
        cutoff = datetime.now() - timedelta(hours=hours)
        async with self._lock:
            return [
                m for m in self.metrics[metric_name]
                if m["timestamp"] > cutoff
            ]

    async def cleanup(self):
        """Remove old metrics."""
        cutoff = datetime.now() - timedelta(hours=self.max_age_hours)
        async with self._lock:
            for name in self.metrics:
                self.metrics[name] = [
                    m for m in self.metrics[name]
                    if m["timestamp"] > cutoff
                ]


# Global metrics store
metrics_store = MetricsStore()


# =============================================================================
# METRIC RECORDERS
# =============================================================================

async def record_response_time(duration_ms: float, route: str):
    """Record response time for a request."""
    await metrics_store.record("response_time", duration_ms, {"route": route})


async def record_rag_search(
    query: str,
    confidence: float,
    has_results: bool,
    sources: List[str],
):
    """Record RAG search metrics."""
    await metrics_store.record("rag_search", {
        "confidence": confidence,
        "has_results": has_results,
        "source_count": len(sources),
    }, {"query_length": len(query)})


async def record_llm_call(
    duration_ms: float,
    token_estimate: int,
    call_type: str,  # "intent", "response", etc.
    success: bool,
):
    """Record LLM API call metrics."""
    await metrics_store.record("llm_call", {
        "duration_ms": duration_ms,
        "token_estimate": token_estimate,
        "success": success,
    }, {"call_type": call_type})


async def record_classification(
    intent: str,
    confidence: float,
    source: str,  # "keyword", "vector", "llm", "hybrid"
):
    """Record intent classification metrics."""
    await metrics_store.record("classification", {
        "intent": intent,
        "confidence": confidence,
        "source": source,
    })


async def record_feedback(rating: str, session_id: str):
    """Record user feedback."""
    await metrics_store.record("feedback", {
        "rating": rating,
        "session_id": session_id,
    })


async def record_error(error_type: str, details: str = None):
    """Record an error occurrence."""
    await metrics_store.record("error", {
        "type": error_type,
        "details": details,
    })


# =============================================================================
# METRICS AGGREGATION
# =============================================================================

async def get_response_time_stats(hours: int = 1) -> Dict[str, Any]:
    """Get response time statistics."""
    metrics = await metrics_store.get_recent("response_time", hours)

    if not metrics:
        return {"count": 0, "avg_ms": 0, "p50_ms": 0, "p95_ms": 0, "p99_ms": 0}

    values = [m["value"] for m in metrics]
    sorted_values = sorted(values)

    def percentile(p: int) -> float:
        idx = int(len(sorted_values) * p / 100)
        return sorted_values[min(idx, len(sorted_values) - 1)]

    return {
        "count": len(values),
        "avg_ms": round(statistics.mean(values), 2),
        "min_ms": round(min(values), 2),
        "max_ms": round(max(values), 2),
        "p50_ms": round(percentile(50), 2),
        "p95_ms": round(percentile(95), 2),
        "p99_ms": round(percentile(99), 2),
    }


async def get_rag_stats(hours: int = 1) -> Dict[str, Any]:
    """Get RAG search statistics."""
    metrics = await metrics_store.get_recent("rag_search", hours)

    if not metrics:
        return {"count": 0, "hit_rate": 0, "avg_confidence": 0}

    values = [m["value"] for m in metrics]
    hits = sum(1 for v in values if v["has_results"])
    confidences = [v["confidence"] for v in values]

    return {
        "count": len(values),
        "hit_rate": round(hits / len(values) * 100, 2),
        "avg_confidence": round(statistics.mean(confidences), 3),
        "avg_sources": round(statistics.mean([v["source_count"] for v in values]), 1),
    }


async def get_llm_stats(hours: int = 1) -> Dict[str, Any]:
    """Get LLM API usage statistics."""
    metrics = await metrics_store.get_recent("llm_call", hours)

    if not metrics:
        return {"count": 0, "success_rate": 0, "avg_duration_ms": 0, "total_tokens": 0}

    values = [m["value"] for m in metrics]
    successes = sum(1 for v in values if v["success"])
    durations = [v["duration_ms"] for v in values]
    tokens = sum(v["token_estimate"] for v in values)

    # Group by call type
    by_type = defaultdict(list)
    for m in metrics:
        by_type[m["metadata"]["call_type"]].append(m["value"])

    type_stats = {}
    for call_type, type_values in by_type.items():
        type_stats[call_type] = {
            "count": len(type_values),
            "avg_duration_ms": round(statistics.mean([v["duration_ms"] for v in type_values]), 2),
        }

    return {
        "count": len(values),
        "success_rate": round(successes / len(values) * 100, 2),
        "avg_duration_ms": round(statistics.mean(durations), 2),
        "total_tokens_estimate": tokens,
        "by_type": type_stats,
    }


async def get_classification_stats(hours: int = 1) -> Dict[str, Any]:
    """Get intent classification statistics."""
    metrics = await metrics_store.get_recent("classification", hours)

    if not metrics:
        return {"count": 0, "avg_confidence": 0, "by_intent": {}, "by_source": {}}

    values = [m["value"] for m in metrics]
    confidences = [v["confidence"] for v in values]

    # Group by intent
    by_intent = defaultdict(int)
    for v in values:
        by_intent[v["intent"]] += 1

    # Group by source
    by_source = defaultdict(int)
    for v in values:
        by_source[v["source"]] += 1

    return {
        "count": len(values),
        "avg_confidence": round(statistics.mean(confidences), 3),
        "by_intent": dict(by_intent),
        "by_source": dict(by_source),
    }


async def get_feedback_stats(hours: int = 24) -> Dict[str, Any]:
    """Get user feedback statistics."""
    metrics = await metrics_store.get_recent("feedback", hours)

    if not metrics:
        return {"count": 0, "satisfaction_rate": 0, "positive": 0, "negative": 0}

    values = [m["value"] for m in metrics]
    positive = sum(1 for v in values if v["rating"] == "positive")
    negative = sum(1 for v in values if v["rating"] == "negative")

    return {
        "count": len(values),
        "positive": positive,
        "negative": negative,
        "satisfaction_rate": round(positive / len(values) * 100, 2) if values else 0,
    }


async def get_error_stats(hours: int = 1) -> Dict[str, Any]:
    """Get error statistics."""
    metrics = await metrics_store.get_recent("error", hours)

    if not metrics:
        return {"count": 0, "by_type": {}}

    values = [m["value"] for m in metrics]

    by_type = defaultdict(int)
    for v in values:
        by_type[v["type"]] += 1

    return {
        "count": len(values),
        "by_type": dict(by_type),
    }


# =============================================================================
# DASHBOARD DATA
# =============================================================================

async def get_dashboard_data(hours: int = 24) -> Dict[str, Any]:
    """Get all metrics for dashboard display."""
    response_times = await get_response_time_stats(hours)
    rag_stats = await get_rag_stats(hours)
    llm_stats = await get_llm_stats(hours)
    classification_stats = await get_classification_stats(hours)
    feedback_stats = await get_feedback_stats(hours)
    error_stats = await get_error_stats(hours)

    # Calculate overall health
    health_score = 100

    # Deduct for high error rate
    if error_stats["count"] > 10:
        health_score -= min(30, error_stats["count"])

    # Deduct for low satisfaction
    if feedback_stats["count"] > 0 and feedback_stats["satisfaction_rate"] < 70:
        health_score -= 20

    # Deduct for low RAG hit rate
    if rag_stats["count"] > 0 and rag_stats["hit_rate"] < 50:
        health_score -= 15

    # Deduct for high response time
    if response_times["count"] > 0 and response_times["p95_ms"] > 5000:
        health_score -= 10

    health_status = "healthy"
    if health_score < 50:
        health_status = "critical"
    elif health_score < 70:
        health_status = "warning"
    elif health_score < 90:
        health_status = "good"

    return {
        "period_hours": hours,
        "generated_at": datetime.now().isoformat(),
        "health": {
            "score": max(0, health_score),
            "status": health_status,
        },
        "response_times": response_times,
        "rag": rag_stats,
        "llm": llm_stats,
        "classification": classification_stats,
        "feedback": feedback_stats,
        "errors": error_stats,
    }


# =============================================================================
# MONITORING CLASS
# =============================================================================

class Monitor:
    """
    Convenience class for request-level monitoring.

    Usage:
        async with Monitor.request("chat") as m:
            # ... do work ...
            m.record_rag(confidence=0.8, has_results=True)
            m.record_classification("ucsi_hostel", 0.75, "vector")
    """

    def __init__(self, route: str):
        self.route = route
        self.start_time = None
        self._rag_recorded = False
        self._llm_calls = []

    async def __aenter__(self):
        self.start_time = time.time()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        duration_ms = (time.time() - self.start_time) * 1000
        await record_response_time(duration_ms, self.route)

        if exc_type:
            await record_error(exc_type.__name__, str(exc_val))

    async def record_rag(
        self,
        query: str,
        confidence: float,
        has_results: bool,
        sources: List[str] = None,
    ):
        """Record RAG search result."""
        if not self._rag_recorded:
            await record_rag_search(query, confidence, has_results, sources or [])
            self._rag_recorded = True

    async def record_llm(
        self,
        duration_ms: float,
        token_estimate: int,
        call_type: str,
        success: bool = True,
    ):
        """Record LLM API call."""
        await record_llm_call(duration_ms, token_estimate, call_type, success)

    async def record_intent(
        self,
        intent: str,
        confidence: float,
        source: str,
    ):
        """Record intent classification."""
        await record_classification(intent, confidence, source)

    @classmethod
    def request(cls, route: str) -> "Monitor":
        """Create a monitor for a request."""
        return cls(route)


# =============================================================================
# CLEANUP TASK
# =============================================================================

async def start_cleanup_task(interval_hours: int = 1):
    """Start background task to clean up old metrics."""
    while True:
        try:
            await asyncio.sleep(interval_hours * 3600)
            await metrics_store.cleanup()
            print("[Monitor] Cleaned up old metrics")
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[Monitor] Cleanup error: {e}")
