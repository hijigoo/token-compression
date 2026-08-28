#!/usr/bin/env python3
"""합성 코퍼스 생성기.

랩을 돌리려면 입력이 있어야 하는데, 실제 문서는 커밋할 수 없습니다.
그래서 **고객 데이터가 섞일 수 없는 합성 코퍼스**를 스크립트로 만듭니다.
스크립트가 곧 획득 절차이므로 `fetch.sh` 없이도 재현됩니다.

    python make_synthetic.py            # 전체
    python make_synthetic.py structured # 하나만

만드는 코퍼스

    sample              (기존, 손으로 쓴 12건 — 이 스크립트가 건드리지 않습니다)
    sample-structured   구조화 텍스트 12건 — 01-lossless-structure 용
    sample-long         장문 문서 8건      — 02-handle-ref, 03-summarize-llm 용

⚠️ 코퍼스는 **불변**입니다. 내용을 바꿔야 하면 이 파일을 고치지 말고
`-v2` 이름으로 새로 추가하세요. 과거 runs/ 와 비교가 조용히 깨집니다.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent


def write(name: str, cases: list, note: str) -> None:
    d = HERE / name
    d.mkdir(parents=True, exist_ok=True)
    with (d / "cases.jsonl").open("w", encoding="utf-8") as f:
        for c in cases:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    (d / "manifest.json").write_text(json.dumps({
        "name": name,
        "source": "합성 — labs/data/make_synthetic.py",
        "revision": "v1",
        "license": "저장소와 동일 (합성 데이터, 실제 고객 데이터 없음)",
        "n_samples": len(cases),
        "added_at": date.today().isoformat(),
        "note": note,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    chars = sum(len(c["text"]) for c in cases)
    print(f"  {name:20s} {len(cases):2d}건 · {chars:6,}자 · {d}")


# ══════════════════════════════════════════════════════════════════
# sample-structured — 구조가 있는 텍스트
#
# 무손실 변환은 **표현의 중복**을 먹고 삽니다. JSON 은 키를 행마다 반복하고,
# 로그는 접두사를 줄마다 반복하며, 들여쓰기는 의미가 없는데도 토큰을 씁니다.
# 산문에는 그런 중복이 없어서 무손실 변환이 할 일이 없습니다 — 그 대비를
# 보려고 이 코퍼스를 따로 둡니다.
# ══════════════════════════════════════════════════════════════════

def structured() -> list:
    orders = [
        {"order_id": "ORD-20260301-0012", "customer_id": "CUST-88120",
         "amount": 1284000, "status": "paid", "region": "seoul"},
        {"order_id": "ORD-20260301-0013", "customer_id": "CUST-88121",
         "amount": 32450, "status": "refunded", "region": "busan"},
        {"order_id": "ORD-20260301-0014", "customer_id": "CUST-88122",
         "amount": 907300, "status": "paid", "region": "seoul"},
        {"order_id": "ORD-20260301-0015", "customer_id": "CUST-88123",
         "amount": 15900, "status": "pending", "region": "daegu"},
    ]
    metrics = [
        {"date": "2026-03-01", "requests": 128400, "errors": 312, "p95_ms": 842},
        {"date": "2026-03-02", "requests": 131200, "errors": 289, "p95_ms": 811},
        {"date": "2026-03-03", "requests": 96500, "errors": 1904, "p95_ms": 2310},
        {"date": "2026-03-04", "requests": 127800, "errors": 274, "p95_ms": 795},
    ]

    log_a = "\n".join(
        f"2026-03-03T14:2{i}:11.482Z INFO  [payment-api] [trace=8f2a1c] "
        f"handler=refund status=ok latency_ms={180 + i * 7}"
        for i in range(6)
    ) + ("\n2026-03-03T14:26:11.482Z ERROR [payment-api] [trace=8f2a1c] "
         "handler=refund status=fail code=PG-5021 latency_ms=30150")

    log_b = "\n".join(
        f"2026-03-04T02:1{i}:00.000Z WARN  [batch-settle] [job=nightly-0304] "
        f"step=aggregate shard={i} retry=1 msg=lock_timeout"
        for i in range(7)
    )

    kv_a = """
    service            :   payment-api
    environment        :   production
    region             :   koreacentral
    replicas           :   6
    timeout_seconds    :   30
    retry_max          :   3
    circuit_breaker    :   enabled
    error_budget_pct   :   0.5
    """

    kv_b = """
    db_host            :   pg-prod-03.internal
    db_port            :   5432
    pool_min           :   4
    pool_max           :   40
    statement_timeout  :   15000
    ssl_mode           :   require
    failover_target    :   pg-prod-04.internal
    """

    md_a = """| 요금제      | 월 기본료 | 제공 호출 수 | 초과 단가 | 지원 |
|------------|----------|------------|----------|------|
| Free       | 0        | 1,000      | 미제공    | 없음 |
| Starter    | 49,000   | 50,000     | 1.2       | 이메일 |
| Business   | 190,000  | 500,000    | 0.8       | 24시간 |
| Enterprise | 협의      | 무제한      | 0.4       | 전담 |"""

    md_b = """| 리전        | 인스턴스 | vCPU | 메모리GB | 시간당 |
|------------|---------|------|---------|-------|
| koreacentral | D4s_v5  | 4    | 16      | 0.232 |
| koreacentral | D8s_v5  | 8    | 32      | 0.464 |
| japaneast    | D4s_v5  | 4    | 16      | 0.218 |
| japaneast    | D8s_v5  | 8    | 32      | 0.436 |"""

    xml_a = """<config>
        <service name="payment-api" version="4.2.1">
            <endpoint protocol="https" host="api.internal" port="8443" />
            <retry max="3" backoff="exponential" initialMs="200" />
            <timeout connectMs="3000" readMs="30000" />
        </service>
        <alerting>
            <rule name="error-rate" threshold="0.02" window="5m" severity="P2" />
            <rule name="latency-p95" threshold="1500" window="5m" severity="P3" />
        </alerting>
    </config>"""

    xml_b = """<deployment>
        <replicaSet name="worker" desired="12" ready="11" />
        <resources cpuRequest="500m" cpuLimit="2000m" memRequest="1Gi" memLimit="4Gi" />
        <probe type="liveness" path="/healthz" periodSeconds="10" failureThreshold="3" />
        <probe type="readiness" path="/ready" periodSeconds="5" failureThreshold="2" />
    </deployment>"""

    return [
        {"id": "st-001", "text": json.dumps(orders, ensure_ascii=False, indent=2),
         "question": "환불된 주문의 주문번호와 금액은?",
         "must_include": ["ORD-20260301-0013", "32450"],
         "meta": {"kind": "json-array"}},
        {"id": "st-002", "text": json.dumps(metrics, ensure_ascii=False, indent=2),
         "question": "오류가 가장 많았던 날짜와 오류 수는?",
         "must_include": ["2026-03-03", "1904"],
         "meta": {"kind": "json-array"}},
        {"id": "st-003", "text": json.dumps(
            {"app": {"name": "payment-api", "version": "4.2.1",
                     "limits": {"rps": 2000, "burst": 5000, "concurrency": 256},
                     "features": {"refund": True, "partial_refund": False,
                                  "installment": True}},
             "owner": {"team": "billing", "oncall": "billing-oncall",
                       "escalation": ["L2-billing", "L3-platform"]}},
            ensure_ascii=False, indent=4),
         "question": "부분 환불 기능은 켜져 있나? RPS 한도는?",
         "must_include": ["partial_refund", "false", "2000"],
         "meta": {"kind": "json-nested"}},
        {"id": "st-004", "text": json.dumps(
            {"cluster": {"name": "aks-prod-01", "nodePools": [
                {"name": "system", "vmSize": "D4s_v5", "count": 3, "spot": False},
                {"name": "user", "vmSize": "D8s_v5", "count": 9, "spot": False},
                {"name": "batch", "vmSize": "D16s_v5", "count": 4, "spot": True}]},
             "network": {"plugin": "azure-cni-overlay", "podCidr": "10.244.0.0/16"}},
            ensure_ascii=False, indent=4),
         "question": "스팟 인스턴스를 쓰는 노드풀과 대수는?",
         "must_include": ["batch", "true", "4"],
         "meta": {"kind": "json-nested"}},
        {"id": "st-005", "text": log_a,
         "question": "실패한 요청의 오류 코드와 지연 시간은?",
         "must_include": ["PG-5021", "30150"],
         "meta": {"kind": "log-repeat"}},
        {"id": "st-006", "text": log_b,
         "question": "야간 배치에서 반복된 경고 사유는?",
         "must_include": ["lock_timeout", "nightly-0304"],
         "meta": {"kind": "log-repeat"}},
        {"id": "st-007", "text": kv_a,
         "question": "재시도 최대 횟수와 오류 예산은?",
         "must_include": ["retry_max", "3", "0.5"],
         "meta": {"kind": "kv-space"}},
        {"id": "st-008", "text": kv_b,
         "question": "커넥션 풀 최대치와 장애 조치 대상은?",
         "must_include": ["40", "pg-prod-04.internal"],
         "meta": {"kind": "kv-space"}},
        {"id": "st-009", "text": md_a,
         "question": "Business 요금제의 초과 단가는?",
         "must_include": ["Business", "0.8"],
         "meta": {"kind": "md-table"}},
        {"id": "st-010", "text": md_b,
         "question": "japaneast 의 D8s_v5 시간당 단가는?",
         "must_include": ["japaneast", "0.436"],
         "meta": {"kind": "md-table"}},
        {"id": "st-011", "text": xml_a,
         "question": "지연 경보의 임계값과 심각도는?",
         "must_include": ["1500", "P3"],
         "meta": {"kind": "xml"}},
        {"id": "st-012", "text": xml_b,
         "question": "readiness 프로브의 주기와 실패 임계는?",
         "must_include": ["readiness", "5", "2"],
         "meta": {"kind": "xml"}},
    ]


# ══════════════════════════════════════════════════════════════════
# sample-long — 여러 절로 나뉜 장문
#
# 참조 핸들과 요약은 **긴 문서에서만** 이득이 납니다. 짧은 글은 다이제스트
# 오버헤드가 절감을 잡아먹습니다. 그래서 정답이 **한 절에만** 들어 있는
# 장문을 따로 만듭니다. 라우터가 그 절을 고르지 못하면 보존율이 무너지고,
# 그게 이 랩에서 봐야 할 실패 모드입니다.
# ══════════════════════════════════════════════════════════════════

FILLER = {
    "개요": "본 문서는 서비스 운영 정책을 정리한 것입니다. 각 절은 독립적으로 개정될 수 있으며 "
            "개정 시 시행일을 별도로 공지합니다. 문서의 해석에 다툼이 있을 경우 운영위원회의 "
            "결정을 따릅니다. 본 문서에 정하지 않은 사항은 관련 법령과 개별 계약을 따릅니다.",
    "적용범위": "본 정책은 유료 요금제를 사용하는 모든 조직에 적용됩니다. 체험판 계정과 내부 "
                "테스트 계정은 적용 대상에서 제외됩니다. 파트너를 통해 재판매된 계약의 경우 "
                "파트너 계약이 우선하며 본 정책은 보충적으로 적용됩니다.",
    "용어정의": "‘영업일’은 주말과 법정 공휴일을 제외한 날을 말합니다. ‘장애’는 핵심 기능을 "
                "사용할 수 없는 상태를 말하며 성능 저하는 포함하지 않습니다. ‘신청일’은 접수가 "
                "완료된 시점이 속한 날을 기준으로 합니다.",
    "문의": "정책 관련 문의는 담당 조직의 관리자를 통해 접수해 주시기 바랍니다. 개별 사용자의 "
            "직접 문의는 접수되지 않습니다. 접수된 문의는 순차적으로 회신되며 회신 순서는 "
            "접수 순서를 따릅니다.",
    "개정이력": "본 문서는 분기마다 정기 검토를 거칩니다. 정기 검토 외의 개정은 운영위원회 "
                "의결을 거쳐 시행합니다. 개정 내용은 시행일 14일 전에 공지합니다.",
    "부칙": "본 정책은 공지된 시행일부터 적용됩니다. 시행일 이전에 접수된 건은 종전 규정을 "
            "따릅니다. 종전 규정과 본 정책이 충돌하는 경우 접수 시점의 규정을 적용합니다.",
}

LONG_SPECS = [
    ("lg-001", "환불 정책", "환불 수수료율과 면제 조건은?", ["12%", "5일", "면제"],
     "환불규정",
     "환불은 결제일로부터 30일 이내에 신청할 수 있습니다. 환불 시 결제금액의 12%를 "
     "수수료로 공제합니다. 다만 결제 후 5일 이내에 취소하는 경우 수수료를 면제합니다. "
     "부분 환불은 지원하지 않으며 전액 환불만 가능합니다.", "policy"),
    ("lg-002", "장애 보상", "가용률이 99.0% 미만이면 보상 비율은?", ["99.0%", "25%"],
     "보상기준",
     "월 가용률이 99.9% 미만이면 월 이용료의 10%를 크레딧으로 보상합니다. 99.5% 미만이면 "
     "15%, 99.0% 미만이면 25%를 보상합니다. 크레딧은 현금으로 환급되지 않으며 다음 달 "
     "이용료에서 차감됩니다.", "policy"),
    ("lg-003", "데이터 보관", "로그 보관 기간과 삭제 요청 처리 기한은?", ["180일", "30일"],
     "보관기간",
     "접속 로그는 180일간 보관한 뒤 자동 파기합니다. 결제 기록은 관련 법령에 따라 5년간 "
     "보관합니다. 이용자의 삭제 요청은 접수일로부터 30일 이내에 처리합니다. 백업본은 "
     "최대 90일간 남을 수 있습니다.", "policy"),
    ("lg-004", "장애 대응", "P1 장애의 최초 응답 시간과 에스컬레이션 대상은?",
     ["15분", "L3-platform"], "대응절차",
     "P1 장애는 접수 후 15분 이내에 최초 응답합니다. 60분 내에 복구되지 않으면 "
     "L3-platform 으로 에스컬레이션합니다. P2 는 4시간, P3 는 영업일 기준 2일 이내에 "
     "응답합니다. 야간 접수 건도 P1 은 동일한 기준을 적용합니다.", "runbook"),
    ("lg-005", "배포 절차", "프로덕션 배포 승인자와 금지 시간대는?",
     ["2인", "금요일 15시"], "배포규칙",
     "프로덕션 배포는 리뷰어 2인의 승인을 받아야 합니다. 금요일 15시 이후와 공휴일 "
     "전날에는 배포를 금지합니다. 긴급 배포는 온콜 책임자의 사후 승인으로 갈음할 수 "
     "있으며 24시간 내에 기록을 남겨야 합니다.", "runbook"),
    ("lg-006", "접근 권한", "운영 DB 직접 접근의 승인 유효 기간은?", ["4시간", "재승인"],
     "권한관리",
     "운영 DB 직접 접근은 임시 권한으로만 부여하며 승인은 4시간 동안 유효합니다. "
     "유효 기간이 지나면 자동 회수되고 연장하려면 재승인을 받아야 합니다. 모든 조회 "
     "쿼리는 감사 로그에 기록됩니다.", "runbook"),
    ("lg-007", "요금 산정", "초과 사용분의 단가와 청구 주기는?", ["1.2", "익월 5일"],
     "과금기준",
     "기본 제공량을 초과한 호출은 1,000건당 1.2 크레딧으로 산정합니다. 초과분은 익월 "
     "5일에 일괄 청구됩니다. 월 중 요금제를 변경하면 일할 계산합니다. 미납이 30일을 "
     "넘으면 서비스가 중지될 수 있습니다.", "billing"),
    ("lg-008", "계약 해지", "중도 해지 위약금과 통지 기한은?", ["잔여 기간", "30일 전"],
     "해지조건",
     "연 단위 계약을 중도 해지하는 경우 잔여 기간 이용료의 30%를 위약금으로 부담합니다. "
     "해지는 희망일 30일 전까지 서면으로 통지해야 합니다. 통지 없이 해지한 경우 다음 "
     "결제 주기까지 요금이 청구됩니다.", "billing"),
]


def long_docs() -> list:
    """정답 절 1개 + 무관한 절 6개로 문서를 조립합니다.

    라우터가 정답 절을 못 고르면 보존율이 0 이 됩니다. 그게 보여야 할 실패입니다.
    """
    out = []
    order = list(FILLER.items())
    for i, (cid, title, q, must, sec_title, sec_body, kind) in enumerate(LONG_SPECS):
        # 정답 절의 위치를 문서마다 다르게 둡니다. 항상 앞에 있으면
        # '앞에서 자르기' 만으로도 통과해서 라우터를 평가할 수 없습니다.
        pos = i % (len(order) + 1)
        secs = [(k, v) for k, v in order]
        secs.insert(pos, (sec_title, sec_body))
        body = "\n\n".join(f"■ {k}\n{v}" for k, v in secs)
        out.append({
            "id": cid,
            "text": f"[{title}]\n\n{body}",
            "question": q,
            "must_include": must,
            "meta": {"kind": kind, "answer_section": sec_title, "answer_pos": pos,
                     "n_sections": len(secs)},
        })
    return out


TARGETS = {
    "structured": ("sample-structured", structured,
                   "구조화 텍스트(JSON/로그/키값/표/XML) 6종 각 2건. "
                   "무손실 변환이 먹는 '표현의 중복'이 들어 있습니다."),
    "long": ("sample-long", long_docs,
             "7개 절로 나뉜 장문 8건. 정답은 항상 한 절에만 있고 위치는 문서마다 "
             "다릅니다. 참조 핸들·요약의 라우팅 실패를 드러내려는 구성입니다."),
}


def main(argv: list) -> int:
    want = argv[1:] or list(TARGETS)
    unknown = [w for w in want if w not in TARGETS]
    if unknown:
        print(f"알 수 없는 코퍼스: {unknown} (가능: {list(TARGETS)})", file=sys.stderr)
        return 2
    print("합성 코퍼스 생성")
    for w in want:
        name, fn, note = TARGETS[w]
        write(name, fn(), note)
    print("\n코퍼스는 불변입니다. 내용을 바꿔야 하면 -v2 로 새로 추가하세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
