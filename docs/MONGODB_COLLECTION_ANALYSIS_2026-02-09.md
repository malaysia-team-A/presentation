# MongoDB Collection Analysis (2026-02-09)

## Scope
- Schema source: `UCSI_DB_10_02_2026.json`
- Live DB source: `MONGO_URI` target `UCSI_DB` (runtime query snapshot)
- Code scan scope:
  - `app/engines/db_engine_async.py`
  - `app/engines/rag_engine_async.py`
  - `app/engines/semantic_router_async.py`
  - `app/api/chat.py`
  - `app/api/admin.py`
  - `app/api/auth.py`

## 1) Schema Export (`UCSI_DB_10_02_2026.json`)
- File structure is schema-centric:
  - top-level keys: `collections`, `relationships`
  - each collection entry contains `ns` + `jsonSchema`
  - `relationships` is empty
- This file does not include document payloads/counts.

Schema collection names:
- `UCSI_DB.BadQA`
- `UCSI_DB.Feedback`
- `UCSI_DB.Hostel`
- `UCSI_DB.LearnedQA`
- `UCSI_DB.UCSI`
- `UCSI_DB.UCSI_ MAJOR`
- `UCSI_DB.UCSI_FACILITY`
- `UCSI_DB.UCSI_HOSTEL_FAQ`
- `UCSI_DB.UCSI_STAFF`
- `UCSI_DB.UCSI_University_Blocks_Data`
- `UCSI_DB.USCI_SCHEDUAL`
- `UCSI_DB.feedbacks`
- `UCSI_DB.semantic_intents`
- `UCSI_DB.unanswered`

## 2) Live DB Snapshot (`UCSI_DB`)
Collection counts at analysis time:
- `UCSI`: `500`
- `UCSI_ MAJOR`: `107`
- `USCI_SCHEDUAL`: `86`
- `semantic_intents`: `60`
- `unanswered`: `35`
- `UCSI_STAFF`: `17`
- `Feedback`: `14`
- `Hostel`: `7`
- `UCSI_FACILITY`: `5`
- `UCSI_HOSTEL_FAQ`: `4`
- `BadQA`: `2`
- `LearnedQA`: `1`
- `UCSI_University_Blocks_Data`: `1`
- `feedbacks`: missing in live DB

## 3) Current Runtime Collection Usage

### 3.1 Canonical collections (active runtime path)
- `Feedback`
  - user feedback storage
  - learned positive-memory retrieval
  - bad-answer guard signal
  - RLHF policy signal aggregation
- `unanswered`
  - no-data / miss logging
- `semantic_intents`
  - semantic intent vector router
- student collection (auto-detected):
  - preferred: `UCSI`, fallback candidates `students`, `Students`, `UCSI_STUDENTS`
- RAG domain data:
  - `Hostel`
  - `UCSI_FACILITY`
  - `UCSI_ MAJOR`
  - `USCI_SCHEDUAL`
  - `UCSI_STAFF`
  - `UCSI_HOSTEL_FAQ`
  - `UCSI_University_Blocks_Data`

### 3.2 Optional legacy fallbacks (disabled by default)
- `feedbacks`
  - enabled only when `USE_LEGACY_FEEDBACK_COLLECTION=true`
- `LearnedQA`, `BadQA`
  - enabled only when `USE_LEGACY_QA_COLLECTIONS=true`

## 4) What Was Fixed in Code
- FastAPI async path retained as single runtime architecture.
- Sync Mongo engine removed (`app/engines/db_engine.py` already deleted in project state).
- `rag_engine.py` rebuilt into parser-safe sync FAISS core used only via async wrapper.
- `db_engine_async.py` changed to canonical-feedback design:
  - default runtime does not depend on `feedbacks/LearnedQA/BadQA`
  - legacy reads/writes are opt-in via env flags
- `rag_engine_async.py` now supports collection aliases for naming variants:
  - helps avoid misses from typo/spacing variants (e.g., schedule/major names)

## 5) Migration/Operational Note
- Added `scripts/db/migrate_legacy_qa_to_feedback.py`
  - migrates `LearnedQA/BadQA` signals into `Feedback`-compatible records
  - run once before fully disabling legacy collection reads in production
