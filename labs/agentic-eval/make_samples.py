#!/usr/bin/env python3
"""리포트에 실을 '압축 전 → 후' 샘플을 실제로 만들어 저장합니다.

왜 별도 스크립트인가
────────────────────
리포트에 압축 예시를 손으로 적어 넣으면, 코드나 모델이 바뀌었을 때 조용히
거짓말이 됩니다. 그래서 예시도 **측정값처럼** 다룹니다 — 여기서 진짜로
압축기를 돌려 JSON 으로 떨어뜨리고, 리포트는 그 파일을 읽기만 합니다.

쓰는 곳
    ./.venv/bin/python make_samples.py -o ../../reports/summary/samples.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "labs"))


# 에이전트가 실제로 주고받는 모양을 본뜬 입력입니다. 셋 다 성격이 다릅니다.
#   tool   — 명령 출력. 에이전트 컨텍스트에서 가장 크게 자라는 자리입니다.
#   user   — 사람이 쓴 과제 설명. 문장이 많아 압축 여지가 큽니다.
#   ko     — 같은 성격의 한국어. 다국어 모델이 한국어에서도 되는지 봅니다.
CASES = [
    {
        "id": "tool-output",
        "label": "도구 출력 (명령 실행 결과)",
        "why": "에이전트 컨텍스트에서 가장 빠르게 증가하는 영역이며, 압축 효과가 가장 크게 나타나는 구간입니다.",
        "role": "tool",
        "text": """$ pytest tests/ -v
============================= test session starts ==============================
platform linux -- Python 3.11.4, pytest-8.4.1, pluggy-1.6.0
rootdir: /app
plugins: asyncio-0.23.5, cov-4.1.0
collected 14 items

tests/test_parser.py::test_parse_header PASSED                           [  7%]
tests/test_parser.py::test_parse_body PASSED                             [ 14%]
tests/test_parser.py::test_parse_empty PASSED                            [ 21%]
tests/test_auth.py::test_login_ok PASSED                                 [ 28%]
tests/test_auth.py::test_login_bad_password FAILED                       [ 35%]
tests/test_auth.py::test_token_refresh PASSED                            [ 42%]

=================================== FAILURES ===================================
_________________________ test_login_bad_password ______________________________

    def test_login_bad_password():
        client = TestClient(app)
        resp = client.post("/login", json={"user": "alice", "password": "wrong"})
>       assert resp.status_code == 401
E       assert 500 == 401
E        +  where 500 = <Response [500]>.status_code

tests/test_auth.py:42: AssertionError
------------------------------- Captured log -------------------------------
ERROR    app.auth:auth.py:88 bcrypt.checkpw raised: Invalid salt
=========================== short test summary info ============================
FAILED tests/test_auth.py::test_login_bad_password - assert 500 == 401
========================= 1 failed, 13 passed in 2.41s =========================""",
    },
    {
        "id": "task-en",
        "label": "과제 설명 (영어)",
        "why": "자연어 산문 입력입니다. 중복 표현이 많아 압축률 대비 정보 손실이 작습니다.",
        "role": "user",
        "text": """You are working in a Python repository. There is a bug in the
authentication module that causes the server to return a 500 Internal Server
Error instead of a 401 Unauthorized when a user supplies an incorrect password.
Your task is to find the root cause of this problem and to fix it so that the
endpoint returns the correct status code. Please make sure that you do not
break any of the other tests that are currently passing in the test suite. The
relevant file is located at app/auth.py and the failing test can be found in
tests/test_auth.py at line 42. After you have made your change, run the full
test suite again to confirm that all 14 tests pass successfully.""",
    },
    {
        "id": "task-ko",
        "label": "과제 설명 (한국어)",
        "why": "동일 성격의 한국어 입력입니다. 다국어 모델이 한국어에서도 "
               "식별자와 숫자를 보존하는지 확인합니다.",
        "role": "user",
        "text": """당신은 파이썬 저장소에서 작업하고 있습니다. 인증 모듈에 버그가
있어서, 사용자가 잘못된 비밀번호를 입력했을 때 401 Unauthorized 를 반환해야
하는데 대신 500 Internal Server Error 를 반환하고 있습니다. 이 문제의 근본
원인을 찾아서, 엔드포인트가 올바른 상태 코드를 반환하도록 수정하는 것이
당신의 과제입니다. 현재 통과하고 있는 다른 테스트들을 깨뜨리지 않도록
반드시 주의해 주십시오. 관련 파일은 app/auth.py 에 있으며, 실패하는 테스트는
tests/test_auth.py 의 42번째 줄에서 찾을 수 있습니다. 수정을 마친 뒤에는
전체 테스트 스위트를 다시 실행하여 14개 테스트가 모두 통과하는지
확인해 주십시오.""",
    },
]

# 리포트에서 비교할 압축률입니다. 0.5 는 본 실험의 기본값입니다.
RATES = [0.7, 0.5, 0.3]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args()

    import compressors as C
    from kit import tokens as T

    def ntok(s: str) -> int:
        try:
            return T.count(s)
        except Exception:
            return len(s) // 4

    # 정책을 꺼 둡니다. 여기서는 압축기 자체가 무엇을 하는지만 보여 줍니다.
    # (본 실험에서는 keep_last·skip_system 같은 정책이 얹힙니다.)
    C.set_policy(keep_last=0, min_chars=0, skip_system=False)
    comp = C.get("llmlingua")

    out = {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
           "compressor": "llmlingua (LLMLingua-2 · xlm-roberta-large)",
           "policy": "keep_last=0 · min_chars=0 · skip_system=False "
                     "(압축기 자체만 보이려고 정책을 껐습니다)",
           "rates": RATES, "cases": []}

    for c in CASES:
        rec = {k: c[k] for k in ("id", "label", "why", "role")}
        rec["before"] = c["text"]
        rec["before_tokens"] = ntok(c["text"])
        rec["variants"] = []
        for r in RATES:
            t0 = time.perf_counter()
            msgs = comp([{"role": c["role"], "content": c["text"]}], r)
            el = time.perf_counter() - t0
            after = msgs[0]["content"]
            rec["variants"].append({
                "rate": r, "after": after, "after_tokens": ntok(after),
                "reduction": 1 - ntok(after) / max(1, rec["before_tokens"]),
                "latency_s": round(el, 2),
            })
            print(f"  {c['id']:12s} rate={r}  "
                  f"{rec['before_tokens']:>5} → {ntok(after):>5} tok  "
                  f"({(1-ntok(after)/max(1,rec['before_tokens']))*100:4.1f}%)  "
                  f"{el:.1f}s")
        out["cases"].append(rec)

    p = Path(a.out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"▸ {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
