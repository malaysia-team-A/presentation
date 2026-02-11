# 코드 협업 가이드라인

이 문서는 프로젝트 내 코드/문서 작업 시 충돌을 줄이고 품질을 유지하기 위한 공통 규칙입니다.

## 1. 변경 원칙
- 변경 이유가 분명해야 합니다.
- 실제 문제 해결에 필요한 범위만 수정합니다.
- 관련 없는 리팩터링/대규모 포맷 변경은 분리합니다.

## 2. 파일 수정 방식
- 기존 로직을 바꿀 때는 왜 바꾸는지 짧게 설명합니다.
- 미확정 삭제보다 `deprecated` 표시 또는 주석 처리 후 추적 가능하게 유지합니다.
- 인코딩 문제 발생 파일은 전체를 깨끗한 UTF-8 텍스트로 재저장합니다.

## 3. API 변경 규칙
- 엔드포인트 변경 시 다음을 함께 업데이트합니다.
  - `docs/README.md`
  - `docs/SYSTEM_WORKFLOW.md`
  - 관련 프런트 호출 코드(`static/site/js/app.js`)
- 요청/응답 스키마 변경 시 `app/schemas.py` 동기화 필수

## 4. 보안 규칙
- 민감정보(성적/GPA)는 고보안 검증 없이 노출 금지
- 인증이 필요한 API는 의존성(`get_current_user`)을 명시 적용
- 운영 환경에서 관리자 API는 반드시 권한 검사 적용

## 5. QA 규칙
- 기능 변경 후 최소 실행
  - `python scripts/checks/check_server.py`
  - `python scripts/qa/strict_qa_suite.py --mode base`
- 배포 전 권장 실행
  - `python scripts/qa/strict_qa_suite.py --mode full`
  - `python scripts/qa/stress_test_runner.py`

## 6. 문서 동기화 규칙
- 코드 변경 후 같은 턴에서 문서를 같이 업데이트합니다.
- 실행 포트/경로/API가 바뀌면 문서 우선 갱신 후 공유합니다.
- 기준일자를 문서 상단에 명시합니다.
