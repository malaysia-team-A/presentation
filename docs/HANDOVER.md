# UCSI Buddy — 인수인계 문서

**버전:** 3.4.0 | **최종 업데이트:** 2026-02-12

---

## 현재 상태

프로젝트 완전 작동 상태. 모든 주요 기능 구현 완료, 알려진 버그 없음.

---

## 핵심 기술 스택

| 구성 요소 | 기술 |
|----------|------|
| 웹 프레임워크 | FastAPI (비동기, uvicorn) |
| LLM | Google Gemini `gemma-3-27b-it` (google-genai SDK) |
| 임베딩 모델 | `paraphrase-multilingual-MiniLM-L12-v2` (SentenceTransformer, 로컬, 384차원) |
| 벡터 검색 | FAISS (로컬 `data/knowledge_base/`) |
| 문서 DB | MongoDB Atlas (Motor 비동기 드라이버) |
| 인증 | JWT HS256 (`python-jose`) |
| 프론트엔드 | 바닐라 HTML/JS (Tailwind CDN, Material Icons) |

---

## 채팅 플로우 (3-Branch 라우팅)

```
POST /api/chat
    │
    ├─ [Branch 1] _is_personal_query()
    │   "내 성적", "my gpa", "내 프로필" 등
    │   → handle_personal_query()
    │   ↳ JWT 필수 / GPA는 verify_password 2FA 추가 필요
    │
    ├─ [Branch 2] has_ucsi_keywords()
    │   "hostel", "block", "diploma", "pet", "schedule" 등
    │   → intent_classifier.classify()
    │   ├─ query_type=aggregate → handle_llm_first_query()
    │   └─ query_type=specific  → handle_ucsi_query()  ← RAG 검색
    │
    └─ [Branch 3] 나머지 (일반 지식, 인물 검색 등)
        → handle_llm_first_query()
        ↳ RAG + MongoDB 이름 검색 병렬 실행
        ↳ 데이터 있음 → 보안 체크 → LLM with context
        ↳ 데이터 없음 → LLM 자유 응답
```

---

## 보안 구조

### 학생 데이터 3중 보호

1. **로그인 필수**: `handle_llm_first_query`에서 source에 `"student"` 포함 시 → `login_hint` 반환
2. **JWT 검증**: `app/api/dependencies.py`의 `get_current_user_optional` Depends
3. **GPA 2FA**: `high_security_sessions` 딕셔너리에 세션 키 등록 필요

> 중요: UCSI 도메인 데이터(스케줄, 기숙사, 건물 등)는 로그인 없이 접근 가능.
> `is_student_data` 체크는 소스에 `"student"` 키워드가 있을 때만 true.

### FAISS 민감정보 제외 (`rag_engine_async.py`)

```python
_SENSITIVE_FIELDS = {"password", "Password", "gpa", "GPA", "cgpa", "CGPA",
                     "dob", "DOB", "date_of_birth", "STUDENT_NUMBER", "student_number"}
```

---

## 임베딩 모델 주의사항

- **모델**: `paraphrase-multilingual-MiniLM-L12-v2` (한/영 동시 지원, 384차원)
- **캐시**: `C:\Users\[사용자]\.cache\huggingface\hub\`
- **오프라인 모드**: `main.py` 최상단 `HF_HUB_OFFLINE=1` → 네트워크 없이 캐시에서 로드
- **모델 변경 시**: FAISS 인덱스 삭제 후 재시작 필수
  - `data/knowledge_base/faiss_index.bin`
  - `data/knowledge_base/faiss_metadata.pkl`

---

## MongoDB 컬렉션 구조

| 컬렉션 | 주요 필드 | 용도 |
|--------|----------|------|
| `UCSI_University_Student_Data` | STUDENT_NAME, STUDENT_NUMBER, GPA, PROGRAMME_NAME, Password | 학생 정보 |
| `UCSI_University_Staff_Data` | name, role, email, profile_url | 교직원 정보 |
| `UCSI_University_Blocks_Data` | Name, BUILDING_IMAGE, MAP, Address | 캠퍼스 건물 |
| `UCSI_University_Hostel_Data` | room_type, price, deposit | 기숙사 |
| `UCSI_University_Programme_Data` | name, faculty, tuition, duration, Url | 학과/프로그램 |
| `UCSI_University_Schedule_Data` | event, date | 학사 일정 |
| `semantic_intents` | intent, example, embedding | SemanticRouter 시드 |
| `learned_responses` | user_message, ai_response | RLHF 긍정 학습 |
| `bad_responses` | user_message, ai_response, reason | RLHF 부정 가드 |

---

## Rich Content 렌더링

API 응답에 `rich_content` 필드가 있으면 프론트엔드가 자동 렌더링:

```json
{
  "response": "Block A is located at...",
  "rich_content": {
    "images": [{"url": "https://drive.google.com/file/d/...", "label": "Block A"}],
    "links": [{"url": "https://maps.google.com/...", "type": "map", "label": "View on Map"}]
  }
}
```

- Google Drive URL → `toEmbedUrl()` 함수로 `uc?export=view&id=` 형식 자동 변환 후 `<img>` 렌더링
- 링크 타입: `map`, `staff_profile`, `programme_info` → 아이콘 자동 선택

---

## 자주 발생하는 이슈 & 해결책

| 증상 | 원인 | 해결책 |
|------|------|--------|
| 서버 시작 시 SSL/Network 에러 | HuggingFace 모델 다운로드 시도 | `HF_HUB_OFFLINE=1` 확인 (`main.py` 최상단) |
| FAISS 검색 결과 이상 | 모델 변경 후 인덱스 미갱신 | `faiss_index.bin`, `faiss_metadata.pkl` 삭제 후 재시작 |
| 로그인 상태에서도 login_hint | `user=user` 파라미터 누락 | `handle_llm_first_query(user=user)` 확인 |
| 스케줄/기숙사 정보에서 login_hint | `is_student_data` 조건 과도 | `"student" in s.lower()` 조건만 사용 |
| `Collection` bool TypeError | `if not self.collection:` 사용 | `if self.collection is None:` 으로 수정 |
| KeyError: 'response' | 응답 키 불일치 | `result.get("text") or result.get("response", "")` 사용 |

---

## 개발 환경 설정

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

`.env` 필수 항목:
```
MONGO_URI=mongodb+srv://...
GEMINI_API_KEY=AIza...
SECRET_KEY=<32바이트 hex>
ADMIN_PASSWORD=<관리자 비밀번호>
HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1
```

---

## 완료된 기능

- [x] 학생 로그인 (학번 + 이름)
- [x] GPA 2중 인증 (비밀번호)
- [x] UCSI 도메인 정보 RAG 검색 (기숙사, 프로그램, 캠퍼스, 직원, 일정)
- [x] 인물 쿼리 MongoDB 직접 검색 (학생/교직원)
- [x] 다국어 지원 (한국어/영어 혼용 쿼리)
- [x] 건물 이미지 인라인 표시 (Google Drive 임베드)
- [x] 지도/프로필/프로그램 링크 버튼
- [x] 채팅 기록 세션 저장
- [x] 피드백 (좋아요/싫어요) + RLHF 학습
- [x] 관리자 대시보드 (모니터링, 재인덱싱, 문서 업로드)
- [x] Prompt Injection 탐지 (12패턴)
- [x] 응답 할루시네이션 방지
- [x] 시맨틱 캐시 (동일 질문 빠른 응답)
- [x] FAISS 민감정보(GPA, 비밀번호) 인덱싱 제외
