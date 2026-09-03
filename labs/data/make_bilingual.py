#!/usr/bin/env python3
"""한·영 이중언어 코퍼스 생성기.

    python make_bilingual.py

## 왜 따로 만드나

토큰 프루닝(`04-llmlingua`)은 **작은 언어모델이 토큰별 중요도를 매겨** 덜
중요한 토큰을 지우는 방식입니다. 그래서 앞선 랩들과 성격이 다릅니다.

    01 무손실     규칙 기반. 언어와 무관합니다
    03 요약       큰 모델이 다시 씁니다. 다국어를 잘합니다
    04 프루닝     **작은 모델의 언어별 실력에 직접 좌우됩니다**

LLMLingua 계열 모델은 대부분 영어 코퍼스로 학습됐습니다. 한국어에서 같은
성능이 나오는지는 **재봐야 알 수 있고**, 그게 이 코퍼스의 목적입니다.

## 구성

같은 내용을 한국어와 영어로 각각 씁니다. 번역이 아니라 **같은 사실을 담은
쌍**입니다. `pair_id` 로 묶여 있어 언어별 차이를 케이스 단위로 비교할 수
있습니다.

    ko-001  한국어  ─┐
                     ├─ pair=p01  같은 사실, 같은 질문
    en-001  영어    ─┘

⚠️ 코퍼스는 **불변**입니다. 바꿔야 하면 이 파일을 고치지 말고 `-v2` 로
새로 추가하세요. 과거 runs/ 와 비교가 조용히 깨집니다.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent

# ══════════════════════════════════════════════════════════════════
# 쌍으로 된 케이스
#
# 프루닝이 무엇을 먼저 버리는지 보려고, 앞선 랩과 같은 유형을 씁니다.
#   numeric     숫자·금액
#   negation    부정어 — 뒤집히면 답이 정반대가 됩니다
#   identifier  코드·사번 — 문맥이 없어 지워지기 쉽습니다
#   structured  표·목록
#   longdoc     여러 문단. 프루닝이 이득을 내려면 길이가 필요합니다
# ══════════════════════════════════════════════════════════════════

PAIRS = [
    # ── numeric ────────────────────────────────────────────────
    ("p01", "numeric",
     dict(text="2026년 3월 결제 내역입니다. 총 결제 건수는 1,284건이며 결제 총액은 "
               "32,450,000원입니다. 이 중 환불 처리된 금액은 1,280,500원으로 전체의 "
               "3.9%에 해당합니다. 2월 대비 결제 총액은 12.4% 증가하였고 환불률은 "
               "0.7%p 감소했습니다. 카드 결제가 78%, 계좌이체가 22%를 차지했습니다.",
          question="3월 결제 총액과 환불액은?",
          must_include=["32,450,000", "1,280,500"]),
     dict(text="Payment summary for March 2026. Total transactions were 1,284 and the "
               "total amount charged was 32,450,000 KRW. Of that, 1,280,500 KRW was "
               "refunded, which is 3.9% of the total. Compared to February, the charged "
               "amount rose 12.4% and the refund rate fell 0.7 percentage points. Card "
               "payments accounted for 78% and bank transfers for 22%.",
          question="What were the total charged and refunded amounts in March?",
          must_include=["32,450,000", "1,280,500"])),

    # ── negation ───────────────────────────────────────────────
    ("p02", "negation",
     dict(text="환불 신청은 영업일 기준 09시부터 18시까지 접수됩니다. 주말 및 공휴일에는 "
               "접수되지 않습니다. 심야 시간대에는 시스템 점검으로 인해 신청이 처리되지 "
               "않습니다. 접수된 건은 영업일 기준 3일 이내 처리됩니다. 부분 환불은 "
               "지원하지 않으며 전액 환불만 가능합니다.",
          question="부분 환불이 가능한가?",
          must_include=["부분 환불", "않"]),
     dict(text="Refund requests are accepted on business days from 09:00 to 18:00. "
               "They are not accepted on weekends or public holidays. During late night "
               "hours requests are not processed because of system maintenance. Accepted "
               "requests are handled within 3 business days. Partial refunds are not "
               "supported; only full refunds are available.",
          question="Are partial refunds supported?",
          must_include=["Partial refunds", "not"])),

    # ── identifier ─────────────────────────────────────────────
    ("p03", "identifier",
     dict(text="장애 보고서입니다. 인시던트 번호는 INC-2026-0314 이며 영향받은 클러스터는 "
               "prod-eastus-aks-01 입니다. 담당자 사번은 EMP-88213 이고 에스컬레이션 "
               "대상은 L3-platform 입니다. 근본 원인은 인증서 만료였으며 복구까지 "
               "47분이 걸렸습니다. 재발 방지 과제는 TASK-5521 로 등록되었습니다.",
          question="인시던트 번호와 에스컬레이션 대상은?",
          must_include=["INC-2026-0314", "L3-platform"]),
     dict(text="Incident report. The incident number is INC-2026-0314 and the affected "
               "cluster is prod-eastus-aks-01. The assigned engineer is EMP-88213 and the "
               "escalation target is L3-platform. The root cause was an expired "
               "certificate and recovery took 47 minutes. The follow-up action was filed "
               "as TASK-5521.",
          question="What is the incident number and the escalation target?",
          must_include=["INC-2026-0314", "L3-platform"])),

    # ── structured ─────────────────────────────────────────────
    ("p04", "structured",
     dict(text="엔드포인트별 성능 지표입니다. /v1/chat 은 초당 120건, p50 340ms, "
               "p95 1850ms, 오류율 0.4% 입니다. /v1/embed 는 초당 450건, p50 45ms, "
               "p95 120ms, 오류율 0.1% 입니다. /v1/rerank 는 초당 60건, p50 780ms, "
               "p95 2400ms, 오류율 1.2% 입니다. /v1/search 는 초당 200건, p50 210ms, "
               "p95 900ms, 오류율 0.3% 입니다.",
          question="p95 지연이 가장 큰 엔드포인트와 그 값은?",
          must_include=["/v1/rerank", "2400"]),
     dict(text="Per-endpoint performance metrics. /v1/chat handles 120 requests per "
               "second with p50 340ms, p95 1850ms and a 0.4% error rate. /v1/embed "
               "handles 450 per second with p50 45ms, p95 120ms and 0.1% errors. "
               "/v1/rerank handles 60 per second with p50 780ms, p95 2400ms and 1.2% "
               "errors. /v1/search handles 200 per second with p50 210ms, p95 900ms "
               "and 0.3% errors.",
          question="Which endpoint has the highest p95 latency and what is it?",
          must_include=["/v1/rerank", "2400"])),

    # ── longdoc ────────────────────────────────────────────────
    # 프루닝은 짧은 글에서 이득이 없습니다. 길이가 있어야 버릴 것이 생깁니다.
    ("p05", "longdoc",
     dict(text="서비스 운영 정책 안내입니다.\n\n"
               "본 문서는 유료 요금제를 사용하는 모든 조직에 적용됩니다. 체험판 계정과 "
               "내부 테스트 계정은 적용 대상에서 제외됩니다. 파트너를 통해 재판매된 "
               "계약의 경우 파트너 계약이 우선하며 본 정책은 보충적으로 적용됩니다.\n\n"
               "영업일은 주말과 법정 공휴일을 제외한 날을 말합니다. 장애는 핵심 기능을 "
               "사용할 수 없는 상태를 말하며 성능 저하는 포함하지 않습니다. 신청일은 "
               "접수가 완료된 시점이 속한 날을 기준으로 합니다.\n\n"
               "월 가용률이 99.9% 미만이면 월 이용료의 10%를 크레딧으로 보상합니다. "
               "99.5% 미만이면 15%, 99.0% 미만이면 25%를 보상합니다. 크레딧은 현금으로 "
               "환급되지 않으며 다음 달 이용료에서 차감됩니다.\n\n"
               "정책 관련 문의는 담당 조직의 관리자를 통해 접수해 주시기 바랍니다. "
               "개별 사용자의 직접 문의는 접수되지 않습니다. 본 문서는 분기마다 정기 "
               "검토를 거치며 개정 내용은 시행일 14일 전에 공지합니다.",
          question="가용률이 99.0% 미만이면 보상 비율은?",
          must_include=["99.0%", "25%"]),
     dict(text="Service operations policy.\n\n"
               "This document applies to every organization on a paid plan. Trial "
               "accounts and internal test accounts are excluded. For contracts resold "
               "through a partner, the partner agreement takes precedence and this "
               "policy applies only as a supplement.\n\n"
               "A business day means a day other than a weekend or a public holiday. An "
               "outage means core functionality is unavailable; degraded performance is "
               "not included. The request date is the day on which intake was "
               "completed.\n\n"
               "If monthly availability falls below 99.9%, we credit 10% of the monthly "
               "fee. Below 99.5% the credit is 15%, and below 99.0% it is 25%. Credits "
               "are not refundable in cash and are deducted from the following month's "
               "fee.\n\n"
               "Policy questions should be submitted through your organization's "
               "administrator. Direct requests from individual users are not accepted. "
               "This document is reviewed quarterly and any revision is announced 14 "
               "days before it takes effect.",
          question="What is the credit rate when availability falls below 99.0%?",
          must_include=["99.0%", "25%"])),

    # ── longdoc 2 ──────────────────────────────────────────────
    ("p06", "longdoc",
     dict(text="배포 및 접근 권한 지침입니다.\n\n"
               "프로덕션 배포는 리뷰어 2인의 승인을 받아야 합니다. 금요일 15시 이후와 "
               "공휴일 전날에는 배포를 금지합니다. 긴급 배포는 온콜 책임자의 사후 "
               "승인으로 갈음할 수 있으며 24시간 내에 기록을 남겨야 합니다.\n\n"
               "운영 데이터베이스 직접 접근은 임시 권한으로만 부여하며 승인은 4시간 "
               "동안 유효합니다. 유효 기간이 지나면 자동 회수되고 연장하려면 재승인을 "
               "받아야 합니다. 모든 조회 쿼리는 감사 로그에 기록됩니다.\n\n"
               "P1 장애는 접수 후 15분 이내에 최초 응답합니다. 60분 내에 복구되지 "
               "않으면 상위 조직으로 에스컬레이션합니다. P2는 4시간, P3는 영업일 기준 "
               "2일 이내에 응답합니다. 야간 접수 건도 P1은 동일한 기준을 적용합니다.\n\n"
               "접속 로그는 180일간 보관한 뒤 자동 파기합니다. 결제 기록은 관련 법령에 "
               "따라 5년간 보관합니다. 이용자의 삭제 요청은 접수일로부터 30일 이내에 "
               "처리합니다.",
          question="운영 DB 직접 접근 승인의 유효 기간은?",
          must_include=["4시간", "재승인"]),
     dict(text="Deployment and access control guidelines.\n\n"
               "Production deployments require approval from two reviewers. Deployments "
               "are prohibited after 15:00 on Fridays and on the day before a public "
               "holiday. An emergency deployment may proceed with retroactive approval "
               "from the on-call lead, and must be recorded within 24 hours.\n\n"
               "Direct access to the production database is granted only as a temporary "
               "permission, and the approval is valid for 4 hours. Once it expires the "
               "permission is revoked automatically and an extension requires "
               "re-approval. Every query is written to the audit log.\n\n"
               "A P1 incident receives a first response within 15 minutes. If it is not "
               "resolved within 60 minutes it is escalated to the upper organization. P2 "
               "is answered within 4 hours and P3 within 2 business days. P1 follows the "
               "same standard even when reported overnight.\n\n"
               "Access logs are retained for 180 days and then destroyed. Payment "
               "records are retained for 5 years as required by law. A user's deletion "
               "request is processed within 30 days of receipt.",
          question="How long is an approval for direct production database access valid?",
          must_include=["4 hours", "re-approval"])),
]


def build() -> list:
    out = []
    for pid, kind, ko, en in PAIRS:
        n = pid[1:]
        out.append({"id": f"ko-{n}", "text": ko["text"], "question": ko["question"],
                    "must_include": ko["must_include"],
                    "meta": {"kind": kind, "lang": "ko", "pair_id": pid}})
        out.append({"id": f"en-{n}", "text": en["text"], "question": en["question"],
                    "must_include": en["must_include"],
                    "meta": {"kind": kind, "lang": "en", "pair_id": pid}})
    return out


def main() -> int:
    cases = build()
    d = HERE / "sample-bilingual"
    d.mkdir(parents=True, exist_ok=True)
    with (d / "cases.jsonl").open("w", encoding="utf-8") as f:
        for c in cases:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    ko = [c for c in cases if c["meta"]["lang"] == "ko"]
    en = [c for c in cases if c["meta"]["lang"] == "en"]
    (d / "manifest.json").write_text(json.dumps({
        "name": "sample-bilingual",
        "source": "합성 — labs/data/make_bilingual.py",
        "revision": "v1",
        "license": "저장소와 동일 (합성 데이터, 실제 고객 데이터 없음)",
        "n_samples": len(cases),
        "added_at": date.today().isoformat(),
        "note": f"한국어 {len(ko)}건 · 영어 {len(en)}건. 같은 사실을 담은 쌍이며 "
                f"meta.pair_id 로 묶여 있습니다. 토큰 프루닝의 언어별 성능 차이를 "
                f"보려고 만들었습니다.",
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("이중언어 코퍼스 생성")
    print(f"  {d}")
    print(f"  한국어 {len(ko)}건 · {sum(len(c['text']) for c in ko):,}자")
    print(f"  영어   {len(en)}건 · {sum(len(c['text']) for c in en):,}자")
    kinds = {}
    for c in cases:
        kinds[c["meta"]["kind"]] = kinds.get(c["meta"]["kind"], 0) + 1
    print(f"  유형 {kinds}")
    print("\n코퍼스는 불변입니다. 내용을 바꿔야 하면 -v2 로 새로 추가하세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
