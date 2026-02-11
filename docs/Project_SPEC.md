# UCSI 챗봇 시스템 기술 명세 (v3.1)

- 작성일: 2026-02-09
- 기준: FastAPI 비동기 런타임

## 1. 기술 스택
| 구분 | 기술 | 비고 |
|---|---|---|
| 언어 | Python 3.10+ | 권장 3.10 이상 |
| 웹 프레임워크 | FastAPI | 비동기 API |
| ASGI 서버 | Uvicorn | `python main.py`로 실행 |
| DB | MongoDB Atlas | Motor 비동기 드라이버 |
| 임베딩/검색 | sentence-transformers + FAISS | 벡터 인덱스 |
| LLM | Google Gen AI SDK | `google-genai` |
| 검증/스키마 | Pydantic v2 | 요청 검증 |

## 2. 디렉터리 핵심 구조
- `main.py`: 서버 엔트리포인트, 라우터/정적 파일 등록
- `app/api/`: 인증/채팅/관리자 API
- `app/engines/`: AI/RAG/DB 엔진
- `app/core/`: 세션 상태 저장
- `app/utils/`: 인증 유틸
- `static/site/`: 사용자 UI
- `static/admin/`: 관리자 대시보드
- `scripts/`: 체크/QA/DB/디버그 도구

## 3. 실행 시 초기화
1. DB 연결 (`db_engine_async.connect()`)
2. MongoDB 컬렉션 RAG 재색인 (`rag_engine_async.index_mongodb_collections()`)
3. 라우터/정적 리소스 제공 시작

## 4. 데이터 흐름
1. 요청 유입 (`/api/chat`)
2. 토큰 해석 및 세션 분기
3. 개인/도메인/일반 질의 분류
4. 필요 시 RAG 검색 및 문맥 주입
5. AI 응답 생성 + suggestions
6. 피드백 입력 시 `LearnedQA`/`BadQA` 반영

## 5. 환경 변수
- 필수
  - `SECRET_KEY`
  - `MONGO_URI`
  - `GEMINI_API_KEY` (레거시: `GOOGLE_API_KEY`)
- 선택
  - `GEMINI_MODEL`
  - `RAG_FAST_CONFIDENCE`
  - `RAG_REWRITE_TRIGGER`
  - `RAG_RERANK_TRIGGER`
  - `RAG_MAX_TOTAL_QUERIES`

## 6. 운영 체크포인트
- 관리자 API 인증이 기본 미적용 상태이므로 운영 환경에서는 즉시 보완 필요
- 인덱스 파일(`faiss_index.bin`, `faiss_metadata.pkl`)은 런타임 재생성 가능
- 보고서 산출물은 `data/reports/`에 저장
