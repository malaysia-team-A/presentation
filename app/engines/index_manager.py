"""
Index Manager for UCSI Buddy Chatbot

Handles:
1. RAG index management (FAISS)
2. Automatic re-indexing
3. Index health monitoring
4. Data change detection
"""

import asyncio
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import hashlib
import json


# =============================================================================
# CONFIGURATION
# =============================================================================

# Re-indexing settings
AUTO_REINDEX_ENABLED = os.getenv("AUTO_REINDEX_ENABLED", "false").lower() in ("true", "1", "yes")
REINDEX_INTERVAL_HOURS = int(os.getenv("REINDEX_INTERVAL_HOURS", "6"))
MIN_REINDEX_INTERVAL_MINUTES = int(os.getenv("MIN_REINDEX_INTERVAL_MINUTES", "5"))

# Index health thresholds
MIN_DOCUMENTS_THRESHOLD = 10
STALE_INDEX_HOURS = 24


# =============================================================================
# INDEX MANAGER
# =============================================================================

class IndexManager:
    """
    Manages RAG index lifecycle including:
    - Manual and automatic re-indexing
    - Index health monitoring
    - Data change detection
    """

    def __init__(self):
        self.last_index_time: Optional[datetime] = None
        self.last_index_count: int = 0
        self.last_index_hash: Optional[str] = None
        self.index_history: List[Dict[str, Any]] = []
        self._reindex_lock = asyncio.Lock()
        self._is_indexing = False
        self._scheduled_task: Optional[asyncio.Task] = None

    @property
    def is_indexing(self) -> bool:
        """Check if indexing is currently in progress."""
        return self._is_indexing

    async def get_status(self) -> Dict[str, Any]:
        """Get current index status."""
        from app.engines.rag_engine_async import rag_engine_async

        # Get index info
        index_info = await rag_engine_async.get_index_info()

        # Calculate staleness
        is_stale = False
        hours_since_index = None

        if self.last_index_time:
            hours_since_index = (datetime.now() - self.last_index_time).total_seconds() / 3600
            is_stale = hours_since_index > STALE_INDEX_HOURS

        return {
            "last_index_time": self.last_index_time.isoformat() if self.last_index_time else None,
            "last_index_count": self.last_index_count,
            "hours_since_index": round(hours_since_index, 2) if hours_since_index else None,
            "is_stale": is_stale,
            "is_indexing": self._is_indexing,
            "auto_reindex_enabled": AUTO_REINDEX_ENABLED,
            "reindex_interval_hours": REINDEX_INTERVAL_HOURS,
            "index_info": index_info,
            "health": self._calculate_health(index_info, is_stale),
        }

    def _calculate_health(self, index_info: Dict[str, Any], is_stale: bool) -> str:
        """Calculate overall index health."""
        doc_count = index_info.get("document_count", 0)

        if doc_count == 0:
            return "critical"
        if doc_count < MIN_DOCUMENTS_THRESHOLD:
            return "warning"
        if is_stale:
            return "stale"
        return "healthy"

    async def reindex(
        self,
        force: bool = False,
        triggered_by: str = "manual",
    ) -> Dict[str, Any]:
        """
        Perform re-indexing of all MongoDB collections.

        Args:
            force: Skip minimum interval check
            triggered_by: Who/what triggered the reindex

        Returns:
            Result dictionary with status and metrics
        """
        from app.engines.rag_engine_async import rag_engine_async
        from app.engines.db_engine_async import db_engine_async

        # Check if already indexing
        if self._is_indexing:
            return {
                "success": False,
                "error": "Indexing already in progress",
                "status": "in_progress",
            }

        # Check minimum interval
        if not force and self.last_index_time:
            minutes_since = (datetime.now() - self.last_index_time).total_seconds() / 60
            if minutes_since < MIN_REINDEX_INTERVAL_MINUTES:
                return {
                    "success": False,
                    "error": f"Minimum interval not met. Wait {MIN_REINDEX_INTERVAL_MINUTES - int(minutes_since)} more minutes.",
                    "status": "rate_limited",
                }

        async with self._reindex_lock:
            self._is_indexing = True
            start_time = datetime.now()

            try:
                # Ensure DB is connected
                if db_engine_async.db is None:
                    await db_engine_async.connect()

                # Perform indexing
                count = await rag_engine_async.index_mongodb_collections()

                end_time = datetime.now()
                duration = (end_time - start_time).total_seconds()

                # Update state
                self.last_index_time = end_time
                self.last_index_count = count
                changes = await self.check_data_changes()
                self.last_index_hash = changes.get("current_hash")

                # Record in history
                record = {
                    "timestamp": end_time.isoformat(),
                    "document_count": count,
                    "duration_seconds": round(duration, 2),
                    "triggered_by": triggered_by,
                    "success": True,
                }
                self.index_history.append(record)
                self.index_history = self.index_history[-50:]  # Keep last 50

                return {
                    "success": True,
                    "document_count": count,
                    "duration_seconds": round(duration, 2),
                    "timestamp": end_time.isoformat(),
                    "status": "completed",
                }

            except Exception as e:
                # Record failure
                record = {
                    "timestamp": datetime.now().isoformat(),
                    "error": str(e),
                    "triggered_by": triggered_by,
                    "success": False,
                }
                self.index_history.append(record)

                return {
                    "success": False,
                    "error": str(e),
                    "status": "failed",
                }

            finally:
                self._is_indexing = False

    async def check_data_changes(self) -> Dict[str, Any]:
        """
        Check if data has changed since last index.

        Returns information about potential changes.
        """
        from app.engines.db_engine_async import db_engine_async

        if db_engine_async.db is None:
            return {"has_changes": False, "error": "DB not connected"}

        try:
            # Get collection counts
            collections = await db_engine_async.db.list_collection_names()
            counts = {}
            total = 0

            for coll_name in collections:
                try:
                    count = await db_engine_async.db[coll_name].count_documents({})
                    counts[coll_name] = count
                    total += count
                except Exception:
                    continue

            # Create hash of current state
            current_hash = hashlib.md5(
                json.dumps(counts, sort_keys=True).encode()
            ).hexdigest()

            has_changes = self.last_index_hash is not None and current_hash != self.last_index_hash

            return {
                "has_changes": has_changes,
                "current_hash": current_hash,
                "last_hash": self.last_index_hash,
                "total_documents": total,
                "collection_counts": counts,
            }

        except Exception as e:
            return {"has_changes": False, "error": str(e)}

    async def start_auto_reindex(self):
        """Start automatic re-indexing background task."""
        if not AUTO_REINDEX_ENABLED:
            print("[IndexManager] Auto re-index is disabled")
            return

        if self._scheduled_task and not self._scheduled_task.done():
            print("[IndexManager] Auto re-index already running")
            return

        self._scheduled_task = asyncio.create_task(self._auto_reindex_loop())
        print(f"[IndexManager] Auto re-index started (every {REINDEX_INTERVAL_HOURS} hours)")

    async def stop_auto_reindex(self):
        """Stop automatic re-indexing."""
        if self._scheduled_task:
            self._scheduled_task.cancel()
            try:
                await self._scheduled_task
            except asyncio.CancelledError:
                pass
            self._scheduled_task = None
            print("[IndexManager] Auto re-index stopped")

    async def _auto_reindex_loop(self):
        """Background loop for automatic re-indexing."""
        while True:
            try:
                await asyncio.sleep(REINDEX_INTERVAL_HOURS * 3600)

                # Check for data changes
                changes = await self.check_data_changes()
                if changes.get("has_changes", False):
                    print("[IndexManager] Data changes detected, triggering re-index")
                    await self.reindex(force=True, triggered_by="auto_scheduled")
                else:
                    print("[IndexManager] No data changes, skipping re-index")

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[IndexManager] Auto re-index error: {e}")
                await asyncio.sleep(60)  # Wait before retry

    def get_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent indexing history."""
        return self.index_history[-limit:][::-1]


# Singleton instance
index_manager = IndexManager()
