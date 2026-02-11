# n8n Workflow Guide for UCSI Buddy Chatbot

이 문서는 n8n을 사용하여 UCSI Buddy Chatbot의 E2E 테스트 및 모니터링 워크플로우를 설정하는 방법을 설명합니다.

## 목차

1. [기본 설정](#기본-설정)
2. [테스트 워크플로우](#테스트-워크플로우)
3. [모니터링 워크플로우](#모니터링-워크플로우)
4. [자동화 시나리오](#자동화-시나리오)

---

## 기본 설정

### 환경 변수

n8n에서 다음 Credentials를 설정하세요:

```
UCSI_API_BASE_URL: http://localhost:5000
UCSI_ADMIN_PASSWORD: (your admin password)
```

### HTTP Request Node 기본 설정

```json
{
  "authentication": "none",
  "url": "={{ $env.UCSI_API_BASE_URL }}/api/chat",
  "method": "POST",
  "headers": {
    "Content-Type": "application/json"
  }
}
```

---

## 테스트 워크플로우

### 1. 기본 채팅 테스트

```
[Manual Trigger]
       │
       ▼
[Set Test Cases] ──► 테스트 케이스 정의
       │
       ▼
[Loop Over Items]
       │
       ▼
[HTTP Request: POST /api/chat]
       │
       ▼
[Parse Response]
       │
       ▼
[IF: Check Success]
       │
   ┌───┴───┐
   ▼       ▼
[Pass]  [Fail]
   │       │
   ▼       ▼
[Aggregate Results]
       │
       ▼
[Send Report]
```

#### Set Test Cases Node (Code)

```javascript
const testCases = [
  {
    name: "UCSI Domain - Hostel",
    message: "hostel fee 얼마야?",
    expectedCategory: "ucsi_domain",
    expectedRoute: "rag"
  },
  {
    name: "Personal Query",
    message: "my GPA",
    expectedCategory: "personal",
    expectedRoute: "personal_db_direct"
  },
  {
    name: "General Knowledge",
    message: "who is Taylor Swift?",
    expectedCategory: "general_knowledge",
    expectedRoute: "general_ai"
  },
  {
    name: "Capability Query",
    message: "can you dance?",
    expectedCategory: "capability",
    expectedRoute: "capability_smalltalk"
  }
];

return testCases.map(tc => ({ json: tc }));
```

#### HTTP Request Node

```json
{
  "method": "POST",
  "url": "http://localhost:5000/api/chat",
  "body": {
    "message": "={{ $json.message }}",
    "conversation_id": "n8n_test_{{ $now.format('yyyyMMdd_HHmmss') }}"
  },
  "options": {
    "timeout": 30000
  }
}
```

#### Parse & Validate Node (Code)

```javascript
const input = $input.first().json;
const testCase = $('Set Test Cases').first().json;

// Parse response
let response;
try {
  response = JSON.parse(input.response);
} catch (e) {
  return [{
    json: {
      testName: testCase.name,
      passed: false,
      error: "Failed to parse response",
      raw: input.response
    }
  }];
}

// Validate
const route = response.retrieval?.route || "unknown";
const confidence = response.retrieval?.confidence || 0;

const passed = route.includes(testCase.expectedRoute) ||
               confidence > 0.5;

return [{
  json: {
    testName: testCase.name,
    passed: passed,
    expectedRoute: testCase.expectedRoute,
    actualRoute: route,
    confidence: confidence,
    responsePreview: (response.text || "").substring(0, 100)
  }
}];
```

---

### 2. 인증 플로우 테스트

```
[Manual Trigger]
       │
       ▼
[HTTP Request: POST /api/login]
  body: { student_number, name }
       │
       ▼
[Extract Token]
       │
       ▼
[HTTP Request: POST /api/chat]
  header: Authorization: Bearer {{token}}
  body: { message: "my profile" }
       │
       ▼
[Validate Personal Data Access]
       │
       ▼
[HTTP Request: POST /api/verify_password]
       │
       ▼
[HTTP Request: POST /api/chat]
  body: { message: "my GPA" }
       │
       ▼
[Validate Grade Access]
```

#### Login Node

```json
{
  "method": "POST",
  "url": "http://localhost:5000/api/login",
  "body": {
    "student_number": "1002345678",
    "name": "Test Student"
  }
}
```

#### Authenticated Chat Node

```json
{
  "method": "POST",
  "url": "http://localhost:5000/api/chat",
  "headers": {
    "Authorization": "Bearer {{ $json.token }}"
  },
  "body": {
    "message": "show my profile"
  }
}
```

---

### 3. RAG 품질 테스트

```
[Schedule Trigger: Daily]
       │
       ▼
[Load Test Questions from Google Sheet]
       │
       ▼
[Loop Over Questions]
       │
       ▼
[HTTP Request: POST /api/chat]
       │
       ▼
[Extract Metrics]
  - confidence
  - sources
  - response_length
       │
       ▼
[Store to Database/Sheet]
       │
       ▼
[Calculate Averages]
       │
       ▼
[IF: Avg Confidence < 0.6]
       │
       ▼
[Send Alert Email]
```

#### Extract Metrics Node (Code)

```javascript
const items = $input.all();
const results = [];

for (const item of items) {
  let response;
  try {
    response = JSON.parse(item.json.response);
  } catch (e) {
    continue;
  }

  results.push({
    json: {
      question: item.json.originalQuestion,
      timestamp: new Date().toISOString(),
      confidence: response.retrieval?.confidence || 0,
      route: response.retrieval?.route || "unknown",
      sources: response.retrieval?.sources || [],
      sourceCount: (response.retrieval?.sources || []).length,
      responseLength: (response.text || "").length,
      hasSuggestions: (response.suggestions || []).length > 0
    }
  });
}

return results;
```

---

## 모니터링 워크플로우

### 4. Unanswered Questions Monitor

```
[Schedule Trigger: Every Hour]
       │
       ▼
[HTTP Request: GET /api/admin/stats]
  header: Authorization: Bearer {{admin_token}}
       │
       ▼
[Extract Unanswered Count]
       │
       ▼
[IF: Count > Threshold]
       │
       ▼
[Slack/Discord Notification]
  "⚠️ {{count}} unanswered questions in the last hour"
```

### 5. Feedback Analysis

```
[Schedule Trigger: Daily]
       │
       ▼
[MongoDB Node: Aggregate Feedback]
  pipeline: [
    { $match: { timestamp: { $gte: yesterday } } },
    { $group: {
        _id: "$rating",
        count: { $sum: 1 }
    }}
  ]
       │
       ▼
[Calculate Satisfaction Rate]
       │
       ▼
[IF: Satisfaction < 80%]
       │
       ▼
[Send Alert + Top Negative Feedback]
```

---

## 자동화 시나리오

### 6. Auto Re-index on Data Change

```
[Webhook: MongoDB Change Stream]
  or
[Schedule: Every 6 Hours]
       │
       ▼
[HTTP Request: POST /api/admin/reindex]
  header: Authorization: Bearer {{admin_token}}
       │
       ▼
[Log Result]
       │
       ▼
[IF: Failed]
       │
       ▼
[Send Alert]
```

### 7. Health Check

```
[Schedule Trigger: Every 5 Minutes]
       │
       ▼
[HTTP Request: GET /health]
       │
       ▼
[IF: Status != 200 OR Response Time > 5s]
       │
       ▼
[PagerDuty/Slack Alert]
```

---

## 샘플 워크플로우 JSON

### Basic Chat Test Workflow

```json
{
  "name": "UCSI Buddy - Basic Chat Test",
  "nodes": [
    {
      "name": "Manual Trigger",
      "type": "n8n-nodes-base.manualTrigger",
      "position": [250, 300]
    },
    {
      "name": "Test Chat",
      "type": "n8n-nodes-base.httpRequest",
      "position": [450, 300],
      "parameters": {
        "method": "POST",
        "url": "http://localhost:5000/api/chat",
        "jsonParameters": true,
        "bodyParametersJson": "{\"message\": \"hostel fee?\", \"conversation_id\": \"n8n_test\"}"
      }
    },
    {
      "name": "Check Response",
      "type": "n8n-nodes-base.if",
      "position": [650, 300],
      "parameters": {
        "conditions": {
          "string": [
            {
              "value1": "={{ $json.response }}",
              "operation": "isNotEmpty"
            }
          ]
        }
      }
    }
  ],
  "connections": {
    "Manual Trigger": {
      "main": [[{"node": "Test Chat", "type": "main", "index": 0}]]
    },
    "Test Chat": {
      "main": [[{"node": "Check Response", "type": "main", "index": 0}]]
    }
  }
}
```

---

## MCP 연동 (Claude Code)

n8n MCP 서버를 사용하면 Claude Code에서 직접 워크플로우를 실행할 수 있습니다:

```bash
# n8n MCP 서버 설정
npx @anthropic/mcp-server-n8n

# Claude Code에서 사용
"n8n 워크플로우 실행해줘: UCSI Buddy - Basic Chat Test"
```

---

## 권장 테스트 주기

| 테스트 | 주기 | 목적 |
|-------|------|------|
| Health Check | 5분 | 서비스 가용성 |
| Basic Chat Test | 1시간 | 기본 기능 |
| RAG Quality Test | 일간 | 답변 품질 |
| Feedback Analysis | 일간 | 사용자 만족도 |
| Full Integration | 주간 | 전체 시스템 |

---

## 문제 해결

### 일반적인 오류

1. **Connection Refused**
   - 서버가 실행 중인지 확인
   - 포트 확인 (기본: 5000)

2. **401 Unauthorized**
   - 토큰 만료 확인
   - Admin 비밀번호 확인

3. **Timeout**
   - LLM API 지연 가능
   - timeout 값 증가 (30초 권장)

4. **Empty Response**
   - 메시지 필드 확인
   - JSON 형식 확인
