"""
RAG Engine (Async-compatible Wrapper for Google GenAI New SDK)

Refactored to use `google-genai` (V1) instead of the deprecated `google-generativeai`.
This ensures long-term support and stability.
"""

from __future__ import annotations

import csv
import logging
import os
import pickle
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
import threading
import time

import numpy as np

# Suppress noisy logs
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

# Dependencies (New SDK)
try:
    import faiss
    from google import genai
    from google.genai import types
    HAS_DEPENDENCIES = True
except ImportError as e:
    HAS_DEPENDENCIES = False
    faiss = None
    genai = None
    types = None
    print(f"Warning: RAG dependencies missing ({e}). Install faiss-cpu google-genai")

try:
    from app.engines.query_rewriter import query_rewriter as _query_rewriter
except ImportError:
    _query_rewriter = None

try:
    from app.engines.reranker import reranker as _reranker
except ImportError:
    _reranker = None

# Configuration
KNOWLEDGE_BASE_DIR = Path("data/knowledge_base")
INDEX_FILE = KNOWLEDGE_BASE_DIR / "faiss_index.bin"
METADATA_FILE = KNOWLEDGE_BASE_DIR / "faiss_metadata.pkl"

# Configure Gemini Client
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
client = None

if GOOGLE_API_KEY and HAS_DEPENDENCIES:
    try:
        client = genai.Client(api_key=GOOGLE_API_KEY, http_options={'api_version': 'v1beta'})
    except Exception as e:
        print(f"[RAG] Failed to init Gemini Client: {e}")

TOKEN_RE = re.compile(r"[a-z0-9가-힣]{2,}")
FICTIONAL_OR_INVALID_KEYWORDS: Set[str] = {
    "ufo", "jedi", "spiderman", "moon campus", "mars campus", "teleport pad", "time machine", "alien faculty",
}

# --- DOMAIN CONSTANTS ---
DOMAIN_HINTS: Dict[str, Set[str]] = {
    "CampusBlocks": {"block", "building", "address", "location", "campus", "map", "where is"},
    "HostelFAQ": {"hostel faq", "refund", "installment", "policy", "guaranteed", "accommodation policy"},
    "Hostel": {"hostel", "dorm", "accommodation", "rent", "deposit", "room"},
    "Facility": {"facility", "library", "gym", "cafeteria", "pool", "laundry", "print", "printer", "prayer"},
    "Schedule": {"schedule", "calendar", "intake", "deadline", "event", "semester"},
    "Programme": {"programme", "program", "major", "course", "tuition", "fee", "fees", "scholarship", "foundation", "diploma", "degree", "master", "phd"},
    "Staff": {"staff", "lecturer", "professor", "dean", "advisor", "teacher", "faculty", "head"},
}

DOMAIN_RELATIONS: Dict[str, Set[str]] = {
    "HostelFAQ": {"Hostel"}, "Hostel": {"HostelFAQ"},
    "CampusBlocks": {"Facility"}, "Facility": {"CampusBlocks"},
    "Programme": {"Staff"}, "Staff": {"Programme"}, "Schedule": {"Programme"},
}

COLLECTION_TO_LABEL: Dict[str, str] = {
    "hostel": "Hostel", "ucsi_facility": "Facility", "usci_schedual": "Schedule",
    "ucsi_ major": "Programme", "ucsi_staff": "Staff", "ucsi_hostel_faq": "HostelFAQ",
    "ucsi_university_blocks_data": "CampusBlocks",
}

ALIAS_MAP: Dict[str, List[str]] = {
    "hostel": ["accommodation", "dorm"], "accommodation": ["hostel", "dorm"],
    "tuition": ["fee", "fees", "cost"], "fee": ["tuition", "cost", "price"],
    "programme": ["program", "major", "course"], "program": ["programme", "major", "course"],
    "lecturer": ["staff", "professor"], "professor": ["staff", "lecturer"],
    "library": ["facility", "opening hours"], "bus": ["shuttle", "route", "transport"],
    "route": ["bus", "shuttle", "transport"], "block": ["building", "address", "location"],
    # Pet/animal queries → expand to hostel policy context
    "pet": ["pet hostel rule", "pet policy", "keep pet hostel"],
    "dog": ["pet hostel rule", "pet policy", "animal hostel"],
    "cat": ["pet hostel rule", "pet policy", "animal hostel"],
    "animal": ["pet hostel rule", "pet policy", "keep animal hostel"],
    "breed": ["keep", "raise", "allowed hostel"],
    "애완동물": ["기숙사 반려동물", "애완동물 규정", "반려동물 정책"],
    "반려동물": ["기숙사 반려동물", "애완동물 규정", "기숙사 정책"],
}

def _tokenize(text: str) -> Set[str]:
    return set(TOKEN_RE.findall(str(text or "").lower()))

try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    SentenceTransformer = None
    print("[RAG] Warning: sentence-transformers not found via pip.")


class LocalEmbeddingWrapper:
    """Wrapper for local SentenceTransformer embeddings."""
    def __init__(self, model_name: str = "paraphrase-multilingual-MiniLM-L12-v2"):
        if SentenceTransformer:
             self.model = SentenceTransformer(model_name)
        else:
             self.model = None
             print("[RAG] SentenceTransformer failed to import.")

    def encode(self, sentences: List[str] | str, show_progress_bar: bool = False) -> np.ndarray:
        if not self.model:
             return np.array([[]])
        return self.model.encode(sentences, show_progress_bar=show_progress_bar)

    def get_sentence_embedding_dimension(self) -> int:
        if self.model:
            return self.model.get_sentence_embedding_dimension()
        return 384

# --- Helper Functions (Module Level) ---

def infer_preferred_labels(query: str) -> Set[str]:
    q = str(query or "").lower()
    preferred = set()
    for label, hints in DOMAIN_HINTS.items():
        if any(h in q for h in hints): preferred.add(label)
    return preferred

def expand_query_variants(query: str) -> List[str]:
    q = str(query or "").strip()
    if not q: return []
    ql = q.lower()
    alias_terms = []
    for trigger, aliases in ALIAS_MAP.items():
        if trigger in ql: alias_terms.extend(aliases)
    
    out = [q]
    if alias_terms:
        seen = set()
        norm = []
        for a in alias_terms:
            al = str(a).strip().lower()
            if al and al not in seen and al not in ql:
                seen.add(al)
                norm.append(al)
        if norm:
            out.append(f"{q} {' '.join(norm[:4])}")
            out.extend(norm[:6])
    
    deduped = []
    seen_final = set()
    for c in out:
        k = str(c).strip().lower()
        if k and k not in seen_final:
            seen_final.add(k)
            deduped.append(str(c).strip())
            if len(deduped) >= 7: break
    return deduped

def source_to_label(source: str, text: str = "") -> Optional[str]:
    sl = str(source or "").lower()
    for cname, label in COLLECTION_TO_LABEL.items():
        if cname in sl: return label
    m = re.search(r"\[([A-Za-z]+)\]", str(text or ""))
    if m:
        token = m.group(1).lower()
        tmap = {k.replace("_", "").lower(): v for k, v in COLLECTION_TO_LABEL.items()}
        tmap.update({v.lower(): v for v in COLLECTION_TO_LABEL.values()})
        return tmap.get(token)
    return None

def apply_domain_boost(score: float, label: Optional[str], preferred: Set[str]) -> float:
    if not preferred: return score
    if not label: return score * 0.60
    if label in preferred: return min(score * 1.40, 1.20)
    if any(label in DOMAIN_RELATIONS.get(t, set()) for t in preferred): return score
    return score * 0.60

def expand_domain_scope(preferred: Set[str], query: str = "") -> Set[str]:
    if not preferred: return set()
    expanded = set(preferred)
    q = str(query or "").lower()
    spec_fac = any(t in q for t in {"library", "gym", "cafeteria", "pool", "laundry", "print", "printer", "prayer"})
    for label in list(preferred):
        if label == "Facility" and spec_fac: continue
        expanded.update(DOMAIN_RELATIONS.get(label, set()))
    return expanded

def is_forced_no_data_query(query: str) -> bool:
    q = str(query or "").lower()
    return any(t in q for t in FICTIONAL_OR_INVALID_KEYWORDS)

def is_route_specific_query(query: str) -> bool:
    q = str(query or "").lower()
    return "route" in q and any(t in q for t in {"bus", "shuttle"})

def is_route_relevant_text(text: str) -> bool:
    t = str(text or "").lower()
    return any(k in t for k in {"route", "bus", "shuttle", "transport"})

def iter_campus_block_entries(doc: dict) -> List[dict]:
    entries = []
    campus_root = (doc or {}).get("campus")
    if not isinstance(campus_root, dict): return entries

    def _coerce(cname: str, payload: dict) -> Optional[dict]:
        if not isinstance(payload, dict): return None
        name = str(payload.get("Name") or "").strip()
        if not name: return None
        return {
            "campus_name": str(cname or "").strip(),
            "name": name,
            "address": str(payload.get("Address") or "").strip(),
            "map_url": str(payload.get("MAP") or "").strip(),
            "image_url": str(payload.get("BUILDING_IMAGE") or "").strip(),
            "latitude": payload.get("Latitude"),
            "longitude": payload.get("Longitude"),
        }

    for cname, payload in campus_root.items():
        if not isinstance(payload, dict): continue
        blocks = payload.get("blocks")
        if isinstance(blocks, list):
            for b in blocks:
                e = _coerce(str(cname), b)
                if e: entries.append(e)
        else:
            e = _coerce(str(cname), payload)
            if e: entries.append(e)
    return entries

def build_campus_block_text(entry: dict) -> str:
    parts = [f"campus: {entry.get('campus_name')}", f"name: {entry.get('name')}"]
    if entry.get("address"): parts.append(f"address: {entry.get('address')}")
    if entry.get("map_url"): parts.append(f"map: {entry.get('map_url')}")
    if entry.get("image_url"): parts.append(f"building_image: {entry.get('image_url')}")
    return f"[CampusBlocks] {' | '.join(parts)}"


class RAGEngine:
    def __init__(self) -> None:
        self.index = None
        self.metadata: List[Dict[str, Any]] = []
        self.model = None
        self.enabled = HAS_DEPENDENCIES and (SentenceTransformer is not None)
        # Using local sentence-transformers model (all-MiniLM-L6-v2)
        self.model_name = "all-MiniLM-L6-v2"
        self.dimension = 384
        self.metric_type = None

        if not self.enabled:
            print("[RAG] Disabled: Missing dependencies (sentence-transformers).")
            return

        try:
            self.model = LocalEmbeddingWrapper(self.model_name)
            self.dimension = self.model.get_sentence_embedding_dimension()
            self.metric_type = faiss.METRIC_INNER_PRODUCT
            self._load_index()
        except Exception as exc:
            print(f"[RAG] Init error: {exc}")
            self.enabled = False

    def _create_new_index(self) -> None:
        if not self.enabled: return
        self.index = faiss.IndexFlatIP(self.dimension)
        self.metadata = []

    def _load_index(self) -> None:
        if not self.enabled: return
        if INDEX_FILE.exists() and METADATA_FILE.exists():
            try:
                loaded = faiss.read_index(str(INDEX_FILE))
                if getattr(loaded, "d", None) != self.dimension:
                    print(f"[RAG] Dimension mismatch, rebuilding.")
                    self._create_new_index()
                    return
                with METADATA_FILE.open("rb") as handle:
                    metadata = pickle.load(handle)
                    self.metadata = metadata if isinstance(metadata, list) else []
                self.index = loaded
                print(f"[RAG] Loaded index ({self.index.ntotal} docs).")
                return
            except Exception: pass
        self._create_new_index()

    def _save_index(self) -> None:
        if not self.enabled or self.index is None: return
        KNOWLEDGE_BASE_DIR.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self.index, str(INDEX_FILE))
        with METADATA_FILE.open("wb") as handle:
            pickle.dump(self.metadata, handle)

    # --- Wrapper methods for backward compatibility ---
    def _infer_preferred_labels(self, query: str) -> Set[str]:
        return infer_preferred_labels(query)

    def _expand_query_variants(self, query: str) -> List[str]:
        return expand_query_variants(query)

    def _source_to_label(self, source: str, text: str = "") -> Optional[str]:
        return source_to_label(source, text)

    def _apply_domain_boost(self, score: float, label: Optional[str], preferred: Set[str]) -> float:
        return apply_domain_boost(score, label, preferred)

    def _expand_domain_scope(self, preferred: Set[str], query: str = "") -> Set[str]:
        return expand_domain_scope(preferred, query)

    def _is_forced_no_data_query(self, query: str) -> bool:
        return is_forced_no_data_query(query)

    def _is_route_specific_query(self, query: str) -> bool:
        return is_route_specific_query(query)

    def _is_route_relevant_text(self, text: str) -> bool:
        return is_route_relevant_text(text)

    def _iter_campus_block_entries(self, doc: dict) -> List[dict]:
        return iter_campus_block_entries(doc)

    def _build_campus_block_text(self, entry: dict) -> str:
        return build_campus_block_text(entry)

    # --- Ingestion ---
    def ingest_file(self, file_path: str) -> bool:
        if not self.enabled or not self.index or not self.model: return False
        path = Path(file_path)
        if not path.exists(): return False
        try:
            ext = path.suffix.lower()
            text = ""
            if ext == ".pdf":
                try:
                    import PyPDF2
                    with path.open("rb") as f:
                        reader = PyPDF2.PdfReader(f)
                        for p in reader.pages: text += (p.extract_text() or "") + "\n"
                except: return False
            elif ext == ".txt":
                text = path.read_text(encoding="utf-8", errors="ignore")
            elif ext == ".csv":
                rows = []
                with path.open("r", encoding="utf-8", errors="ignore") as f:
                    reader = csv.reader(f)
                    for r in reader: rows.append(",".join(str(c) for c in r))
                text = "\n".join(rows)
            else: return False
            
            if not text.strip(): return False
            
            chunk_size = 600
            step = 500
            chunks = []
            for i in range(0, len(text), step):
                c = text[i:i+chunk_size].strip()
                if len(c) >= 50: chunks.append(c)
            
            if not chunks: return False
            
            embs = self.model.encode(chunks).astype("float32")
            if self.metric_type == faiss.METRIC_INNER_PRODUCT:
                faiss.normalize_L2(embs)
            self.index.add(embs)
            for c in chunks: self.metadata.append({"text": c, "source": path.name})
            self._save_index()
            return True
        except Exception as e:
            print(f"[RAG] Ingest error: {e}")
            return False
            
    def rebuild_index_with_mongo_entries(self, texts: List[str], meta_entries: List[Dict]) -> int:
        if not self.enabled or not self.model: return 0
        try:
            safe_texts = [str(t) for t in (texts or []) if str(t).strip()]
            safe_meta = []
            for i, _ in enumerate(safe_texts):
                base = meta_entries[i] if i < len(meta_entries) else {}
                m = dict(base) if isinstance(base, dict) else {}
                m["text"] = safe_texts[i]
                m.setdefault("source", "MongoDB:unknown")
                safe_meta.append(m)
            
            preserved = [it for it in self.metadata if isinstance(it, dict) and not str(it.get("source") or "").startswith("MongoDB:")]
            
            rebuilt_texts = [str(it.get("text")) for it in preserved] + safe_texts
            rebuilt_meta = preserved + safe_meta
            
            self._create_new_index()
            if not self.index: return 0
            
            if rebuilt_texts:
                embs = self.model.encode(rebuilt_texts).astype("float32")
                if self.metric_type == faiss.METRIC_INNER_PRODUCT:
                    faiss.normalize_L2(embs)
                self.index.add(embs)
                
            self.metadata = rebuilt_meta
            self._save_index()
            print(f"[RAG] Rebuilt index: {len(self.metadata)} items.")
            return len(safe_texts)
        except Exception as e:
            print(f"[RAG] Rebuild error: {e}")
            return 0

    # --- Search ---
    def search(self, query: str, n_results: int = 3, preferred_labels: List[str] = None) -> dict:
        q = str(query or "").strip()
        if not q or is_forced_no_data_query(q):
            return {"context": "[NO_DATA]", "has_relevant_data": False, "confidence": 0.0, "sources": []}
            
        variants = expand_query_variants(q) or [q]
        if _query_rewriter:
            try:
                rw = _query_rewriter.rewrite(q)
                if rw.get("search_queries"):
                    variants = list(set([q] + rw["search_queries"] + variants))[:7]
            except: pass
            
        pref = set(preferred_labels or [])
        pref.update(infer_preferred_labels(q))
        
        results = []
        if self.enabled and self.index and self.index.ntotal > 0:
            try:
                q_vecs = self.model.encode(variants[:3]).astype("float32")
                if self.metric_type == faiss.METRIC_INNER_PRODUCT:
                    faiss.normalize_L2(q_vecs)
                
                D, I = self.index.search(q_vecs, k=max(5, n_results * 2))
                
                for q_idx, _ in enumerate(variants[:3]):
                    for i, idx in enumerate(I[q_idx]):
                        if idx < 0 or idx >= len(self.metadata): continue
                        meta = self.metadata[idx]
                        text = str(meta.get("text") or "")
                        score = float(D[q_idx][i])
                        
                        src = str(meta.get("source") or "doc")
                        lbl = source_to_label(src, text)
                        
                        boosted = apply_domain_boost(score, lbl, pref)
                        if boosted > 0.3: results.append((text, boosted, src, lbl))
            except Exception as e: print(f"[RAG] Search error: {e}")
            
        if not results:
             return {"context": "[NO_DATA]", "has_relevant_data": False, "confidence": 0.0, "sources": []}
             
        deduped = {}
        for t, s, src, l in results:
            k = (t, src)
            if s > deduped.get(k, (0,0,0,0))[1]: deduped[k] = (t, s, src, l)
            
        ranked = sorted(deduped.values(), key=lambda x: x[1], reverse=True)
        
        if _reranker and len(ranked) > 5:
            try:
                # Lightweight rerank
                dt = [r[0] for r in ranked[:10]]
                rr = _reranker.rerank(q, dt)
                # Just use reranker sort order for top results
                new_ranked = []
                for _, _, rscore in rr:
                    # Find original match
                    pass 
                # Improving rerank integration:
                # The lightweight reranker returns (orig_idx, doc, score)
                # We should re-order based on that
                rerank_map = {doc: sc for _, doc, sc in rr}
                for i, r in enumerate(ranked):
                     r_score = rerank_map.get(r[0], 0.0)
                     # Combine scores: 70% vector, 30% keyword
                     final = (r[1] * 0.7) + (r_score * 0.3)
                     ranked[i] = (r[0], final, r[2], r[3])
                ranked.sort(key=lambda x: x[1], reverse=True)
            except: pass
            
        top_k = ranked[:n_results]
        conf = top_k[0][1] if top_k else 0.0
        
        ctx = "\n".join([f"[{r[3] or 'Doc'}] {r[0]} (conf:{r[1]:.2f})" for r in top_k])
        srcs = list(set([r[2] for r in top_k]))
        
        return {"context": ctx, "has_relevant_data": conf > 0.45, "confidence": conf, "sources": srcs}

rag_engine = RAGEngine()
