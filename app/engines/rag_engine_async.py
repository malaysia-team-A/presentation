"""
Async RAG Engine - High-performance asynchronous Orchestrator for RAG.

This module provides a fully asynchronous interface for the RAG engine,
integrating MongoDB Atlas data collection with FAISS vector search.
Calculations (embeddings/FAISS) are offloaded to a thread pool to avoid 
blocking the FastAPI event loop.
"""

import asyncio
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple

from app.engines.db_engine_async import db_engine_async
from app.engines.rag_engine import (
    rag_engine as _sync_rag_engine,
    infer_preferred_labels,
    expand_query_variants,
    source_to_label,
    apply_domain_boost,
    is_forced_no_data_query,
    iter_campus_block_entries,
    build_campus_block_text
)

# Configuration for indexing
_MONGO_COLLECTIONS_CONFIG: List[Dict[str, Any]] = [
    {
        "name": "Hostel",
        "aliases": ["HOSTEL"],
        "fields": ["room_type", "building", "campus", "category", "rent_price", "deposit", "features"],
        "label": "Hostel",
    },
    {
        "name": "UCSI_FACILITY",
        "aliases": ["UCSI_FACILITIES"],
        "fields": ["name", "location", "category", "opening_hours", "price_info", "tags"],
        "label": "Facility",
    },
    {
        "name": "UCSI_ MAJOR",
        "aliases": ["UCSI_MAJOR", "UCSI_MAJORS"],
        "fields": [
            "Programme",
            "Fields of Study",
            "Course Duration",
            "Course Mode",
            "Course Location",
            "Intakes",
            "Local Students Fees",
            "International Students Fees",
            "Programme Overview",
        ],
        "label": "Programme",
    },
    {
        "name": "USCI_SCHEDUAL",
        "aliases": ["UCSI_SCHEDUAL", "UCSI_SCHEDULE", "UCSI_SCHEDULES"],
        "fields": ["event_name", "event_type", "start_date", "end_date", "programme", "campus_scope"],
        "label": "Schedule",
    },
    {
        "name": "UCSI_STAFF",
        "aliases": ["UCSI_STAFFS"],
        "fields": ["major", "staff_members"],
        "label": "Staff",
    },
    {
        "name": "UCSI_HOSTEL_FAQ",
        "aliases": ["UCSI_HOSTEL_FAQS"],
        "fields": ["question", "answer", "category", "tags"],
        "label": "HostelFAQ",
    },
    {
        "name": "UCSI_University_Blocks_Data",
        "aliases": ["UCSI_UNIVERSITY_BLOCKS_DATA"],
        "fields": ["campus"],
        "label": "CampusBlocks",
    },
    {
        "name": "UCSI",
        "aliases": ["STUDENT", "STUDENTS", "UCSI_STUDENT"],
        "fields": [
            "STUDENT_NAME", "student_name", "Student_Name", "Name", "name",
            "PROGRAMME_NAME", "programme_name", "Programme_Name", "Programme",
            "INTAKE", "DEPARTMENT", "Agama", "Gender"
        ],
        "label": "Student",
    },
]


class AsyncRAGEngine:
    def __init__(self):
        # Thread pool for CPU-bound tasks (SentenceTransformers, FAISS)
        self.executor = ThreadPoolExecutor(max_workers=4)
        # Use the underlying sync engine for shared index and model instances
        self.sync_engine = _sync_rag_engine
        print("[AsyncRAG] Native Async RAG Engine Initialized")

    async def _collect_mongo_index_payload(self) -> Tuple[List[str], List[Dict[str, Any]]]:
        """Collect and format text data from MongoDB collections asynchronously."""
        db = db_engine_async.db
        if db is None:
            return [], []

        mongo_texts: List[str] = []
        mongo_metadata_entries: List[Dict[str, Any]] = []
        
        try:
            collection_names = set(await db.list_collection_names())
        except Exception as e:
            print(f"[AsyncRAG] Error listing collections: {e}")
            return [], []

        for config in _MONGO_COLLECTIONS_CONFIG:
            coll_name = str(config["name"])
            aliases = config.get("aliases") or []
            candidate_names = [coll_name] + aliases
            
            matched_collection = next((n for n in candidate_names if n in collection_names), None)
            if not matched_collection:
                continue

            try:
                # Use async cursor for memory-efficient iteration
                cursor = db[matched_collection].find({}, {"_id": 0})
                doc_count = 0
                
                async for doc in cursor:
                    if coll_name == "UCSI_University_Blocks_Data":
                        # Specialized handling for CampusBlocks
                        for entry in iter_campus_block_entries(doc):
                            full_text = build_campus_block_text(entry)
                            if len(full_text) > 50:
                                mongo_texts.append(full_text)
                                mongo_metadata_entries.append({
                                    "text": full_text,
                                    "source": f"MongoDB:{matched_collection}",
                                    "type": "collection",
                                })
                                doc_count += 1
                        continue

                    # General field extraction
                    fields = config.get("fields") or []
                    label = config.get("label") or "Document"
                    text_parts = [f"[{label}]"]
                    
                    for field in fields:
                        if field not in doc:
                            continue
                        val = doc[field]
                        if isinstance(val, str):
                            text_parts.append(f"{field}: {val}")
                        elif isinstance(val, (int, float)):
                            text_parts.append(f"{field}: {val}")
                        elif isinstance(val, list):
                            # Special handling for staff members nested list
                            if field == "staff_members":
                                for member in val[:10]:
                                    if isinstance(member, dict):
                                        m_parts = [
                                            f"{k}: {member.get(k)}"
                                            for k in ("name", "role", "email", "profile_url")
                                            if member.get(k)
                                        ]
                                        if m_parts:
                                            text_parts.append("[staff] " + " | ".join(m_parts))
                            else:
                                text_parts.append(f"{field}: {', '.join(map(str, val[:5]))}")

                    # Add other fields not in mapping but are primitives
                    # NEVER index sensitive fields regardless of collection
                    _SENSITIVE_FIELDS = {"password", "Password", "gpa", "GPA", "cgpa", "CGPA",
                                         "dob", "DOB", "date_of_birth", "STUDENT_NUMBER", "student_number"}
                    for k, v in doc.items():
                        if k not in fields and k not in _SENSITIVE_FIELDS and isinstance(v, (str, int, float)):
                            text_parts.append(f"{k}: {v}")

                    full_text = " | ".join(text_parts)
                    if len(full_text) > 50:
                        mongo_texts.append(full_text)
                        mongo_metadata_entries.append({
                            "text": full_text,
                            "source": f"MongoDB:{matched_collection}",
                            "type": "collection",
                        })
                        doc_count += 1
                
                if doc_count > 0:
                    print(f"[AsyncRAG] Indexed {doc_count} entries from {matched_collection}")
                    
            except Exception as e:
                print(f"[AsyncRAG] Error processing collection {matched_collection}: {e}")
                continue

        return mongo_texts, mongo_metadata_entries

    async def search_context(
        self,
        query: str,
        top_k: int = 5,
        preferred_labels: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Perform vector search with async orchestration.
        Offloads blocking FAISS and embedding tasks to the thread pool.
        """
        if not self.sync_engine.enabled:
            return {"context": "[NO_DATA]", "has_relevant_data": False, "confidence": 0.0, "sources": []}

        # Step 1: Pre-processing (Fast, run in main loop)
        q = str(query or "").strip()
        if not q or is_forced_no_data_query(q):
            return {"context": "[NO_DATA]", "has_relevant_data": False, "confidence": 0.0, "sources": []}

        # Use the sync engine's search method for consistency, but run it in executor
        # We could also replicate the granular steps here if we wanted more mid-stage async hooks.
        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(
                self.executor,
                lambda: self.sync_engine.search(
                    query=q,
                    n_results=top_k,
                    preferred_labels=preferred_labels
                )
            )
            return result
        except Exception as e:
            print(f"[AsyncRAG] Search failed: {e}")
            return {"context": "[ERROR]", "has_relevant_data": False, "confidence": 0.0, "sources": []}

    async def index_mongodb_collections(self) -> int:
        """Fetch all data from MongoDB and rebuild the FAISS index."""
        db = db_engine_async.db
        if db is None:
            print("[AsyncRAG] MongoDB not connected, skipping indexing")
            return 0

        # Step 1: Async data collection (Non-blocking I/O)
        mongo_texts, mongo_metadata = await self._collect_mongo_index_payload()
        if not mongo_texts:
            return 0

        # Step 2: Rebuild Index (Blocking CPU/IO offloaded to thread)
        loop = asyncio.get_running_loop()
        try:
            count = await loop.run_in_executor(
                self.executor,
                lambda: self.sync_engine.rebuild_index_with_mongo_entries(mongo_texts, mongo_metadata)
            )
            return count
        except Exception as e:
            print(f"[AsyncRAG] Reindex failed: {e}")
            return 0

    async def add_document(self, text: str, source: str) -> bool:
        """Add a raw text document to the index asynchronously."""
        filename = os.path.basename(str(source or "uploaded.txt"))
        suffix = os.path.splitext(filename)[1].lower() or ".txt"
        if suffix not in {".txt", ".csv"}:
            suffix = ".txt"

        tmp_path = None
        try:
            # Creation of temp file is blocking but fast; could be moved to thread if needed.
            with tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False, encoding="utf-8") as tmp:
                tmp.write(str(text or ""))
                tmp_path = tmp.name
            return await self.ingest_file(tmp_path)
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass

    async def ingest_file(self, file_path: str) -> bool:
        """Ingest a file (PDF, TXT, CSV) into the RAG index asynchronously."""
        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(
                self.executor,
                self.sync_engine.ingest_file,
                file_path
            )
        except Exception as e:
            print(f"[AsyncRAG] Ingest failed: {e}")
            return False

    async def get_index_info(self) -> Dict[str, Any]:
        """Get information about the current FAISS index asynchronously."""
        if not self.sync_engine.enabled:
            return {
                "enabled": False,
                "document_count": 0,
                "index_loaded": False,
                "model_name": None,
                "dimension": 0,
            }

        # Accessing metadata is fast (in-memory)
        metadata = self.sync_engine.metadata
        index = self.sync_engine.index

        source_counts: Dict[str, int] = {}
        for item in metadata:
            if isinstance(item, dict):
                src = str(item.get("source") or "unknown").lower()
                if src.startswith("mongodb:"): key = "mongodb"
                elif src.endswith(".pdf"): key = "pdf"
                elif src.endswith(".txt"): key = "txt"
                elif src.endswith(".csv"): key = "csv"
                else: key = "other"
                source_counts[key] = source_counts.get(key, 0) + 1

        return {
            "enabled": True,
            "document_count": len(metadata),
            "index_loaded": index is not None,
            "index_size": getattr(index, "ntotal", 0) if index else 0,
            "model_name": self.sync_engine.model_name,
            "dimension": self.sync_engine.dimension,
            "source_breakdown": source_counts,
        }


# Singleton instance
rag_engine_async = AsyncRAGEngine()
