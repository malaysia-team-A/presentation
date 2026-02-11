# UCSI Buddy 챗봇 업데이트 로그

**날짜:** 2026-02-10
**버전:** 3.1.0

---

## 1. 개요

이번 업데이트에서는 프로젝트 요구사항(project_plan.pdf)에 맞춰 다음 기능들을 구현/개선했습니다:

- 하이브리드 인텐트 분류기
- 할루시네이션 방지
- Self-Learning 시스템 강화
- 성능 모니터링
- UX 개선
- 보안 강화 (Prompt Injection 방지)
- 코드 구조 통합

---

## 2. 새로 추가된 파일

### 2.1 엔진 (app/engines/)

| 파일 | 설명 |
|-----|------|
| `intent_classifier.py` | 하이브리드 인텐트 분류기 (Keyword Guard → Vector Search → LLM Fallback) |
| `response_validator.py` | 할루시네이션 방지 및 응답 검증 |
| `ux_engine.py` | UX 개선 (인사말, 에러 메시지, 응답 포맷팅) |
| `index_manager.py` | RAG 인덱스 자동 관리 및 재인덱싱 |
| `monitoring.py` | 성능 모니터링 (응답 시간, RAG hit rate, LLM 사용량) |
| `unanswered_analyzer.py` | 미답변 질문 분석 및 리포트 생성 |
| `semantic_router_async.py` | 시맨틱 라우터 (SentenceTransformer 기반) |

### 2.2 테스트 (scripts/tests/)

| 파일 | 설명 |
|-----|------|
| `test_integration.py` | 통합 테스트 (DB, LLM, RAG, E2E) |
| `test_security.py` | 보안 테스트 (Prompt Injection, Sanitization) |
| `test_ux.py` | UX 테스트 (Greeting, Error Messages) |
| `run_all_tests.py` | 전체 테스트 러너 |

### 2.3 문서 (docs/)

| 파일 | 설명 |
|-----|------|
| `N8N_WORKFLOW_GUIDE.md` | n8n 워크플로우 가이드 |
| `UPDATE_LOG_2026-02-10.md` | 이 문서 |

---

## 3. 수정된 파일

### 3.1 main.py
- `USE_CHAT_V2` 환경변수 분기 로직 제거
- `chat.py` 단일 모듈로 통합

```python
# Before
USE_CHAT_V2 = os.getenv("USE_CHAT_V2", "false").lower() in ("true", "1", "yes")
if USE_CHAT_V2:
    import app.api.chat_v2 as chat
else:
    import app.api.chat as chat

# After
import app.api.chat as chat  # Unified chat module
```

### 3.2 app/api/chat.py (구 chat_v2.py)
- 하이브리드 인텐트 분류기 통합
- Prompt Injection 탐지 및 입력 Sanitization
- Response Validation (할루시네이션 방지)
- 성능 모니터링 (Monitor) 통합
- 코드 라인 수: ~800줄 → ~550줄 (30% 감소)

### 3.3 app/api/admin.py
새 엔드포인트 추가:
- `GET /api/admin/index/status` - 인덱스 상태 조회
- `POST /api/admin/index/reindex` - 수동 재인덱싱
- `GET /api/admin/index/history` - 인덱싱 히스토리
- `GET /api/admin/index/changes` - 데이터 변경 감지
- `GET /api/admin/monitoring/dashboard` - 모니터링 대시보드
- `GET /api/admin/unanswered/analysis` - 미답변 질문 분석
- `GET /api/admin/unanswered/report` - 미답변 리포트
- `GET /api/admin/health` - 헬스체크

### 3.4 app/engines/rag_engine_async.py
- `get_index_info()` 메서드 추가 - 인덱스 상태 정보 반환

### 3.5 app/engines/ai_engine_async.py
- 긴 대화 요약 기능 추가 (토큰 절약)
- 프롬프트 개선 (Grounding 지침 강화)

---

## 4. 아키텍처 변경

### 4.1 인텐트 분류 흐름 (Hybrid Classifier)

```
사용자 메시지
    │
    ▼
[1] Keyword Guard (빠른 분류)
    ├─ 개인정보 키워드 → personal
    ├─ 능력 질문 → capability
    ├─ UCSI 키워드 → ucsi_domain (force RAG)
    │
    ▼ (매칭 없음)
[2] Vector Search (SentenceTransformer)
    ├─ confidence >= 0.65 → 분류 결과 사용
    │
    ▼ (낮은 confidence)
[3] LLM Fallback (Gemini)
    └─ 최종 분류 결정
```

### 4.2 Self-Learning 흐름

```
[문서 업로드]
Admin → /admin/upload → rag_engine.ingest_file() → FAISS 벡터화

[Positive 피드백]
사용자 👍 → save_learned_response() → Feedback 컬렉션
→ 다음에 같은 질문 시 바로 응답

[Negative 피드백]
사용자 👎 → save_bad_response() → BadResponse 컬렉션
→ feedback_guard로 해당 응답 재사용 방지

[미답변 질문]
Low confidence → log_unanswered() → unanswered 컬렉션
→ unanswered_analyzer로 분석 → Admin이 데이터 추가
```

### 4.3 응답 검증 흐름 (Hallucination Prevention)

```
LLM 응답 생성
    │
    ▼
Response Validator
    ├─ 숫자 검증 (Context와 일치 여부)
    ├─ 소스 기반 검증
    ├─ Grounding 검사
    │
    ├─ Valid → 응답 반환
    └─ Invalid → Safe Response 생성 + 로깅
```

---

## 5. API 엔드포인트 요약

### 5.1 Chat API (`/api`)
| Method | Endpoint | 설명 |
|--------|----------|------|
| POST | `/chat` | 채팅 메시지 처리 |
| POST | `/feedback` | 피드백 저장 (RLHF) |
| GET | `/export_chat` | 대화 내보내기 |

### 5.2 Auth API (`/api`)
| Method | Endpoint | 설명 |
|--------|----------|------|
| POST | `/login` | 학생 로그인 |
| POST | `/verify-password` | 비밀번호 검증 (성적 조회용) |
| POST | `/logout` | 로그아웃 |

### 5.3 Admin API (`/api/admin`)
| Method | Endpoint | 설명 |
|--------|----------|------|
| POST | `/login` | 관리자 로그인 |
| GET | `/stats` | 통계 조회 |
| POST | `/upload` | 문서 업로드 |
| GET | `/files` | 파일 목록 |
| DELETE | `/files` | 파일 삭제 |
| GET | `/index/status` | 인덱스 상태 |
| POST | `/index/reindex` | 재인덱싱 |
| GET | `/monitoring/dashboard` | 모니터링 |
| GET | `/unanswered/analysis` | 미답변 분석 |
| GET | `/health` | 헬스체크 |

---

## 6. 테스트 실행 방법

```bash
# 전체 테스트
python scripts/tests/run_all_tests.py --verbose

# 개별 테스트
python scripts/tests/test_integration.py --test db
python scripts/tests/test_security.py
python scripts/tests/test_ux.py
```

---

## 7. 환경 변수

### 필수
| 변수 | 설명 |
|-----|------|
| `MONGO_URI` | MongoDB 연결 문자열 |
| `GEMINI_API_KEY` | Google Gemini API 키 |
| `JWT_SECRET_KEY` | JWT 시크릿 키 |
| `ADMIN_PASSWORD` | 관리자 비밀번호 |

### 선택 (기본값 있음)
| 변수 | 기본값 | 설명 |
|-----|-------|------|
| `GEMINI_MODEL` | `gemma-3-27b-it` | LLM 모델 |
| `RAG_EMBEDDING_MODEL` | `paraphrase-multilingual-MiniLM-L12-v2` | 임베딩 모델 |
| `AUTO_REINDEX_ENABLED` | `false` | 자동 재인덱싱 |
| `REINDEX_INTERVAL_HOURS` | `6` | 재인덱싱 주기 |

---

## 8. 파일 구조

```
app/
├── api/
│   ├── chat.py           # 통합 채팅 API (하이브리드 분류기)
│   ├── chat_legacy.py    # 백업 (구 chat.py)
│   ├── chat_helpers.py   # 헬퍼 함수
│   ├── auth.py           # 인증 API
│   ├── admin.py          # 관리자 API
│   └── dependencies.py
├── engines/
│   ├── ai_engine_async.py      # LLM 엔진 (Gemini)
│   ├── db_engine_async.py      # DB 엔진 (MongoDB)
│   ├── rag_engine.py           # RAG 엔진 (동기)
│   ├── rag_engine_async.py     # RAG 엔진 (비동기)
│   ├── intent_classifier.py    # 하이브리드 분류기
│   ├── semantic_router_async.py # 시맨틱 라우터
│   ├── response_validator.py   # 응답 검증
│   ├── ux_engine.py            # UX 엔진
│   ├── index_manager.py        # 인덱스 관리
│   ├── monitoring.py           # 모니터링
│   └── unanswered_analyzer.py  # 미답변 분석
├── core/
│   └── session.py        # 세션 관리
├── schemas.py            # Pydantic 스키마
└── config.py             # 설정

scripts/
├── tests/
│   ├── test_integration.py
│   ├── test_security.py
│   ├── test_ux.py
│   └── run_all_tests.py
└── ...

docs/
├── UPDATE_LOG_2026-02-10.md  # 이 문서
└── ...
```

---

## 9. 다음 단계 (TODO)

- [ ] MongoDB Atlas Vector Search 통합 (선택사항)
- [ ] pytest 기반 테스트 전환
- [ ] CI/CD 파이프라인 구축
- [ ] 프론트엔드 개선

---

## 11. 심층 분석 및 향후 개선 계획 (Pragmatic Improvement Plan)

오늘 진행된 코드베이스 심층 분석을 통해 확인된 리스크와 이를 해결하기 위한 실용적인 개선 계획입니다.

### 11.1 주요 분석 결과
- **세션 및 대화 기록의 휘발성**: 현재 대화 기록과 고보안 세션이 인메모리(`session.py`)에만 저장되어 있어, 서버 재시작 시 데이터가 유실되고 다중 프로세스 환경에서 세션 공유가 불가능함.
- **RAG 인덱싱 확장성**: 서버 시작 시 모든 MongoDB 문서를 메모리로 로드하여 인덱싱함. 데이터 증가 시 부팅 속도 저하 및 OOM(Out Of Memory) 위험이 있음.
- **검색 로직의 비효율성**: 학습된 답변(Learned Response) 검색 시 Python 루프를 통한 유사도 비교를 수행하여 CPU 부하 및 응답 속도 저하 발생 가능.
- **모니터링 데이터 유실**: 성능 지표가 메모리에만 기록되어 재시작 시 히스토리 확인 불가.

### 11.2 향후 개선 단계 (제안됨)

#### Phase 1: 확장성 및 안정성 확보 (Shared Sessions)
- **세션 DB화**: 세션 데이터를 MongoDB에 저장하고 1시간 뒤 자동 삭제(TTL)되도록 설정.
- **효과**: 서버 재시작 시에도 흐름 유지, 다중 CPU 프로세싱 지원, 휘발성 유지.

#### Phase 2: 검색 성능 최적화 (Keeping Accuracy)
- **RAG 시동 속도 개선**: FAISS 인덱스를 디스크에 캐싱하여 부팅 속도를 1초 이내로 단축.
- **DB 기반 텍스트 검색**: Python 루프 대신 MongoDB의 `$text` 인덱스 검색을 활용하여 검색 속도 및 정확도 향상.

#### Phase 3: 품질 및 가시성 개선
- **중앙 집중식 설정**: 코드 내 흩어진 키워드 및 설정을 `config.py`로 통합.
- **구조화된 로깅**: `print()` 대신 표준 `logging` 라이브러리를 사용한 로그 시스템 구축.

#### Phase 4: 관리자 및 모니터링 강화
- **모니터링 영속화**: 성능 지표를 MongoDB에 저장하여 장기적인 지표 추적 가능.
- **관리자 계정 관리**: 단일 비밀번호 방식에서 DB 기반 관리자 계정 시스템으로 전환 고려.

---

## 12. 참고

- 프로젝트 요구사항: `docs/assets/project_plan.pdf`
- 기존 문서: `docs/README.md`, `docs/ARCHITECTURE_FASTAPI.md`
