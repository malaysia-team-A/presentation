import csv
import json
from datetime import datetime
from pathlib import Path
import sys
from fastapi.testclient import TestClient

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import main


TEST_CASES = [
    {
        "id": 1,
        "query": "Where is Block A?",
        "expected_any": ["block a", "address", "building"],
        "expect_no_data": False,
    },
    {
        "id": 2,
        "query": "How much is the hostel fee?",
        "expected_any": ["rm", "hostel", "rent", "deposit"],
        "expect_no_data": False,
    },
    {
        "id": 3,
        "query": "What time does the library close?",
        # Current UCSI_FACILITY sample data has no explicit library entry.
        "expected_any": ["could not find", "cannot find", "not available", "not in our database"],
        "expect_no_data": True,
    },
    {
        "id": 4,
        "query": "event schedule for intake",
        "expected_any": ["event", "start_date", "end_date", "schedule"],
        "expect_no_data": False,
    },
    {
        "id": 5,
        "query": "Who is Professor Spiderman?",
        "expected_any": ["could not find", "cannot find", "not available", "not in our database"],
        "expect_no_data": True,
    },
    {
        "id": 6,
        "query": "What is the fee for the Mars Campus?",
        "expected_any": ["could not find", "cannot find", "not available", "not in our database"],
        "expect_no_data": True,
    },
    {
        "id": 7,
        "query": "Tell me about the Moon campus tuition",
        "expected_any": ["could not find", "cannot find", "not available", "not in our database"],
        "expect_no_data": True,
    },
    {
        "id": 8,
        "query": "Is accommodation guaranteed for first year students?",
        "expected_any": ["accommodation", "hostel", "answer", "question"],
        "expect_no_data": False,
    },
]


def _parse_payload_text(raw_response):
    if not raw_response:
        return ""
    try:
        parsed = json.loads(raw_response)
        if isinstance(parsed, dict):
            return str(parsed.get("text", ""))
    except Exception:
        pass
    return str(raw_response)


def run():
    rows = []
    passed = 0

    client = TestClient(main.app)
    for tc in TEST_CASES:
        resp = client.post("/api/chat", json={"message": tc["query"]})
        ok_http = resp.status_code == 200
        try:
            payload = resp.json()
        except Exception:
            payload = {}
        text = _parse_payload_text(payload.get("response", ""))
        text_lower = text.lower()

        hit_expected = any(token in text_lower for token in [t.lower() for t in tc["expected_any"]])
        has_no_data_phrase = any(
            token in text_lower
            for token in ["could not find", "cannot find", "not available", "not in our database"]
        )

        if tc["expect_no_data"]:
            ok = ok_http and has_no_data_phrase
        else:
            ok = ok_http and hit_expected

        if ok:
            passed += 1

        rows.append(
            {
                "id": tc["id"],
                "query": tc["query"],
                "status_code": resp.status_code,
                "ok": ok,
                "expected_hit": hit_expected,
                "has_no_data_phrase": has_no_data_phrase,
                "response_preview": text[:240],
                "type": "no_data" if tc["expect_no_data"] else "grounded",
            }
        )

    total = len(rows)
    accuracy = (passed / total * 100.0) if total else 0.0

    out_dir = Path("data")
    out_dir.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = out_dir / f"e2e_rag_regression_{ts}.csv"

    with report_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print(f"TOTAL={total}")
    print(f"PASS={passed}")
    print(f"ACCURACY={accuracy:.2f}")
    print(f"REPORT={report_path}")

    fails = [r for r in rows if not r["ok"]]
    print(f"FAILS={len(fails)}")
    for r in fails:
        print(f"- id={r['id']} query={r['query']} status={r['status_code']} preview={r['response_preview'][:120]}")


if __name__ == "__main__":
    run()
