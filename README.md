# UCSI Buddy Chatbot

FastAPI + MongoDB + RAG(FAISS) + Google Gemini 기반 UCSI 대학 도메인 챗봇 프로젝트입니다.

**Version:** 3.4.0 | **Updated:** 2026-02-12

---

## 주요 변경사항 (v3.4.0)

- **다국어 임베딩 모델 교체**: Gemini text-embedding 제거 → `paraphrase-multilingual-MiniLM-L12-v2` (SentenceTransformer, 384차원, 한/영 동시 지원)
- **HuggingFace 오프라인 모드**: 서버 시작 시 네트워크 요청 없이 캐시된 모델만 사용 (`HF_HUB_OFFLINE=1`)
- **RAG-First 패턴**: `handle_llm_first_query`가 항상 RAG + MongoDB 병렬 검색 후 LLM 호출
- **MongoDB 직접 이름 검색**: 인물 쿼리에서 FAISS 벡터 검색과 병렬로 MongoDB regex 검색 (`search_by_name`)
- **보안 강화**: FAISS 인덱싱 시 Password, GPA, CGPA, DOB, STUDENT_NUMBER 필드 제외 (`_SENSITIVE_FIELDS`)
- **프론트엔드 Rich Content**: 건물 이미지(Google Drive 임베드), 지도/프로필 링크 채팅창 내 인라인 렌더링
- **라우팅 버그 수정**: `handle_llm_first_query` 호출 시 `user=user` 누락 2건 수정
- **Dead Code 정리**: `handle_general_query`, `handle_capability_query`, `_resolve_session` 제거

---

## 빠른 시작

```bash
# 1. 가상환경 생성/활성화
python -m venv .venv
.venv\Scripts\activate

# 2. 의존성 설치
pip install -r requirements.txt

# 3. .env 작성 (.env.example 참고)
# 필수: SECRET_KEY, MONGO_URI, GEMINI_API_KEY, ADMIN_PASSWORD

# 4. 실행
python main.py
```

접속:
- 메인 UI: `http://localhost:5000/`
- 관리자 UI: `http://localhost:5000/admin`
- API 문서 (Swagger): `http://localhost:5000/docs`

> **주의**: 모델 변경 후 첫 실행 시 FAISS 재인덱싱이 필요합니다.
> `data/knowledge_base/faiss_index.bin`, `faiss_metadata.pkl`을 삭제 후 재시작하세요.

---

## 프로젝트 구조

```
final/
├── main.py                    # FastAPI 메인 엔트리포인트 (HF 오프라인 모드 설정 포함)
├── main_fastapi.py            # 호환용 진입점
├── requirements.txt           # Python 의존성
├── .env                       # 환경변수 (SECRET_KEY, MONGO_URI, GEMINI_API_KEY 등)
│
├── app/
│   ├── config.py              # 설정 관리
│   ├── schemas.py             # Pydantic 모델
│   ├── extensions.py          # 인메모리 세션 저장소
│   │
│   ├── api/
│   │   ├── chat.py            # 메인 채팅 API (3-branch 라우팅)
│   │   ├── chat_helpers.py    # 채팅 헬퍼 함수 (포맷터, 검증, rich content)
│   │   ├── chat_legacy.py     # 이전 버전 백업
│   │   ├── auth.py            # 인증 (login, verify_password, logout)
│   │   ├── admin.py           # 관리자 API
│   │   └── dependencies.py   # FastAPI 의존성 (JWT 검증)
│   │
│   ├── engines/
│   │   ├── intent_config.py         # UCSI 키워드/엔티티 타입 통합 설정 (SSoT)
│   │   ├── intent_classifier.py     # 하이브리드 인텐트 분류기 (query_type, entity_type 감지)
│   │   ├── semantic_router_async.py # 벡터 기반 의도 라우팅 (SentenceTransformer)
│   │   ├── semantic_cache_engine.py # 시맨틱 응답 캐시 (SentenceTransformer)
│   │   ├── ai_engine_async.py       # LLM 엔진 (Gemini, 회로차단기, 속도제한)
│   │   ├── db_engine_async.py       # MongoDB 비동기 엔진 (Motor, search_by_name 포함)
│   │   ├── rag_engine.py            # RAG 코어 (FAISS 인덱싱/검색, 민감정보 필터링)
│   │   ├── rag_engine_async.py      # RAG 비동기 래퍼
│   │   ├── response_validator.py    # 응답 검증/할루시네이션 방지
│   │   ├── reranker.py              # Cross-Encoder 재순위화
│   │   ├── query_rewriter.py        # 쿼리 최적화/확장
│   │   ├── index_manager.py         # 인덱스 수명주기 관리
│   │   ├── monitoring.py            # 성능 메트릭 수집
│   │   ├── language_engine.py       # 다국어 감지 (en/ko/zh)
│   │   ├── faq_cache_engine.py      # FAQ 캐시
│   │   └── unanswered_analyzer.py   # 미답변 질문 분석
│   │
│   ├── core/
│   │   └── session.py         # 세션 관리 (대화기록, 고보안 세션)
│   │
│   └── utils/
│       ├── auth_utils.py      # JWT/비밀번호 유틸리티
│       └── logging_utils.py   # 감사 로깅 (PII 마스킹)
│
├── static/
│   ├── site/
│   │   ├── code_hompage.html  # 메인 챗봇 UI (rich content 렌더링 포함)
│   │   ├── css/styles.css
│   │   └── js/app.js
│   ├── images/                # 이미지 리소스
│   └── admin/
│       └── admin.html
│
├── data/
│   ├── knowledge_base/        # FAISS 인덱스 (faiss_index.bin, faiss_metadata.pkl)
│   ├── reference/             # DB 스키마, 백업 데이터
│   └── reports/               # QA/테스트 리포트 (CSV)
│
├── scripts/
│   ├── qa/                    # QA 스위트
│   ├── checks/                # 환경 점검
│   ├── debug/                 # 디버그 도구
│   └── run/                   # 실행 스크립트 (.bat)
│
├── test_cases/                # 테스트 데이터
└── docs/                      # 프로젝트 문서
```

---

## 핵심 아키텍처

### 인텐트 라우팅 (3-Branch)

```
사용자 메시지
    │
    ▼
[Branch 1] 개인정보 쿼리 감지 (_is_personal_query)
    ├─ "내 성적", "my profile", "내 GPA" 등
    └─ → handle_personal_query (JWT 필수, GPA는 2FA)
    │
    ▼ (매칭 없음)
[Branch 2] UCSI 키워드 감지 (has_ucsi_keywords)
    ├─ "hostel", "block", "fee", "programme", "pet", "schedule" 등
    ├─ query_type = aggregate → handle_llm_first_query
    └─ query_type = specific  → handle_ucsi_query (RAG 검색)
    │
    ▼ (매칭 없음)
[Branch 3] LLM-First (handle_llm_first_query)
    ├─ RAG 검색 + MongoDB 이름 검색 병렬 실행
    ├─ 데이터 있음 → 보안 체크 후 LLM 응답 생성
    └─ 데이터 없음 → LLM 일반 지식으로 응답
```

### 인텐트 분류 파이프라인 (handle_ucsi_query 내부)

```
UCSI 쿼리
    │
    ▼
[1] Keyword Guard (즉시 분류, 0ms)
    │
    ▼ (매칭 없음)
[2] SemanticRouter — SentenceTransformer 벡터 검색 (confidence ≥ 0.50)
    │  paraphrase-multilingual-MiniLM-L12-v2 (384차원, 한/영 동시 지원)
    │
    ▼ (낮은 confidence)
[3] LLM Fallback (Gemini gemma-3-27b-it)
    └─ 최종 분류 결정
```

### 카테고리별 처리

| 카테고리 | 처리 방식 | 인증 필요 |
|---------|----------|----------|
| personal_profile | MongoDB 학생 데이터 직접 조회 | JWT 필수 |
| personal_grade | MongoDB 학생 데이터 직접 조회 | JWT + 비밀번호 2FA |
| ucsi_hostel / ucsi_facility / ucsi_programme / ucsi_staff / ucsi_schedule | RAG(FAISS) → LLM | 불필요 |
| general_person / general_world | LLM 자유 응답 | 불필요 |
| capability_smalltalk | LLM 자유 응답 | 불필요 |

### 보안 계층

| 계층 | 내용 |
|------|------|
| Prompt Injection 탐지 | 12개 패턴 감지, 로깅 후 일반 처리 |
| 입력 Sanitization | HTML/스크립트 제거, 길이 2000자 제한 |
| 학생 데이터 접근 | 미로그인 시 login_hint 반환 |
| GPA/성적 2FA | `high_security_sessions`에 등록된 세션만 허용 |
| FAISS 민감정보 제외 | Password, GPA, CGPA, DOB, STUDENT_NUMBER 인덱싱 제외 |
| 응답 검증 | 숫자 검증, 할루시네이션 패턴 탐지, RAG 소스 grounding |
| RLHF 피드백 루프 | 긍정 피드백 → 학습, 부정 피드백 → 가드 레일 |

### Rich Content 렌더링

| 타입 | 트리거 | 렌더링 방식 |
|------|--------|-----------|
| 건물 이미지 | `entity_type = building` | Google Drive URL → 인라인 `<img>` |
| 지도 링크 | `MAP` 필드 존재 | 클릭 가능한 "View on Map" 버튼 |
| 직원 프로필 링크 | `entity_type = staff` | "View Profile" 버튼 |
| 프로그램 정보 링크 | `entity_type = programme` | "More Information" 버튼 |

---

## API 요약

### 인증

| Method | Endpoint | 설명 |
|--------|---------|------|
| POST | `/api/login` | 학생 로그인 (학번 + 이름) |
| POST | `/api/verify_password` | 비밀번호 검증 (2FA, 10분 유효) |
| POST | `/api/logout` | 로그아웃 |

### 채팅

| Method | Endpoint | 설명 |
|--------|---------|------|
| POST | `/api/chat` | 메인 채팅 (인증 선택적) |
| POST | `/api/feedback` | 피드백 (positive/negative) |
| GET | `/api/export_chat` | 대화 내보내기 (JWT 필수) |

### 관리자

| Method | Endpoint | 설명 |
|--------|---------|------|
| POST | `/api/admin/login` | 관리자 로그인 |
| GET | `/api/admin/stats` | 통계 조회 |
| POST | `/api/admin/upload` | 문서 업로드 (PDF/TXT/CSV) |
| POST | `/api/admin/reindex` | MongoDB 재인덱싱 |
| GET | `/api/admin/index/status` | 인덱스 상태 |
| POST | `/api/admin/index/reindex` | 수동 재인덱싱 |
| GET | `/api/admin/monitoring/dashboard` | 모니터링 대시보드 |
| GET | `/api/admin/unanswered/analysis` | 미답변 질문 분석 |
| GET | `/api/admin/health` | 헬스체크 (Public) |

---

## 환경 변수 (.env)

### 필수

| 변수 | 설명 |
|-----|------|
| `SECRET_KEY` | JWT 서명 키 (32바이트 hex 권장) |
| `MONGO_URI` | MongoDB Atlas 연결 문자열 |
| `GEMINI_API_KEY` | Google Gemini API 키 |
| `ADMIN_PASSWORD` | 관리자 비밀번호 |

### 선택 (RAG 튜닝)

| 변수 | 기본값 | 설명 |
|-----|-------|------|
| `GEMINI_MODEL` | `gemma-3-27b-it` | LLM 모델명 |
| `RAG_FAST_CONFIDENCE` | `0.72` | RAG 고신뢰 임계값 |
| `RAG_REWRITE_TRIGGER` | `0.68` | 쿼리 재작성 임계값 |
| `RAG_RERANK_TRIGGER` | `0.82` | 재순위화 임계값 |
| `SEMANTIC_ROUTER_MIN_CONFIDENCE` | `0.50` | SemanticRouter 최소 신뢰도 |
| `HF_HUB_OFFLINE` | `1` | HuggingFace 오프라인 모드 (캐시 모델만 사용) |
| `TRANSFORMERS_OFFLINE` | `1` | Transformers 오프라인 모드 |
| `AUTO_REINDEX_ENABLED` | `false` | 자동 재인덱싱 활성화 |
| `REINDEX_INTERVAL_HOURS` | `6` | 자동 재인덱싱 간격 (시간) |

---

## 실행 스크립트

```bash
# 서버 시작
start_fastapi.bat          # 루트 래퍼
scripts/run/start_fastapi.bat

# 재인덱싱 (모델 변경 후 필요)
scripts/reindex_rag.py

# 환경 점검
python scripts/verify_setup.py
python scripts/checks/check_server.py

# QA 테스트
python scripts/qa/strict_qa_suite.py --mode full
python scripts/qa/stress_test_runner.py
```

---

## 문서

| 파일 | 내용 |
|------|------|
| `docs/ARCHITECTURE_FASTAPI.md` | 아키텍처 상세 |
| `docs/SYSTEM_WORKFLOW.md` | 전체 워크플로우 |
| `docs/HANDOVER.md` | 인수인계 문서 |
| `docs/PROJECT_SPEC_V3_RAG_FIRST.md` | 제품/품질 스펙 |
| `docs/N8N_WORKFLOW_GUIDE.md` | n8n 연동 가이드 |
