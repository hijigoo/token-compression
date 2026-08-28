#!/usr/bin/env python3
"""랩 노트북 빌더.

노트북 3개(00/01/02)를 같은 뼈대로 만듭니다. 손으로 JSON 을 만지면 셀 순서와
따옴표에서 사고가 나므로 스크립트로 찍습니다.

    python build_notebooks.py            # 전체
    python build_notebooks.py 01         # 하나만

각 노트북의 마지막 두 절은 셋 다 같습니다.

    N.   configs/*.yaml 을 전부 찾아 하나씩 돌립니다
    N+1. 조건을 나란히 놓고 비교합니다

"조건 1개 = 파일 1개" 라는 규칙이 있으니, 노트북은 폴더를 훑기만 하면
그 랩의 모든 조건을 덮습니다. 설정을 추가해도 노트북은 안 고쳐도 됩니다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def md(s: str) -> dict:
    return {"cell_type": "markdown", "metadata": {},
            "source": s.strip("\n").splitlines(keepends=True)}


def code(s: str) -> dict:
    return {"cell_type": "code", "metadata": {}, "execution_count": None,
            "outputs": [], "source": s.strip("\n").splitlines(keepends=True)}


def notebook(cells: list) -> dict:
    return {
        "cells": cells,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python",
                           "name": "python3"},
            "language_info": {"name": "python", "pygments_lexer": "ipython3"},
        },
        "nbformat": 4, "nbformat_minor": 5,
    }


# ══════════════════════════════════════════════════════════════════
# 공통 조각
# ══════════════════════════════════════════════════════════════════

BOOTSTRAP = '''
import sys
from pathlib import Path

LAB = Path.cwd().resolve()
LABS = LAB.parents[0]                  # labs/<이 랩> -> labs
sys.path.insert(0, str(LABS))
sys.path.insert(0, str(LAB))           # 이 랩의 모듈(transforms, blocks 등)

from kit import VERSION, config as C, dataset, env, metrics, tokens as T
from kit.display import table, pct
from kit.runner import Run

# .env 는 labs/.env → 저장소 루트 .env → scripts/explore/.env 순으로 찾습니다.
env.load(verbose=True)

RUNS = LABS.parent / "runs"
print("kit", VERSION, "· 랩", LAB.name)
'''

ALL_CONFIGS_MD = '''
## {n}. 이 랩의 모든 조건 돌려보기

**조건 1개 = 파일 1개**입니다. `configs/` 를 훑으면 이 랩이 답할 수 있는
질문이 전부 나옵니다. 설정을 새로 추가해도 이 셀은 고칠 필요가 없습니다.

각 조건은 `runs/{lab}/<설정이름>/<시각>/` 에 따로 기록됩니다. 나중에
"그때 무엇을 돌렸나" 를 설정 이름만 보고 알 수 있게 하려는 것입니다.
'''

COMPARE_MD = '''
## {n}. 조건 비교

같은 코드에 조건만 바꿔 돌린 결과입니다. **숫자 하나가 아니라 표를 보세요.**
어떤 조건에서 무엇을 얻고 무엇을 잃는지가 이 랩의 결론입니다.
'''


def config_table_cell(extra_cols: str = "", extra_vals: str = "") -> str:
    return f'''
rows = []
for name, m, out in results:
    rows.append([
        name,
        m.get("dataset_name", "-"),
        m["n"],
        f'{{m["tokens_before"]:,}} → {{m["tokens_after"]:,}}',
        pct(m["saved"]),
        pct(m.get("survival_mean")),
        pct(m.get("survival_worst")),{extra_vals}
    ])

table(
    ["설정", "코퍼스", "건수", "토큰", "절감", "평균 보존율", "최저 보존율"{extra_cols}],
    rows,
    align=["left", "left", "right", "right", "right", "right", "right"{
        ", 'right'" * extra_cols.count(",")}],
    title="조건 비교",
    note="절감률만 크면 좋은 게 아닙니다. 최저 보존율과 함께 읽으세요.",
)
'''


# ══════════════════════════════════════════════════════════════════
# 00-baseline
# ══════════════════════════════════════════════════════════════════

def nb_00() -> dict:
    return notebook([
        md('''
# 00-baseline — 압축 없이 통과시키기

압축을 하지 않는 랩입니다. 두 가지를 위해 있습니다.

1. **기준선** — 다른 랩의 "30% 절감" 이 무엇 대비인지 정해 줍니다
2. **하네스 검증** — 압축을 안 했으니 절감은 0%, 보존율은 100% 여야 합니다.
   아니면 압축기가 아니라 **측정 도구가 고장 난 것**입니다

먼저 원리를 한 단계씩 보고, 마지막에 `configs/` 의 모든 조건을 돌립니다.
'''),
        md("## 1. kit 불러오기\n\n랩은 `labs/` 를 경로에 넣고 `from kit import ...` 로 씁니다."),
        code(BOOTSTRAP + '''
print("배포명 기본값:", env.get("AZURE_OPENAI_DEPLOYMENT", "(없음)"))
print("엔드포인트    :", env.mask_endpoint(env.get("AZURE_OPENAI_ENDPOINT")))'''),

        md('''
## 2. 설정 읽기

설정은 코드가 아니라 yaml 에 둡니다. 그래야 `runs/` 경로에 조건 이름이
그대로 남아서, 나중에 무엇을 돌렸는지 알 수 있습니다.
'''),
        code('''
cfg = C.load("configs/noop.yaml")

table(
    ["항목", "값"],
    [["name", cfg.name], ["lab", cfg.lab],
     ["params", cfg.params or "(없음)"],
     ["dataset.path", Path(cfg.dataset["path"]).name],
     ["model", cfg.model],
     ["tokenizer", cfg.tokenizer or "(기본: local)"]],
    align=["left", "left"], title="설정",
)'''),

        md('''
## 3. 토큰을 어떻게 셀 것인가

**두 가지 방식이 있고 설정으로 고릅니다.**

| | `local` | `api` |
|---|---|---|
| 방법 | tiktoken (없으면 문자 근사) | 모델을 호출해 `usage.input_tokens` |
| 비용 | 0 | 텍스트마다 호출 1회 |
| 정확도 | 근사 | **과금 기준 그대로** |
| 포함되는 것 | 텍스트만 | 텍스트 + **메시지 포맷 오버헤드** |

```yaml
tokenizer:
  mode: api            # local | api
  deployment: gpt-5.4  # 생략하면 AZURE_OPENAI_DEPLOYMENT
  cache: true          # 같은 텍스트는 한 번만 호출
```

**`api` 는 캐시가 필수입니다.** 케이스 N건이면 압축 전후로 2N 회를 부르고,
스윕을 10단계 돌리면 그만큼 곱해집니다. 결과는 `kit/.cache/` 에 남습니다.

> **주의** — `api` 값에는 메시지 포맷 오버헤드가 포함됩니다(실측 +6).
> 압축 전후를 같은 방식으로 재므로 **비율 비교는 안전하지만**,
> `local` 값과 나란히 놓으면 안 됩니다. 그래서 `token_backend` 를 기록합니다.
'''),
        code('''
counter = T.make_counter(cfg.tokenizer, cfg.model)
print("측정 방식:", counter.backend)

sample = "환불 수수료는 결제금액의 10%입니다."
print(f"예시 {len(sample)}자 → {counter(sample):,} 토큰")'''),

        md('''
## 4. 코퍼스 살펴보기

`must_include` 는 **정답에 꼭 필요한 문자열**입니다. 이게 있어야 보존율을
잴 수 있고, LLM 호출이 없으므로 스윕을 수백 번 돌려도 비용이 0 입니다.
'''),
        code('''
cases = dataset.load(cfg.dataset["path"], limit=cfg.dataset.get("limit"))
info = dataset.summarize(cases)

table(
    ["항목", "값"],
    [["케이스", f'{info["n_cases"]}건'],
     ["총 길이", f'{info["n_chars"]:,}자'],
     ["must_include 보유", f'{info["with_must_include"]}건'],
     ["유형", ", ".join(f"{k}×{v}" for k, v in info["kinds"].items())]],
    align=["left", "left"], title="코퍼스",
)

c = cases[0]
print(f"\\n[{c.id}] {c.kind}")
print(f"질문        : {c.question}")
print(f"must_include: {c.must_include}")
print(f"원문        : {c.text[:80]}…")'''),

        md('''
## 5. 압축 — 이 랩은 그대로 통과시킵니다

**모든 랩이 이 시그니처를 씁니다.** 랩을 바꾼다는 건 이 함수 하나를
바꾼다는 뜻이고, 나머지(코퍼스·지표·기록)는 전부 재사용됩니다.
'''),
        code('''
def compress(text: str, **params) -> tuple[str, dict]:
    """압축하지 않습니다. 반환은 (압축문, 메타) 입니다."""
    return text, {}


after, meta = compress(cases[0].text)
print("원문과 동일:", after == cases[0].text)'''),

        md('''
## 6. 집계 — 평균만 보면 안 됩니다

**정답 보존율**은 각 케이스에서 `must_include` 문자열 중 압축 후에도 남은
비율입니다. 100% 면 하나도 안 잃은 것입니다.

집계는 평균과 함께 **최저값**과 **유형별 분해**를 항상 냅니다.

> 평균 90% 여도 한 케이스가 0% 면 그 질문에는 아예 답할 수 없습니다.
> 평균은 그걸 가립니다. **최저 보존율부터 보세요.**
'''),
        code('''
records = [
    metrics.per_case(c.id, c.kind, c.text, compress(c.text, **cfg.params)[0],
                     c.must_include, counter)
    for c in cases
]
m = metrics.aggregate(records, counter)

table(
    ["지표", "값", "정상값", "뜻"],
    [["절감률", pct(m["saved"]), "0.0%", "압축을 안 했으므로"],
     ["토큰", f'{m["tokens_before"]:,} → {m["tokens_after"]:,}', "변화 없음", ""],
     ["평균 보존율", pct(m.get("survival_mean")), "100%", "전체 케이스 평균"],
     ["하위 5%", pct(m.get("survival_p5")), "100%", "나쁜 쪽 5% 지점"],
     ["최저 보존율", pct(m.get("survival_worst")), "100%", "가장 많이 깨진 케이스"],
     ["측정 방식", m["token_backend"], "local 또는 api", "다르면 비교 불가"]],
    align=["left", "right", "right", "left"], title="집계",
)'''),

        md('''
## 7. 하네스 자가 점검

압축을 안 했으니 아래가 성립해야 합니다. 어긋나면 압축기가 아니라
**측정 도구가 고장 난 것**이고, 그 상태로는 다른 랩의 숫자를 믿을 수 없습니다.
'''),
        code('''
problems = []
if m["saved"] != 0.0:
    problems.append(f'절감률이 0 이 아닙니다 ({m["saved"]:.2%}) — 로더가 원문을 바꾸고 있습니다')
if m.get("survival_worst") not in (None, 1.0):
    problems.append(f'최저 보존율이 100% 가 아닙니다 ({m["survival_worst"]:.1%})')

if problems:
    print("하네스 점검 실패")
    for p in problems:
        print("  ✗", p)
else:
    print("하네스 정상 — 다른 랩을 돌려도 됩니다.")'''),

        md(ALL_CONFIGS_MD.format(n=8, lab="00-baseline") + '''
이 랩에는 조건이 둘 있습니다.

| 설정 | 토큰 측정 | 비용 |
|---|---|---|
| `noop.yaml` | `local` (tiktoken) | 0 |
| `noop-api.yaml` | `api` (모델 호출 실측) | 텍스트당 1회, 캐시되면 0 |

`api` 조건은 `.env` 가 없으면 건너뜁니다. 건너뛴 이유를 표에 남겨서,
"돌았는데 결과가 없는" 상태와 "아예 못 돌린" 상태를 구분합니다.
'''),
        code('''
def run_config(path):
    """설정 하나를 끝까지 돌리고 (설정, 지표, 결과경로) 를 돌려줍니다."""
    cfg = C.load(path)
    cases = dataset.load(cfg.dataset["path"], limit=cfg.dataset.get("limit"))
    counter = T.make_counter(cfg.tokenizer, cfg.model)

    run = Run(cfg, RUNS)
    for c in cases:
        after, extra = compress(c.text, **cfg.params)
        run.add(metrics.per_case(c.id, c.kind, c.text, after,
                                 c.must_include, counter, extra),
                before=c.text, after=after)

    m = metrics.aggregate(run.records, counter)
    m["dataset_name"] = Path(cfg.dataset["path"]).name
    counter.save()
    if counter.stats():
        m["token_calls"] = counter.stats()
    return cfg, m, run.finish(m, ["압축 없음. 다른 랩의 절감률은 이 결과를 기준으로 읽습니다."])


results, skipped = [], []
for p in sorted(Path("configs").glob("*.yaml")):
    try:
        cfg, m, out = run_config(p)
        results.append((cfg.name, m, out))
        extra = ""
        if m.get("token_calls"):
            extra = (f' · API {m["token_calls"]["api_calls"]}회'
                     f' · 캐시 {m["token_calls"]["cache_hits"]}회')
        print(f'{p.name:20s} 절감 {m["saved"]:6.1%} · {m["token_backend"]}{extra}')
    except Exception as e:
        skipped.append((p.name, f"{type(e).__name__}: {e}"))
        print(f"{p.name:20s} 건너뜀 — {type(e).__name__}: {str(e)[:80]}")

if skipped:
    print("\\n건너뛴 설정이 있습니다. 자격증명이 없으면 api 조건은 못 돌립니다.")
    print("  cd labs && cp .env.example .env   (또는 cp ../scripts/explore/.env .env)")'''),

        md(COMPARE_MD.format(n=9) + '''
`local` 과 `api` 의 토큰 수가 다른 것이 정상입니다. 차이는 **메시지 포맷
오버헤드**(케이스당 +6)이고, 이건 텍스트가 아니라 역할 구분자 같은
프레이밍입니다. 그래서 두 값을 나란히 놓고 "어느 쪽이 맞다" 를 따지면 안 됩니다.
'''),
        code('''
table(
    ["설정", "측정 방식", "건수", "토큰", "절감", "최저 보존율"],
    [[n, m["token_backend"], m["n"],
      f'{m["tokens_before"]:,} → {m["tokens_after"]:,}',
      pct(m["saved"]), pct(m.get("survival_worst"))]
     for n, m, _ in results],
    align=["left", "left", "right", "right", "right", "right"],
    title="조건 비교",
    note="절감 0% · 최저 보존율 100% 가 두 조건 모두에서 나와야 하네스가 정상입니다.",
)

if len(results) == 2:
    a, b = (m for _, m, _ in results)
    diff = abs(a["tokens_before"] - b["tokens_before"])
    print(f"측정 방식 차이: {diff:,} 토큰 ({diff / max(a["n"], 1):.1f}/건)")
    print("케이스당 +6 이면 메시지 포맷 오버헤드입니다 — 텍스트가 아니라 프레이밍입니다.")'''),

        md('''
## 정리

- **기준선이 없으면 절감률은 의미가 없습니다** — 무엇 대비인지가 있어야 합니다
- **하네스를 먼저 검증합니다** — `kit` 을 고친 뒤에는 항상 여기부터 돌리세요
- **정답 보존율은 평균 대신 최저값** — 평균은 한 케이스의 붕괴를 가립니다
- **측정 방식을 기록합니다** — `local` 과 `api` 는 값이 다르므로 섞으면 안 됩니다

### 다음 랩

[`01-lossless-structure`](../01-lossless-structure/run.ipynb) — 의미를 하나도
안 버리고 표현만 바꿉니다. `compress()` 만 바뀌고 나머지는 그대로입니다.
'''),
    ])


# ══════════════════════════════════════════════════════════════════
# 01-lossless-structure
# ══════════════════════════════════════════════════════════════════

def nb_01() -> dict:
    return notebook([
        md('''
# 01-lossless-structure — 아무것도 안 버리고 줄이기

압축이라고 하면 보통 "덜 중요한 걸 버린다" 를 떠올립니다. 이 랩은 반대입니다.
**아무것도 안 버리고** 토큰만 줄입니다.

가능한 이유는 텍스트에 **내용이 아닌데도 토큰을 먹는 부분**이 있기 때문입니다.

| 무엇이 중복인가 | 어디에 |
|---|---|
| 레코드마다 반복되는 **키 이름** | JSON 배열, API 응답 |
| 줄마다 반복되는 **타임스탬프·서비스명** | 로그 |
| 사람이 보라고 넣은 **들여쓰기** | JSON, XML |
| 세로줄을 맞추려고 채운 **정렬 공백** | 마크다운 표, 설정 파일 |

산문에는 그런 중복이 없습니다. 그래서 같은 코드가 구조화 텍스트에서는
28% 줄이고 산문에서는 1% 줄입니다. **입력이 결과를 정합니다.**
'''),
        md("## 1. kit 과 변환 모듈 불러오기"),
        code(BOOTSTRAP + '''
import transforms as X
from compress import compress, verify_steps

table(
    ["변환", "하는 일", "검증 방법"],
    [[n, t.note,
      "되돌리기" if t.restore else ("정규형 비교" if t.canon else "없음 (손실)")]
     for n, t in X.REGISTRY.items()],
    align=["left", "left", "left"],
    title="등록된 변환",
    note="검증 방법이 없는 변환은 손실로 분류합니다. 무손실은 증명할 수 있어야 합니다.",
)'''),

        md('''
## 2. 무손실을 말이 아니라 코드로 정의하기

"줄었다" 는 쉽게 보입니다. 어려운 건 **"아무것도 안 잃었다" 를 증명**하는
것입니다. 그래서 모든 변환은 자기를 검증하는 방법을 함께 들고 옵니다.

| 방법 | 어떻게 | 쓰는 변환 |
|---|---|---|
| `restore` | 되돌려서 원본과 **글자 단위**로 비교 | `log_dedup` |
| `canon` | 양쪽을 정규형으로 바꿔 비교 | `json_*`, `xml_*`, `md_table_*`, `kv_*` |
| (없음) | 검증 불가 → **손실로 분류** | `ws_collapse` |

정규형 비교가 필요한 이유는, 들여쓰기를 지우면 **되돌릴 수는 없지만 잃은
정보는 없기** 때문입니다. JSON 의 공백은 내용이 아니므로 파싱한 객체가
같으면 같습니다.
'''),
        code('''
import json

before = json.dumps([{"id": "A-1", "amount": 1200, "status": "paid"},
                     {"id": "A-2", "amount": 3400, "status": "refunded"}],
                    ensure_ascii=False, indent=2)

after, meta = compress(before, pipeline=["json_to_table"])
ok, why, checked = verify_steps(meta["_steps"])

print("── 압축 전 ──"); print(before)
print("\\n── 압축 후 ── (\\\\x1f 는 눈에 안 보이는 구분자입니다)")
print(after.replace("\\x1f", " | "))
print(f"\\n검증: {ok} · {why}")
print(f"키 이름이 레코드마다 반복되던 것이 헤더 한 줄로 갔습니다.")'''),

        md('''
## 3. 검사가 진짜 잡는지 확인하기

**일부러 고장 낸 입력으로 확인하지 않은 검사는 믿지 마세요.**
"동작하는 것처럼 보이지만 아무것도 안 하는" 검사는 없느니만 못합니다.

값을 몰래 지우는 변환을 심어서, 검증이 이걸 잡아내는지 봅니다.
'''),
        code('''
def sneaky(text):
    """status 필드를 몰래 버리는 변환. 무손실인 척합니다."""
    o = json.loads(text)
    for r in o:
        r.pop("status", None)
    return True, json.dumps(o, ensure_ascii=False, separators=(",", ":")), {}


X.REGISTRY["sneaky"] = X.Transform("sneaky", sneaky, canon=X.json_canon)

_, bad = compress(before, pipeline=["sneaky"])
print("정상 변환:", verify_steps(compress(before, pipeline=["json_to_table"])[1]["_steps"]))
print("몰래 삭제:", verify_steps(bad["_steps"]))

del X.REGISTRY["sneaky"]
print("\\n검사가 잡았습니다. 잡지 못했다면 이 랩의 '무손실' 은 빈말이 됩니다.")'''),

        md(ALL_CONFIGS_MD.format(n=4, lab="01-lossless-structure") + '''
| 설정 | 입력 | 무엇을 보려고 |
|---|---|---|
| `structure` | 구조화 12건 | 이 랩의 기본 조건 |
| `prose` | 산문 12건 | **대조군** — 같은 코드가 산문에서 무엇을 하나 |
| `structure-lossy-ws` | 구조화 12건 | 공백까지 접으면 얼마를 더 얻고 무엇을 잃나 |
'''),
        code('''
def run_config(path):
    cfg = C.load(path)
    cases = dataset.load(cfg.dataset["path"], limit=cfg.dataset.get("limit"))
    counter = T.make_counter(cfg.tokenizer, cfg.model)

    run = Run(cfg, RUNS)
    broken, applied_count, untouched = [], {}, 0
    n_checked = n_unchecked = 0

    for c in cases:
        after, extra = compress(c.text, **cfg.params)
        steps = extra.pop("_steps")
        ok, why, checked = verify_steps(steps)
        extra["verified"] = why
        n_checked += checked
        n_unchecked += len(steps) - checked
        if not ok:
            broken.append((c.id, why))
        for n in extra["applied"]:
            applied_count[n] = applied_count.get(n, 0) + 1
        if not extra["applied"]:
            untouched += 1
        run.add(metrics.per_case(c.id, c.kind, c.text, after, c.must_include,
                                 counter, extra),
                before=c.text, after=after)

    m = metrics.aggregate(run.records, counter)
    m.update({"dataset_name": Path(cfg.dataset["path"]).name,
              "applied_count": applied_count, "untouched": untouched,
              "steps_verified": n_checked, "steps_unverified": n_unchecked,
              "broken": broken})
    return cfg, m, run.finish(m, [f"적용 횟수 {applied_count or '없음'}"])


results = []
for p in sorted(Path("configs").glob("*.yaml")):
    cfg, m, out = run_config(p)
    results.append((cfg.name, m, out))
    flag = " ← 검증 불가 포함" if m["steps_unverified"] else ""
    print(f'{cfg.name:22s} 절감 {m["saved"]:6.1%} · '
          f'검증 {m["steps_verified"]:2d}단계 · 손 안 댐 {m["untouched"]:2d}건{flag}')'''),

        md(COMPARE_MD.format(n=5) + '''
**여기서 읽어야 할 것 두 가지입니다.**

1. `structure` 와 `prose` 는 **코드가 한 글자도 안 다릅니다.** 입력만 다릅니다.
2. `structure-lossy-ws` 는 절감이 조금 늘지만 **검증 불가 단계**가 생깁니다.
   그만큼 "무손실" 이라는 말을 쓸 수 없게 됩니다.
'''),
        code('''
table(
    ["설정", "코퍼스", "절감", "최저 보존율", "검증", "검증 불가", "손 안 댐"],
    [[n, m["dataset_name"], pct(m["saved"]), pct(m.get("survival_worst")),
      f'{m["steps_verified"]}단계',
      f'{m["steps_unverified"]}단계' if m["steps_unverified"] else "없음",
      f'{m["untouched"]}건']
     for n, m, _ in results],
    align=["left", "left", "right", "right", "right", "right", "right"],
    title="조건 비교",
    note="검증 불가 단계가 하나라도 있으면 그 조건의 결과는 무손실이 아닙니다.",
)

for n, m, _ in results:
    if m["broken"]:
        print(f"✗ {n}: 정보 손실 {len(m['broken'])}건 — {m['broken'][:2]}")

by = {n: m for n, m, _ in results}
if "structure" in by and "prose" in by:
    print(f'같은 코드, 다른 입력: 구조화 {by["structure"]["saved"]:.1%} '
          f'vs 산문 {by["prose"]["saved"]:.1%}')
if "structure" in by and "structure-lossy-ws" in by:
    d = by["structure-lossy-ws"]["saved"] - by["structure"]["saved"]
    print(f'공백까지 접어서 더 얻은 것: {d:.1%}p — '
          f'그 대가로 무손실 보장을 잃습니다.')'''),

        md('''
## 6. 유형별 — 어디서 이득이 나나

무손실의 이득은 **중복의 양에 비례**합니다. 그래서 유형마다 크게 다릅니다.
'''),
        code('''
m = by.get("structure") or results[0][1]

table(
    ["유형", "건수", "절감", "왜"],
    [[k, v["n"], pct(v["saved"]), {
        "json-array": "레코드가 많을수록 키 반복이 커집니다",
        "json-nested": "들여쓰기가 통째로 사라집니다",
        "kv-space": "콜론을 맞추려고 채운 공백이 전부 장식입니다",
        "md-table": "정렬 패딩과 구분선이 사라집니다",
        "log-repeat": "접두사는 길지만 줄 수가 적으면 이득도 적습니다",
        "xml": "태그 이름 자체는 못 줄입니다",
     }.get(k, "")]
     for k, v in sorted(m["by_kind"].items(), key=lambda x: -x[1]["saved"])],
    align=["left", "right", "right", "left"],
    title="유형별 절감 (structure 조건)",
)

print("적용 횟수:", m["applied_count"])'''),

        md('''
## 정리

- **무손실은 표현의 중복을 먹습니다** — 내용이 아니라 포맷을 줄입니다
- **입력이 결과를 정합니다** — 같은 코드가 28% 도 되고 1% 도 됩니다
- **검증할 수 없으면 무손실이 아닙니다** — 되돌리기나 정규형 비교 중 하나는 있어야 합니다
- **공백 접기는 대개 손해입니다** — 조금 더 얻고 보장을 잃습니다

무손실은 여기까지가 천장입니다. 더 줄이려면 **무언가는 버려야** 합니다.

### 다음 랩

[`02-handle-ref`](../02-handle-ref/run.ipynb) — 버리는 대신 밖에 두고
필요할 때만 꺼냅니다.
'''),
    ])


# ══════════════════════════════════════════════════════════════════
# 02-handle-ref
# ══════════════════════════════════════════════════════════════════

def nb_02() -> dict:
    return notebook([
        md('''
# 02-handle-ref — 버리지 않고 밖에 두기

무손실([`01`](../01-lossless-structure/run.ipynb))은 표현의 중복까지가
천장입니다. 더 줄이려면 뭔가를 빼야 하는데, 빼는 방법이 둘입니다.

| | 정보는 | 되돌리기 |
|---|---|---|
| [`03-summarize-llm`](../03-summarize-llm/) | 요약하며 **없앱니다** | 불가 |
| **`02-handle-ref`** | 밖에 두고 **핸들만** 남깁니다 | 꺼내면 원문 그대로 |

핸들 방식은 아무것도 잃지 않습니다. 원문은 저장소에 그대로 있습니다.
대신 **꺼낼 것을 골라야** 하고, 잘못 고르면 답을 못 합니다.

> **이 랩의 결론을 미리 말하면** — 같은 비용(k=1)으로 보존율이 100% 도 되고
> 43.8% 도 됩니다. 차이는 압축 알고리즘이 아니라 **고르는 방법**입니다.
'''),
        md("## 1. kit 과 블록 모듈 불러오기"),
        code(BOOTSTRAP + '''
import blocks as B
from compress import compress'''),

        md('''
## 2. 블록으로 쪼개고 핸들 붙이기

블록 경계를 어디로 잡느냐가 라우팅 난이도를 정합니다. 문서에 이미 절 표시가
있으면 그걸 씁니다 — 사람이 의미 단위로 나눠 둔 것이라 기계가 다시 나누는
것보다 낫습니다.
'''),
        code('''
cases = dataset.load("../data/sample-long")
c = cases[0]

bs = B.make_blocks(c.text, "auto")
table(
    ["핸들", "제목", "길이", "질문과의 겹침"],
    [[f"[[{b.handle}]]", b.title or "(제목 없음)", f"{len(b.body)}자",
      f"{B.score(c.question, b):.3f}"] for b in bs],
    align=["left", "left", "right", "right"],
    title=f"{c.id} 를 블록으로 — 질문: {c.question}",
    note="겹침이 가장 큰 블록을 펼칩니다. 정답 절은 "
         f"'{c.meta['answer_section']}' 입니다.",
)'''),

        md('''
## 3. 컨텍스트에 실제로 들어가는 것

펼친 블록은 원문 그대로, 나머지는 **다이제스트 한 줄**로 들어갑니다.
다이제스트가 필요한 이유는, 흔적이 없으면 모델이 그런 내용이 있었는지조차
모르고 꺼낼 판단도 못 하기 때문입니다. 이 흔적의 길이가 곧 오버헤드입니다.
'''),
        code('''
counter = T.make_counter({}, "gpt-5.4")

for k in (0, 1):
    out, meta = compress(c.text, question=c.question, expand_k=k, digest_chars=24)
    print(f"── expand_k={k} · {counter(out):,} 토큰 "
          f"(원문 {counter(c.text):,}) · 펼친 절 {meta['expanded_titles']} ──")
    print(out[:420] + ("…" if len(out) > 420 else ""))
    print()'''),

        md('''
## 4. 라우팅이 있고 없고 — 이 랩의 핵심

`route` 를 바꿔 같은 `k` 로 비교합니다.

| | 무엇 |
|---|---|
| `bigram` | 질문과 글자 2-gram 이 많이 겹치는 블록 |
| `first` | 문서 **앞에서부터** — 가장 흔한 절단 방식 |

한국어는 띄어쓰기로 자르면 조사 때문에 잘 안 맞습니다(`수수료율은` vs
`수수료`). 그래서 글자 2-gram 겹침을 씁니다.
'''),
        code('''
def sweep(route, ks, cases, digest_chars=24):
    rows = []
    for k in ks:
        recs, hit = [], 0
        for cc in cases:
            after, extra = compress(cc.text, question=cc.question or "",
                                    expand_k=k, route=route,
                                    digest_chars=digest_chars)
            if cc.meta.get("answer_section") in extra["expanded_titles"]:
                hit += 1
            recs.append(metrics.per_case(cc.id, cc.kind, cc.text, after,
                                         cc.must_include, counter, extra))
        mm = metrics.aggregate(recs, counter)
        rows.append([str(k), f'{mm["tokens_after"]:,}', pct(mm["saved"]),
                     pct(mm["survival_mean"]), pct(mm["survival_worst"]),
                     pct(hit / len(cases))])
    return rows


for route, label in [("bigram", "라우팅 있음"), ("first", "라우팅 없음 (앞에서 자르기)")]:
    table(
        ["펼침", "토큰", "절감", "평균 보존율", "최저 보존율", "정답 절 적중"],
        sweep(route, [0, 1, 2, 3, "all"], cases),
        align=["right"] * 6,
        title=f"{label} — route={route}",
    )
print(f"원문 {sum(counter(x.text) for x in cases):,} 토큰")'''),

        md('''
`first` 는 4개를 펼쳐도(=절감을 17.6% 까지 포기해도) 최저 보존율이 **0%**
입니다. 정답이 뒤쪽 절에 있는 문서는 아무리 앞을 남겨도 못 찾기 때문입니다.

> **토큰을 더 쓴다고 정확도가 오르지 않습니다.** 어디를 남기느냐가 정합니다.
> 코퍼스를 만들 때 정답 절의 위치를 문서마다 다르게 둔 이유입니다 — 항상
> 앞에 있으면 앞에서 자르기만으로도 통과해서 라우터를 평가할 수 없습니다.
'''),

        md(ALL_CONFIGS_MD.format(n=5, lab="02-handle-ref") + '''
| 설정 | 무엇을 보려고 |
|---|---|
| `k1` | 기본 조건 — 질문에 맞는 절 1개 |
| `k0-digest-only` | 절감의 상한이자 보존율의 하한 |
| `k1-title-only` | 다이제스트를 제목만으로 줄이면 |
| `k1-no-router` | **대조군** — 라우팅 없이 앞에서 |
| `k1-short` | 짧은 산문에 쓰면 어떻게 되나 |
'''),
        code('''
def run_config(path):
    cfg = C.load(path)
    cs = dataset.load(cfg.dataset["path"], limit=cfg.dataset.get("limit"))
    cnt = T.make_counter(cfg.tokenizer, cfg.model)

    run = Run(cfg, RUNS)
    hit_known = hit_ok = 0
    for cc in cs:
        after, extra = compress(cc.text, question=cc.question or "", **cfg.params)
        want = cc.meta.get("answer_section")
        if want:
            hit_known += 1
            hit_ok += want in extra["expanded_titles"]
        run.add(metrics.per_case(cc.id, cc.kind, cc.text, after,
                                 cc.must_include, cnt, extra),
                before=cc.text, after=after)

    m = metrics.aggregate(run.records, cnt)
    m["dataset_name"] = Path(cfg.dataset["path"]).name
    m["expand_k"] = str(cfg.params.get("expand_k"))
    m["route"] = cfg.params.get("route", "bigram")
    m["digest_chars"] = cfg.params.get("digest_chars", 24)
    if hit_known:
        m["router_hit_rate"] = round(hit_ok / hit_known, 4)
    return cfg, m, run.finish(m, ["절감률은 **꺼내기 전** 기준입니다."])


results = []
for p in sorted(Path("configs").glob("*.yaml")):
    cfg, m, out = run_config(p)
    results.append((cfg.name, m, out))
    print(f'{cfg.name:18s} k={m["expand_k"]:<3s} route={m["route"]:<6s} '
          f'절감 {m["saved"]:6.1%} · 최저 보존율 {m["survival_worst"]:6.1%}')'''),

        md(COMPARE_MD.format(n=6)),
        code('''
table(
    ["설정", "코퍼스", "펼침", "라우팅", "다이제스트", "절감",
     "최저 보존율", "정답 절 적중"],
    [[n, m["dataset_name"], m["expand_k"], m["route"],
      f'{m["digest_chars"]}자' if m["digest_chars"] else "제목만",
      pct(m["saved"]), pct(m.get("survival_worst")),
      pct(m.get("router_hit_rate"))]
     for n, m, _ in results],
    align=["left", "left", "right", "left", "right", "right", "right", "right"],
    title="조건 비교",
    note="절감이 커도 최저 보존율이 0% 면 그 질문에는 답할 수 없습니다.",
)

by = {n: m for n, m, _ in results}
if "k1" in by and "k1-no-router" in by:
    a, b = by["k1"], by["k1-no-router"]
    print(f'같은 k=1, 비슷한 절감({a["saved"]:.1%} vs {b["saved"]:.1%}) 인데')
    print(f'최저 보존율은 {a["survival_worst"]:.1%} vs {b["survival_worst"]:.1%} 입니다.')
    print("차이는 압축 알고리즘이 아니라 무엇을 펼칠지 고르는 방법입니다.")
if "k1" in by and "k1-title-only" in by:
    d = by["k1-title-only"]["saved"] - by["k1"]["saved"]
    print(f'\\n미리보기 24자를 지우면 절감이 {d:.1%}p 뜁니다 — '
          f'절 제목이 이미 설명적이면 미리보기는 순수 낭비입니다.')
if "k1-short" in by:
    print(f'\\n짧은 산문(k1-short)은 절감 {by["k1-short"]["saved"]:.1%} — '
          f'핸들 표시와 색인 헤더가 원문만큼 큽니다.')'''),

        md('''
## 7. 절감률을 곧이곧대로 믿으면 안 되는 이유

**위 표의 절감률은 "꺼내기 전" 한 번의 컨텍스트만 잰 것입니다.**
실제로는 이렇게 흘러갑니다.

| 호출 | 보내는 것 |
|---|---|
| 1번째 | 다이제스트 (모델이 `[[b2]]` 를 달라고 함) |
| 2번째 | 다이제스트 + 꺼낸 블록 (이제 답함) |

**입력 토큰은 두 번 다 과금됩니다.** 다이제스트를 두 번 보내기 때문에,
한 번 묻고 끝이면 절감이 절반 이하로 줄어듭니다. 아래에서 실제로 계산합니다.
'''),
        code('''
n_doc = len(cases)
full = sum(counter(x.text) for x in cases) / n_doc          # 문서당 원문
digest = by["k0-digest-only"]["tokens_after"] / n_doc        # 문서당 다이제스트
expanded = by["k1"]["tokens_after"] / n_doc                  # 다이제스트 + 블록 1개

table(
    ["방식", "호출", "입력 토큰 합 (문서 1건 기준)", "절감"],
    [["원문을 통째로", "1회", f"{full:,.0f}", "기준"],
     ["핸들 — 위 표가 보여준 것", "1회분만", f"{expanded:,.0f}",
      pct(1 - expanded / full)],
     ["핸들 — 실제 (왕복 포함)", "2회", f"{digest + expanded:,.0f}",
      pct(1 - (digest + expanded) / full)]],
    align=["left", "right", "right", "right"],
    title="왕복을 세면 이야기가 달라집니다",
    note="다이제스트를 두 번 보내므로 절감이 크게 깎입니다. 지연도 2배입니다.",
)'''),
        md('''
그럼 언제 이깁니까. 세 가지 경우입니다.

1. **같은 문서에 질문을 여러 번** — 색인을 만드는 비용이 나눠집니다
2. **문서가 훨씬 클 때** — 다이제스트 비중이 작아집니다
3. **프롬프트 캐시가 먹을 때** — 매번 같은 다이제스트라 캐시 적중률이 높습니다
   (Azure 기준 최소 1,024토큰, 128토큰 단위)

1번을 계산해 봅니다. 색인은 한 번 만들고, 질문마다 블록만 새로 꺼냅니다.
'''),
        code('''
block = expanded - digest              # 블록 하나의 순수 비용

table(
    ["질문 수", "원문 매번", "핸들 (왕복 포함)", "절감"],
    [[q, f"{full * q:,.0f}",
      f"{digest * (q + 1) + block * q:,.0f}",
      pct(1 - (digest * (q + 1) + block * q) / (full * q))]
     for q in (1, 2, 3, 5, 10)],
    align=["right", "right", "right", "right"],
    title="같은 문서에 여러 번 물을 때",
    note="색인은 한 번, 블록은 매번. 질문이 늘수록 이득이 붙습니다.",
)

print(f"문서당 원문 {full:,.0f} · 다이제스트 {digest:,.0f} · 블록 {block:,.0f} 토큰")
print("이 코퍼스는 문서가 800자대로 짧은 편입니다.")
print("실제 장문(수천~수만 토큰)에서는 다이제스트 비중이 훨씬 작아 이득이 큽니다.")'''),

        md('''
## 정리

- **정보를 버리는 게 아니라 밖에 둡니다** — 꺼내면 원문 그대로입니다
- **실패는 전부 라우팅 실패입니다** — 저장소는 아무것도 잃지 않습니다
- **토큰을 더 쓴다고 정확도가 오르지 않습니다** — 어디를 남기느냐가 정합니다
- **짧은 글에는 쓰면 안 됩니다** — 핸들 표시가 원문보다 커집니다
- **한 번 묻고 끝이면 손해입니다** — 같은 문서에 여러 번 물을 때 이깁니다

### 다음 랩

[`03-summarize-llm`](../03-summarize-llm/) — 밖에 두는 대신 실제로 버립니다.
유일하게 API 가 필요한 랩입니다.
'''),
    ])


BUILDERS = {"00": ("00-baseline", nb_00),
            "01": ("01-lossless-structure", nb_01),
            "02": ("02-handle-ref", nb_02)}


def main(argv: list) -> int:
    want = argv[1:] or list(BUILDERS)
    for w in want:
        if w not in BUILDERS:
            print(f"모르는 랩: {w} (가능: {list(BUILDERS)})", file=sys.stderr)
            return 2
        lab, fn = BUILDERS[w]
        p = HERE / lab / "run.ipynb"
        nb = fn()
        p.write_text(json.dumps(nb, ensure_ascii=False, indent=1), encoding="utf-8")
        n_code = sum(1 for c in nb["cells"] if c["cell_type"] == "code")
        print(f"  {lab}/run.ipynb — {len(nb['cells'])}셀 (코드 {n_code})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
