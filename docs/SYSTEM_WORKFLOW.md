# UCSI 버디 시스템 워크플로우

- 문서 기준일: 2026-02-11
- 버전: 3.2.1
- 기준 코드: `app/api/chat.py`, `app/api/auth.py`, `app/api/admin.py`

## 1. 요청 처리 전체 흐름
```text
사용자 요청
  -> FastAPI Router (/api/*)
  -> (필요 시) JWT 검증
  -> Intent 판별 (개인정보 / UCSI 도메인 / 일반 질의)
  -> 개인 정보: MongoDB 직접 조회 + 보안 게이트 + 이모지 프로필 포맷
  -> 도메인 질의: RAG 검색(FAISS + MongoDB) 후 AI 응답 생성 + Rich Content 추출/중복 제거
  -> 일반 질의: AI 응답 또는 보수적 fallback
  -> suggestions + retrieval 메타 + rich_content 포함 응답 반환
```

## 2. 인증 워크플로우
1. `POST /api/login`
- 입력: `student_number`, `name`
- 성공 시 JWT 발급(만료 기본 60분)

2. `POST /api/verify_password`
- 로그인 사용자의 비밀번호 2차 검증
- 성공 시 고보안 세션 10분 활성화

3. `POST /api/logout`
- 메모리 세션에서 고보안 상태 제거

## 3. 채팅 워크플로우 (`POST /api/chat`)
1. 세션 결정
- 로그인 사용자: `user:{student_number}`
- 게스트: `guest:{conversation_id}`

2. 의도 분기
- 개인 질의: 로그인/고보안 여부 확인 후 학생 정보 조회
- UCSI 도메인 질의: RAG 우선 경로 강제
- 일반 질의: AI 직접 응답

3. 개인정보/민감정보 게이트
- 로그인 미완료: `type=login_hint`
- GPA/성적 질의 + 고보안 미완료: `type=password_prompt`

4. RAG 처리
- `rag_engine_async.search_context()` 호출
- 신뢰도 낮거나 미일치 시 안전 fallback(`NO_DATA` 정책)
- 미응답/저신뢰는 `unanswered` 로그 저장

5. 응답 생성 및 포맷
- LLM이 `Label: Value` 포맷으로 구조화된 정보 출력 (Staff, Building, Hostel, Programme)
- Raw URL은 LLM 텍스트에 포함되지 않음 (프롬프트에서 금지)
- 프론트엔드에서 `Label: Value` 패턴을 자동 감지해 `.kv-block` 레이아웃으로 렌더링

6. Rich Content 처리 (v3.2.1)
- RAG 컨텍스트에서 URL 추출 (`_extract_rich_content`)
- 쿼리 유형별 제한: Staff → 프로필 1개, Building → 이미지 1개 + map 1개
- URL 기반 중복 제거
- 프론트엔드: rich content URL을 텍스트에서 자동 스트립 (`stripRichUrls`)

7. 응답 구조
- `response`(JSON 문자열): `text`, `suggestions`, `retrieval`, `rich_content`
- `session_id`, `type`, `user`

## 4. 피드백 루프 (`POST /api/feedback`)
- positive: `LearnedQA` 반영(재사용 가능한 정답 강화)
- negative: `BadQA` 반영(오답 재사용 방지)
- 이후 유사 질의 시 `feedback_guard`로 RAG 경로 강화

## 5. 관리자 워크플로우
- `GET /api/admin/stats`: 학생 통계, 피드백, unanswered 로그 집계
- `POST /api/admin/upload`: 파일 저장 후 즉시 인제스트
- `POST /api/admin/reindex`: MongoDB 전체 재색인
- `GET /api/admin/files` / `DELETE /api/admin/files`: KB 파일 관리

## 6. 장애 대응 포인트
- AI 계층: 비동기 Circuit Breaker + Token Bucket Rate Limiter
- DB 계층: 연결 실패 시 graceful fallback
- RAG 계층: 신뢰도 기반 안전 응답, 환각 억제
