# UCSI 버디 챗봇 문서 허브

- 문서 기준일: 2026-02-11
- 버전: 3.2.1
- 기준 코드: `main.py`, `app/api/*.py`, `app/engines/*.py`
- 기본 실행 포트: `5000`

## 1. 프로젝트 개요
이 프로젝트는 UCSI 대학 도메인 질문을 우선 처리하는 RAG 기반 챗봇입니다.
현재 서버는 FastAPI 비동기 구조로 동작하며 인증/개인정보 질의/일반 질의/관리자 기능이 API로 분리되어 있습니다.

### 주요 기능 (v3.2.1)
- **하이브리드 인텐트 분류**: Keyword Guard → Vector Search → LLM Fallback
- **할루시네이션 방지**: 응답 검증 및 소스 기반 검증
- **Self-Learning**: 피드백 기반 학습 (RLHF)
- **보안 강화**: Prompt Injection 탐지 및 입력 Sanitization
- **성능 모니터링**: 응답 시간, RAG hit rate, LLM 사용량 추적
- **UX 개선**: 다국어 인사말, 에러 메시지, 후속 질문 제안
- **Rich Content**: Staff 프로필 링크, 건물 이미지, 프로그램/지도 링크 (중복 제거 적용)
- **구조화된 응답 포맷**: LLM `Label: Value` 출력 → 프론트엔드 자동 KV 레이아웃 렌더링
- **학생 프로필 이모지**: 🆔 학번, 👤 이름, 📚 전공 등 아이콘 부착
- **URL 자동 스트립**: rich content로 표시되는 URL을 텍스트에서 자동 제거

## 2. 현재 아키텍처
- 백엔드: FastAPI + Uvicorn
- 인증: JWT (`/api/login`, `/api/verify_password`, `/api/logout`)
- 데이터 계층: MongoDB Atlas + Motor(비동기)
- RAG: FAISS 인덱스 + MongoDB 컬렉션 인덱싱
- LLM: Google GenAI SDK (`google-genai`)
- 인텐트 분류: 하이브리드 (Keyword + Semantic + LLM)
- 프런트엔드: `static/site/code_hompage.html` (KV 레이아웃, Rich Content, 다크모드)

## 3. API 요약
- 인증
  - `POST /api/login`
  - `POST /api/verify_password`
  - `POST /api/logout`
- 채팅
  - `POST /api/chat`
  - `POST /api/feedback`
  - `GET /api/export_chat`
- 관리자
  - `POST /api/admin/login` - 관리자 로그인
  - `POST /api/admin/logout` - 관리자 로그아웃
  - `GET /api/admin/stats` - 통계 조회
  - `POST /api/admin/upload` - 문서 업로드
  - `POST /api/admin/reindex` - MongoDB 재인덱싱
  - `GET /api/admin/files` - 파일 목록
  - `DELETE /api/admin/files` - 파일 삭제
  - `GET /api/admin/index/status` - 인덱스 상태
  - `POST /api/admin/index/reindex` - 수동 재인덱싱
  - `GET /api/admin/index/history` - 인덱싱 히스토리
  - `GET /api/admin/index/changes` - 데이터 변경 감지
  - `GET /api/admin/monitoring/dashboard` - 모니터링 대시보드
  - `GET /api/admin/unanswered/analysis` - 미답변 질문 분석
  - `GET /api/admin/unanswered/report` - 미답변 리포트
  - `GET /api/admin/health` - 헬스체크 (Public)

## 4. 실행 방법
1. 가상환경 생성 및 활성화
```bash
python -m venv .venv
.venv\Scripts\activate
```
2. 의존성 설치
```bash
pip install -r requirements.txt
```
3. 환경 변수 설정 (`.env`)
- 필수: `SECRET_KEY`, `MONGO_URI`, `GEMINI_API_KEY`(또는 `GOOGLE_API_KEY`)
- 선택: `GEMINI_MODEL`, `RAG_*` 튜닝 변수
4. 서버 실행
```bash
python main.py
```
5. 접속
- 메인 UI: `http://localhost:5000/`
- 관리자 UI: `http://localhost:5000/admin`
- Swagger: `http://localhost:5000/docs`

## 5. QA/검증 스크립트
- 환경 검증: `python scripts/verify_setup.py`
- 런타임 검증: `python scripts/checks/check_python.py`
- 서버 체크: `python scripts/checks/check_server.py`
- 정합성 QA: `python scripts/qa/strict_qa_suite.py --mode full`
- 부하 테스트: `python scripts/qa/stress_test_runner.py`

### 테스트 스위트 (v3.1.0)
- 전체 테스트: `python scripts/tests/run_all_tests.py --verbose`
- 통합 테스트: `python scripts/tests/test_integration.py`
- 보안 테스트: `python scripts/tests/test_security.py`
- UX 테스트: `python scripts/tests/test_ux.py`

## 6. 운영 주의사항
- 서버 시작 시 `index_mongodb_collections()`가 실행되어 MongoDB 기반 RAG 인덱스를 재구축합니다. (향후 디스크 캐싱 도입을 통해 시동 속도를 최적화할 예정입니다.)
- 관리자 업로드(`POST /api/admin/upload`)는 저장 후 즉시 인덱싱을 수행합니다.
- 관리자 API(`app/api/admin.py`)는 `require_admin` 의존성을 통해 JWT 및 관리자 권한을 체크합니다.
- 세션 및 대화 기록은 현재 메모리에 저장되므로 서버 재시작 시 유실됩니다. (차기 업데이트에서 MongoDB TTL 컬렉션을 통한 영속성 확보 예정)
- `main_fastapi.py`는 호환용 진입점이며 실제 기준 실행은 `main.py`입니다.

## 7. 문서 목록
- `docs/ARCHITECTURE_FASTAPI.md`: FastAPI 아키텍처 상세
- `docs/SYSTEM_WORKFLOW.md`: 요청 처리 워크플로우
- `docs/PROJECT_STATUS_ANALYSIS.md`: 최신 상태 및 지표
- `docs/PROJECT_SPEC_V3_RAG_FIRST.md`: 제품/품질 스펙
- `docs/Project_SPEC.md`: 시스템 기술 명세 요약
- `docs/IMPLEMENTATION_PLAN_V2.md`: 구현 로드맵
- `docs/HANDOVER.md`: 인수인계 포인트
- `docs/Guideline.md`: 협업 가이드라인
- `docs/FunctionTech_Plan.md`: 기능 확장 계획
- `docs/UPDATE_LOG_2026-02-10.md`: v3.1.0 업데이트 로그
- `docs/N8N_WORKFLOW_GUIDE.md`: n8n 워크플로우 가이드
- `docs/assets/project_plan.pdf`: 원본 기획안 PDF
