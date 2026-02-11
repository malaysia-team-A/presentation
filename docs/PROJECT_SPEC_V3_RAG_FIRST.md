# UCSI AI Chatbot Project Spec v3.1 (RAG-First)

- 작성일: 2026-02-09
- 기준 코드: `main.py`, `app/api/*.py`, `app/engines/*_async.py`
- 실행 런타임: FastAPI + MongoDB Atlas + FAISS + Gemini

## 1. 제품 목표
1. UCSI 도메인 질의는 반드시 근거 중심(RAG/DB)으로 응답한다.
2. 개인정보/성적 질의는 인증 단계를 명확히 분리한다.
3. 응답은 짧고 행동 가능한 문장으로 제공한다.
4. 모델 추측보다 "정보 없음" 응답을 우선해 환각을 방지한다.

## 2. 범위 정의
- General Query: 일반 상식/일반 질의
- Domain Query: UCSI 관련 정보(학과, 기숙사, 시설, 일정, 교직원)
- Personal Query: 학생 본인 정보 조회(로그인 필요)
- Sensitive Query: GPA/성적/민감정보(비밀번호 재검증 필요)
- Self-improvement Loop:
  - `feedback` 저장
  - `LearnedQA`(좋은 답변) 강화
  - `BadQA`(오답) 재사용 차단
  - `unanswered` 누적

## 3. 시스템 구성
- API 레이어
  - `app/api/auth.py`
  - `app/api/chat.py`
  - `app/api/admin.py`
- 엔진 레이어
  - `ai_engine_async.py`: 모델 호출, rate limit, circuit breaker
  - `db_engine_async.py`: MongoDB 조회/저장
  - `rag_engine_async.py`: 비동기 래퍼
  - `rag_engine.py`: FAISS 인덱싱/검색 코어
- 세션/보안
  - `app/core/session.py`: 대화 이력, 고보안 세션
  - `app/utils/auth_utils.py`: JWT 발급/검증

## 4. RAG 우선 정책
1. 강제 RAG 대상
- 수업/학과/학비/시설/기숙사/직원/일정/블록 등 UCSI 도메인 키워드

2. 개인 질의
- 학생번호 기반 DB 직접 조회 우선
- 성적성 질문은 고보안 세션 없으면 차단

3. 무근거 응답 방지
- `has_relevant_data = false`이면 보수 응답으로 전환
- 미응답은 `unanswered`에 로깅

## 5. API 계약(핵심)
- `POST /api/chat`
  - 입력: `message`, `session_id`(선택), `search_term`(선택), `needs_context`(선택)
  - 출력: `response`(JSON 문자열), `type`, `session_id`, `user`
- `POST /api/login`
  - 입력: `student_number`, `name`
  - 출력: `token` + 사용자 정보
- `POST /api/verify_password`
  - 출력: `verified`, `expires_in_seconds`

## 6. 품질 기준
1. Intent Correctness
- 질의 유형에 따라 올바른 경로로 라우팅

2. Security Correctness
- 비로그인/비검증 상태에서 민감정보 노출 금지

3. Grounded Correctness
- RAG 문맥 밖 정보 단정 금지
- 미확인 데이터는 "정보 없음" 처리

4. UX Quality
- 과도한 장문 응답 억제
- 후속 질문(suggestions) 제공

## 7. 최신 검증 결과 (기록)
- Strict QA: `58/58` 통과
- Stress Test: `300/300` HTTP 성공, `300/300` semantic pass
- 최근 리포트 파일:
  - `data/reports/strict_qa_report_latest.csv`
  - `data/reports/stress_test_report_latest.csv`

## 8. 다음 우선 개발 과제
1. 관리자 라우트 인증/권한 분리 (P0)
2. 인코딩 깨짐 문자열 정리 (P1)
3. 레거시 동기 엔진 정리 및 경량화 (P1)
4. QA 자동화(배포 전 검증 파이프라인) (P1)
