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

# 노트북을 켜 둔 채로 저장소를 갱신하면 커널이 **예전 코드를 물고 있습니다.**
# 그러면 새로 생긴 함수가 없다는 에러(AttributeError)가 나는데, 원인이 코드가
# 아니라 커널이라 찾기가 어렵습니다. 그래서 이 셀을 돌릴 때마다 새로 읽습니다.
_stale = [m for m in list(sys.modules)
          if m == "kit" or m.startswith("kit.")
          or m in ("transforms", "blocks", "summarize", "compress")]
for _m in _stale:
    del sys.modules[_m]

from kit import VERSION, config as C, dataset, env, metrics, tokens as T
from kit.display import table, pct
from kit.runner import Run

# .env 는 labs/.env → 저장소 루트 .env → scripts/explore/.env 순으로 찾습니다.
env.load(verbose=True)

RUNS = LABS.parent / "runs"
print("kit", VERSION, "· 랩", LAB.name)
if _stale:
    print(f"모듈 {len(_stale)}개를 새로 읽었습니다 — 커널에 남아 있던 예전 코드를 지웠습니다")
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


# ══════════════════════════════════════════════════════════════════
# 과금 검증 — 노트북 4개가 공유합니다
#
# tiktoken 은 추정입니다. 실제로 돈이 나가는 기준은 API 응답의
# usage.input_tokens 입니다. "줄었다" 를 추정으로만 말하지 않으려고
# 랩마다 몇 건을 실제로 불러서 두 숫자를 나란히 놓습니다.
# ══════════════════════════════════════════════════════════════════

BILLED_MD = '''
## {n}. 진짜로 줄었나 — API 응답으로 확인하기

여기까지의 절감률은 전부 **tiktoken 추정치**입니다. 실제로 청구되는 값은
API 응답의 `usage.input_tokens` 이고, 둘이 항상 같지는 않습니다.

| 왜 어긋나나 | 얼마나 |
|---|---|
| 메시지 포맷 오버헤드 (역할 구분자 등) | 텍스트당 상수 (실측 +6) |
| 배포 모델의 토크나이저가 tiktoken 과 다를 수 있음 | 모델마다 |
| 압축 결과의 특수 문자를 모델이 어떻게 쪼개는지 | **해봐야 압니다** |

마지막 줄이 중요합니다. {why}

그래서 몇 건만 뽑아 **압축 전과 후를 각각 실제로 보내보고**, 응답이 알려주는
토큰 수로 절감률을 다시 계산합니다. 호출은 케이스당 2회이고 캐시됩니다.
'''

BILLED_CODE = '''
from kit import verify

DEPLOY = env.get("AZURE_OPENAI_DEPLOYMENT")
BILLED = None                     # 아래 리포트에서 다시 씁니다

try:
{setup}
    r = verify.billed(pairs, deployment=DEPLOY, model=DEPLOY, limit={limit})
    BILLED = r["totals"]
    t = BILLED

    table(
        ["케이스", "tiktoken 전→후", "API 실측 전→후", "추정 절감", "실측 절감"],
        [[x["id"],
          f'{{x["local_before"]:,}} → {{x["local_after"]:,}}',
          f'{{x["api_before"]:,}} → {{x["api_after"]:,}}',
          pct(x["local_saved"]), pct(x["api_saved"])]
         for x in r["rows"]],
        foot=["합계",
              f'{{t["local_before"]:,}} → {{t["local_after"]:,}}',
              f'{{t["api_before"]:,}} → {{t["api_after"]:,}}',
              pct(t["local_saved"]), pct(t["api_saved"])],
        align=["left", "right", "right", "right", "right"],
        title=f'과금 기준으로 다시 재기 ({{t["n"]}}건)',
        note="'API 실측' 은 응답의 usage.input_tokens 를 그대로 읽은 값입니다.",
    )

    print(verify.verdict(t))
    print(f'텍스트당 오버헤드 {{t["overhead_per_text"]:+.1f}} 토큰 — '
          f'역할 구분자 같은 프레이밍이라 길이와 무관하게 붙습니다.')
    print(r["counter"].describe())
except Exception as e:
    print(f"과금 검증을 건너뜁니다 — {{type(e).__name__}}: {{str(e)[:160]}}")
    print("\\\\n자격증명이 있으면 아래로 준비하실 수 있습니다.")
    print("  cd labs && cp .env.example .env")
    print("없어도 위까지의 결과는 전부 유효합니다. 다만 추정치입니다.")
'''


def billed_cells(n: int, why: str, setup: str, limit: int = 3) -> list:
    """setup 은 `pairs` 를 만드는 코드 조각입니다 (들여쓰기 4칸으로 들어갑니다).

    limit 은 실제로 불러볼 케이스 수입니다. 호출이 케이스당 2회(전·후)라
    기본을 3건으로 두었지만, 한국어·영어를 짝으로 봐야 하는 랩에서는
    짝수로 올려야 한쪽 언어만 뽑히는 일이 없습니다.
    """
    body = "\n".join("    " + ln if ln.strip() else ln
                     for ln in setup.strip("\n").splitlines())
    return [md(BILLED_MD.format(n=n, why=why)),
            code(BILLED_CODE.format(setup=body, limit=limit))]


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

**세 가지 중에 고르실 수 있고, 기본값은 `both` 입니다.**

| mode | 기준값 | 호출 | 언제 쓰나요 |
|---|---|---|---|
| **`both`** (기본) | API 실측 | 텍스트당 1회 | 과금 기준으로 재면서 추정 오차도 같이 봅니다 |
| `api` | API 실측 | 텍스트당 1회 | 실측만 필요할 때 |
| `local` | tiktoken | 없음 | 네트워크·자격증명 없이 돌릴 때 |

`both` 가 기본인 이유는, **실제로 돈이 나가는 기준은 API 응답의
`usage.input_tokens`** 이기 때문입니다. 그렇다고 tiktoken 을 버리면 추정이
얼마나 어긋나는지 알 수 없어서, 둘을 같이 재고 차이를 남깁니다.

```yaml
tokenizer:
  mode: both           # both | api | local
  deployment:          # 비우면 .env 의 AZURE_OPENAI_DEPLOYMENT
  cache: true          # 같은 텍스트는 한 번만 호출
```

명령줄에서 덮어쓰실 수도 있습니다.

```bash
python compress.py configs/noop.yaml --tokenizer local
```

**자격증명이 없으면** `both` 는 로컬 계산으로 내려가되 왜 그랬는지 알려줍니다.
`api` 는 같은 상황에서 예외를 냅니다 — 실측이 꼭 필요하다고 선언한 것이라
조용히 다른 값을 드리면 안 되기 때문입니다.

**`api` 를 쓰실 때 캐시를 끄지 말아주세요.** 케이스 N건이면 압축 전후로
2N 회를 부르고, 스윕을 10단계 돌리면 그만큼 곱해집니다. 결과는
`kit/.cache/` 에 남아 다음 실행부터 재사용됩니다.

> **주의** — `api` 값에는 메시지 포맷 오버헤드가 포함됩니다(실측 +6).
> 압축 전후를 같은 방식으로 재므로 **비율 비교는 안전하지만**,
> `local` 값과 나란히 놓으면 안 됩니다. 그래서 `token_backend` 를 기록합니다.
'''),
        code('''
# 여기서 방식을 바꿔 보실 수 있습니다. None 이면 config 값을 씁니다.
MODE = None          # None | "both" | "api" | "local"

spec = dict(cfg.tokenizer)
if MODE:
    spec["mode"] = MODE

counter = T.make_counter(spec, cfg.model)
print("측정 방식:", counter.backend)
print("설명    :", counter.describe())

sample = "환불 수수료는 결제금액의 10%입니다."
print(f"\\n예시 {len(sample)}자 → {counter(sample):,} 토큰")'''),

        md('''
지금 설정(`noop.yaml`)은 `local` 이라 위 셀에서는 **API 를 부르지 않았습니다.**
말로만 읽으면 두 방식의 차이가 잘 안 와닿으니, 실제로 한 번 불러서
같은 텍스트를 두 방식으로 재보겠습니다.

**호출은 텍스트당 1회씩, 아래 3건이 전부입니다.** `.env` 가 없으면 건너뜁니다.
'''),
        code('''
probe = ["환불 수수료는 결제금액의 10%입니다.",
         "주문번호 A-1003 은 환불 완료 상태입니다.",
         ("제7조 환불 시 결제금액의 10%를 수수료로 공제한다. "
          "제9조 단, 결제 후 7일 이내 취소는 수수료를 면제한다. "
          "제10조 분쟁은 서울중앙지방법원을 관할로 한다.")]

local_c = T.make_counter({"mode": "local"}, cfg.model)

try:
    api_c = T.make_counter(
        {"mode": "api", "deployment": env.get("AZURE_OPENAI_DEPLOYMENT"),
         "cache": True}, cfg.model)
    rows = []
    for t in probe:
        a, b = local_c(t), api_c(t)
        rows.append([t[:30] + ("…" if len(t) > 30 else ""),
                     f"{len(t)}자", f"{a:,}", f"{b:,}", f"{b - a:+d}"])
    api_c.save()

    table(
        ["텍스트", "길이", "local", "api", "차이"],
        rows,
        align=["left", "right", "right", "right", "right"],
        title="같은 텍스트를 두 방식으로",
        note="차이가 어느 텍스트에서나 같은 값이면 그건 내용이 아니라 "
             "메시지 포맷 오버헤드입니다.",
    )
    print(api_c.describe())
    print("\\n차이가 일정한 이유 — 요청을 보낼 때 역할 구분자 같은 것이 붙습니다.")
    print("텍스트가 길든 짧든 똑같이 붙으므로 상수만큼 차이가 납니다.")
except Exception as e:
    print(f"api 측정을 건너뜁니다 — {type(e).__name__}: {str(e)[:160]}")
    print("\\n자격증명이 있으면 아래로 준비하실 수 있습니다.")
    print("  cd labs && cp .env.example .env")
    print("없어도 이 노트북의 나머지는 local 로 전부 돌아갑니다.")'''),

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

> **"호출 0회" 가 나와도 놀라지 마세요.** 같은 텍스트를 이미 잰 적이 있으면
> 디스크 캐시에서 꺼내 씁니다. 처음 한 번은 실제로 12회를 부르고 20초 남짓
> 걸립니다. 강제로 다시 부르시려면 설정에 `refresh: true` 를 넣거나
> 명령줄에서 `--refresh-tokens` 를 쓰시면 됩니다.
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
    out = run.finish(m, ["압축 없음. 다른 랩의 절감률은 이 결과를 기준으로 읽습니다.",
                         counter.describe()])
    return cfg, m, out, counter


results, skipped = [], []
for p in sorted(Path("configs").glob("*.yaml")):
    try:
        cfg, m, out, cnt = run_config(p)
        results.append((cfg.name, m, out))
        print(f'{p.name:20s} 절감 {m["saved"]:6.1%} · {cnt.describe()}')
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

        *billed_cells(
            10,
            "이 랩은 압축을 안 하므로 **양쪽 다 0% 가 나와야 정상**입니다. "
            "여기서 0% 가 아니면 측정 경로 어딘가가 원문을 바꾸고 있다는 뜻입니다.",
            "pairs = [(c.id, c.text, compress(c.text, **cfg.params)[0])\n"
            "         for c in cases]"),

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

한 줄로 보여드리면 이렇습니다.

```
압축 전   [{"id":"A-1","amount":1200},{"id":"A-2","amount":3400}]
압축 후   #TSV │ id  │ amount
          "A-1" │ 1200
          "A-2" │ 3400
```

`id` 와 `amount` 라는 글자가 레코드마다 반복되던 것을 헤더 한 줄로 올렸습니다.
값은 하나도 안 바뀌었으니 **되돌리면 원본과 똑같습니다.**

가능한 이유는 텍스트에 **내용이 아닌데도 토큰을 먹는 부분**이 있기 때문입니다.

| 무엇이 중복인가 | 어디에 |
|---|---|
| 레코드마다 반복되는 **키 이름** | JSON 배열, API 응답 |
| 줄마다 반복되는 **타임스탬프·서비스명** | 로그 |
| 사람이 보라고 넣은 **들여쓰기** | JSON, XML |
| 세로줄을 맞추려고 채운 **정렬 공백** | 마크다운 표, 설정 파일 |

산문에는 이런 중복이 없습니다. 그래서 같은 코드가 구조화 텍스트에서는
28% 줄이고 산문에서는 1% 줄입니다. **입력이 결과를 정합니다.**

### 이 노트북에서 하실 것

| 절 | 무엇을 |
|---|---|
| 2 | 변환 7종이 실제로 무엇을 바꾸는지 전후로 봅니다 |
| 3 | "아무것도 안 잃었다" 를 어떻게 확인하는지 봅니다 |
| 4 | 그 확인이 **진짜로 잡는지** 일부러 고장 내서 봅니다 |
| 5~7 | 설정 3개를 전부 돌려 비교합니다 |
'''),
        md("## 1. kit 과 변환 모듈 불러오기"),
        code(BOOTSTRAP + '''
import json

import transforms as X
from compress import compress, verify_steps

counter = T.make_counter({}, "gpt-5.4")


def eye(text, width=44):
    """눈에 안 보이는 글자를 보이게 바꿉니다.

    줄바꿈은 ⏎, 표 구분자(\\\\x1f)는 ▏, 연달아 나오는 공백은 · 로 표시합니다.
    안 그러면 표 안에서 줄과 공백이 뭉개져서, 정작 무엇이 바뀌었는지
    알아볼 수가 없습니다. 특히 공백을 지우는 변환은 전후가 똑같아 보입니다.
    """
    import re
    t = text.replace("\\x1f", " ▏ ").replace("\\n", " ⏎ ")
    t = re.sub(r" {2,}", lambda m: "·" * min(len(m.group()), 10), t)
    return t if len(t) <= width else t[:width - 1] + "…"


print("kit 준비 완료 · 변환", len(X.REGISTRY), "종")'''),

        md('''
## 2. 변환 7종이 실제로 무엇을 하는지 한 번에 보기

설명보다 **결과를 보시는 편이 빠릅니다.** 각 변환에 딱 맞는 짧은 입력을
하나씩 주고, 전후를 나란히 놓았습니다.

`⏎` 는 줄바꿈, `▏` 는 표 구분자입니다. 원래 눈에 안 보이는 글자라서
표시해 두었습니다.
'''),
        code('''
DEMO = {
    "json_to_table":    '[{"id":"A-1","amt":1200},{"id":"A-2","amt":3400}]',
    "json_compact":     '{\\n  "host": "db-01",\\n  "port": 5432\\n}',
    "log_dedup":        ("2026-03-03T14:20:11 INFO  handler=refund ok\\n"
                         "2026-03-03T14:20:11 INFO  handler=cancel ok\\n"
                         "2026-03-03T14:20:11 ERROR handler=refund fail"),
    "xml_compact":      '<cfg>\\n    <db host="a" port="1"/>\\n</cfg>',
    "md_table_compact": ("| 요금제  | 가격  |\\n|--------|------|\\n"
                         "| Free   | 0    |\\n| Pro    | 49000|"),
    "kv_compact":       "host    :   db-01\\nport    :   5432\\nretry   :   3",
    "ws_collapse":      "a      b       c       d",
}

rows = []
for name, src in DEMO.items():
    out, meta = compress(src, pipeline=[name])
    ok, why, checked = verify_steps(meta["_steps"])
    rows.append([
        name,
        eye(src),
        eye(out),
        f"{len(src)} → {len(out)}",
        f"-{1 - len(out) / len(src):.0%}",
        "검증됨" if checked else "검증 불가",
    ])

table(
    ["변환", "압축 전", "압축 후", "글자", "절감", "확인"],
    rows,
    align=["left", "left", "left", "right", "right", "left"],
    title="변환 7종 · 같은 입력을 주면 이렇게 바뀝니다",
    note="맨 아래 ws_collapse 만 '검증 불가' 입니다. 이유는 다음 절에서 설명드립니다.",
)'''),

        md('''
## 3. "아무것도 안 잃었다" 를 어떻게 확인하나요

줄었다는 건 글자 수만 세면 바로 보입니다. 어려운 건 **아무것도 안 잃었다**
쪽입니다. 위 표의 `json_to_table` 하나를 붙잡고 실제로 확인해 보겠습니다.
'''),
        code('''
before = json.dumps([{"id": "A-1", "amount": 1200, "status": "paid"},
                     {"id": "A-2", "amount": 3400, "status": "refunded"}],
                    ensure_ascii=False, indent=2)
after, meta = compress(before, pipeline=["json_to_table"])

print("━━━ 압축 전 ━━━")
print(before)
print(f"\\n{len(before)}자 · {counter(before)} 토큰\\n")

print("━━━ 압축 후 ━━━")
print(after.replace("\\x1f", " ▏ "))
print(f"\\n{len(after)}자 · {counter(after)} 토큰")
print(f"\\n키 이름 id·amount·status 가 레코드마다 반복되던 것이 헤더 한 줄로 갔습니다.")'''),

        md('''
줄어든 건 확인했습니다. 그럼 **잃은 건 없을까요?**

압축 결과를 다시 펴서 원본과 맞춰봅니다. 두 개가 같으면 잃은 게 없다는 뜻입니다.
'''),
        code('''
restored = X.json_to_table_restore(after)      # 압축본을 다시 폅니다
original = json.loads(before)                  # 원본을 파싱합니다

print("원본을 파싱  :", original)
print("압축본을 되폄:", restored)
print()
print("두 값이 같은가:", restored == original, "← 같으면 잃은 것이 없습니다")

ok, why, checked = verify_steps(meta["_steps"])
print(f"\\n랩이 매 케이스마다 하는 검사: {ok} · {why}")'''),

        md('''
### 확인하는 방법이 두 가지인 이유

방금 본 것은 **다시 펴서 맞춰보기**였습니다. 그런데 이 방법이 안 통하는
변환도 있습니다.

```
json_compact:   {                      →   {"host":"db-01","port":5432}
                  "host": "db-01",
                  "port": 5432
                }

되돌려 보면?    {"host": "db-01", "port": 5432}
                ↑ 들여쓰기가 몇 칸이었는지 복원할 수 없습니다
```

**글자 단위로는 원본과 다릅니다.** 그렇다고 정보를 잃은 걸까요? 아닙니다.
JSON 에서 들여쓰기는 내용이 아니기 때문입니다. 그래서 이럴 때는 **양쪽을
파싱해서 객체끼리** 맞춰봅니다.

| 확인 방법 | 무엇과 무엇을 비교하나요 | 쓰는 변환 |
|---|---|---|
| **되돌리기** | 되돌린 글자 ↔ 원본 글자 | `log_dedup` |
| **정규형** | 파싱한 값 ↔ 파싱한 값 | `json_*`, `xml_*`, `md_table_*`, `kv_*` |
| (없음) | 비교할 방법이 없습니다 | `ws_collapse` |

`ws_collapse`(공백 접기)만 두 방법 다 안 됩니다. `a      b` 를 `a b` 로
바꾸면 원래 공백이 몇 칸이었는지도, 무엇과 비교해야 할지도 알 수 없습니다.
그래서 이 랩은 **`ws_collapse` 를 무손실이 아니라 손실로 분류**하고,
쓴 횟수를 결과에 남깁니다.
'''),
        code('''
rows = []
for name in ["log_dedup", "json_compact", "ws_collapse"]:
    t = X.REGISTRY[name]
    how = "되돌리기" if t.restore else ("정규형 비교" if t.canon else "없음")
    src = DEMO[name]
    out, meta = compress(src, pipeline=[name])
    ok, why, checked = verify_steps(meta["_steps"])
    rows.append([name, how, "예" if checked else "아니요", why])

table(
    ["변환", "확인 방법", "검증했나요", "결과"],
    rows,
    align=["left", "left", "center", "left"],
    title="세 가지 경우를 나란히",
    note="검증 못 한 변환을 쓰면 그 실행 결과는 '무손실' 이라고 부를 수 없습니다.",
)'''),

        md('''
## 4. 검사가 진짜 잡는지 확인하기

앞 절에서 "검증했습니다" 라는 결과를 봤습니다. 그런데 그 검사가 정말로
일하고 있는 걸까요, 아니면 그냥 항상 통과만 하는 걸까요?

**일부러 고장 낸 입력을 넣어봐야 알 수 있습니다.** 값을 몰래 지우는 변환을
심어서 검사가 걸러내는지 봅니다.
'''),
        code('''
def sneaky(text):
    """status 필드를 몰래 버리면서 무손실인 척하는 변환입니다."""
    o = json.loads(text)
    for r in o:
        r.pop("status", None)
    return True, json.dumps(o, ensure_ascii=False, separators=(",", ":")), {}


X.REGISTRY["sneaky"] = X.Transform("sneaky", sneaky, canon=X.json_canon)

rows = []
for name, label in [("json_to_table", "정상 변환"), ("sneaky", "몰래 삭제")]:
    out, meta = compress(before, pipeline=[name])
    ok, why, _ = verify_steps(meta["_steps"])
    rows.append([label, eye(out, 40), "통과" if ok else "걸림", why])

table(
    ["무엇을 넣었나", "결과물", "검사", "판정"],
    rows,
    align=["left", "left", "center", "left"],
    title="정상 변환 vs 값을 몰래 버리는 변환",
    note="아래쪽이 '걸림' 으로 나와야 검사가 일하고 있는 것입니다.",
)

out, meta = compress(before, pipeline=["sneaky"])
print("몰래 삭제된 결과 :", out)
print("status 필드가 없어졌는데도 JSON 으로는 멀쩡해 보입니다.")
print("정규형 비교가 아니었다면 그냥 통과했을 것입니다.")

del X.REGISTRY["sneaky"]'''),

        md(ALL_CONFIGS_MD.format(n=5, lab="01-lossless-structure") + '''
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
    broken, applied_count, verified_count, untouched = [], {}, {}, 0
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

        # 어떤 변환이 몇 번 쓰였고 그중 몇 번이 검증됐는지 따로 셉니다.
        # 합계만 보면 "12단계 검증" 이 무엇을 검증한 건지 알 수 없습니다.
        for name, _src, _dst in steps:
            applied_count[name] = applied_count.get(name, 0) + 1
            if X.REGISTRY[name].checkable:
                verified_count[name] = verified_count.get(name, 0) + 1

        if not extra["applied"]:
            untouched += 1
        run.add(metrics.per_case(c.id, c.kind, c.text, after, c.must_include,
                                 counter, extra),
                before=c.text, after=after)

    m = metrics.aggregate(run.records, counter)
    m.update({"dataset_name": Path(cfg.dataset["path"]).name,
              "applied_count": applied_count, "verified_count": verified_count,
              "untouched": untouched,
              "steps_verified": n_checked, "steps_unverified": n_unchecked,
              "broken": broken})
    counter.save()
    return cfg, m, run.finish(m, [f"적용 횟수 {applied_count or '없음'}",
                                  counter.describe()])


results = []
for p in sorted(Path("configs").glob("*.yaml")):
    cfg, m, out = run_config(p)
    results.append((cfg.name, m, out))
    flag = " ← 검증 불가 포함" if m["steps_unverified"] else ""
    print(f'{cfg.name:22s} 절감 {m["saved"]:6.1%} · '
          f'변환 {sum(m["applied_count"].values()):2d}번 적용 · '
          f'그중 {m["steps_verified"]:2d}번 검증{flag}')'''),

        md('''
### 무엇을 검증한 것인가

위 줄의 "12번 검증" 이 뭉뚱그려져 있어서, **어떤 변환을 어떤 방법으로**
확인했는지 아래에 풀어 놓았습니다.
'''),
        code('''
by = {n: m for n, m, _ in results}
base = by.get("structure", results[0][1])

rows = []
for name in X.DEFAULT_PIPELINE + ["ws_collapse"]:
    applied = base["applied_count"].get(name, 0)
    if applied == 0:
        continue
    t = X.REGISTRY[name]
    how = ("되돌려서 원본과 글자 비교" if t.restore else
           "파싱해서 값끼리 비교" if t.canon else "확인할 방법 없음")
    ok = base["verified_count"].get(name, 0)
    rows.append([name, how, f"{applied}회",
                 f"{ok}회" if ok == applied else f"{ok}회 ← 못 함"])

table(
    ["변환", "어떻게 확인했나", "적용", "검증"],
    rows,
    foot=["합계", "",
          f'{sum(base["applied_count"].values())}회',
          f'{base["steps_verified"]}회'],
    align=["left", "left", "right", "right"],
    title="structure 조건에서 검증한 내역",
    note="'적용' 과 '검증' 이 같아야 그 조건 전체를 무손실이라 부를 수 있습니다.",
)

lossy = by.get("structure-lossy-ws")
if lossy:
    missed = {k: v - lossy["verified_count"].get(k, 0)
              for k, v in lossy["applied_count"].items()
              if lossy["verified_count"].get(k, 0) < v}
    print(f'structure-lossy-ws 에서 검증 못 한 변환: {missed}')
    print("공백을 접으면 원래 몇 칸이었는지 정보가 사라져서, 되돌릴 수도")
    print("파싱해서 비교할 수도 없습니다. 그래서 이 조건은 무손실이 아닙니다.")'''),

        md(COMPARE_MD.format(n=6) + '''
**여기서 읽어야 할 것 두 가지입니다.**

1. `structure` 와 `prose` 는 **코드가 한 글자도 안 다릅니다.** 입력만 다릅니다.
2. `structure-lossy-ws` 는 절감이 조금 늘지만 **검증 불가 단계**가 생깁니다.
   그만큼 "무손실" 이라는 말을 쓸 수 없게 됩니다.
'''),
        code('''
table(
    ["설정", "코퍼스", "절감", "최저 보존율", "변환 적용", "검증됨", "검증 못 함", "압축 못 함"],
    [[n, m["dataset_name"], pct(m["saved"]), pct(m.get("survival_worst")),
      f'{sum(m["applied_count"].values())}번',
      f'{m["steps_verified"]}번',
      f'{m["steps_unverified"]}번' if m["steps_unverified"] else "없음",
      f'{m["untouched"]}건']
     for n, m, _ in results],
    align=["left", "left", "right", "right", "right", "right", "right", "right"],
    title="조건 비교",
    note="'압축 못 함' 은 적용할 변환이 하나도 없어서 원문 그대로 나간 케이스입니다. "
         "산문이 대부분 여기 해당합니다. "
         "'검증 불가' 단계가 하나라도 있으면 그 조건은 무손실이 아닙니다.",
)

for n, m, _ in results:
    if m["broken"]:
        print(f"✗ {n}: 정보 손실 {len(m['broken'])}건 — {m['broken'][:2]}")

if "structure" in by and "prose" in by:
    print(f'같은 코드, 다른 입력: 구조화 {by["structure"]["saved"]:.1%} '
          f'vs 산문 {by["prose"]["saved"]:.1%}')
if "structure" in by and "structure-lossy-ws" in by:
    d = by["structure-lossy-ws"]["saved"] - by["structure"]["saved"]
    print(f'공백까지 접어서 더 얻은 것: {d:.1%}p — '
          f'그 대가로 무손실 보장을 잃습니다.')'''),

        md('''
## 7. 유형별 — 어디서 이득이 나나

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

        *billed_cells(
            8,
            "이 랩은 표 구분자로 **제어문자**를 씁니다. 그런 글자를 모델 "
            "토크나이저가 어떻게 쪼개는지는 tiktoken 추정으로는 알 수 없습니다.",
            "scfg = C.load('configs/structure.yaml')\n"
            "pairs = [(c.id, c.text, compress(c.text, **scfg.params)[0])\n"
            "         for c in dataset.load(scfg.dataset['path'])]"),

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

        *billed_cells(
            9,
            "이 랩의 압축 결과에는 `[[b2]]` 같은 **핸들 표시**가 섞입니다. "
            "대괄호가 몇 토큰으로 쪼개지는지는 실제로 불러봐야 압니다.",
            "kcfg = C.load('configs/k1.yaml')\n"
            "pairs = [(c.id, c.text,\n"
            "          compress(c.text, question=c.question or '', **kcfg.params)[0])\n"
            "         for c in cases]"),

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


# ══════════════════════════════════════════════════════════════════
# 03-summarize-llm
# ══════════════════════════════════════════════════════════════════

def nb_03() -> dict:
    return notebook([
        md("""
# 03-summarize-llm — 모델에게 요약시키기

앞의 두 랩과 결정적으로 다릅니다.

| | 정보는 | 되돌리기 | 의존성 |
|---|---|---|---|
| [`01`](../01-lossless-structure/run.ipynb) | 아무것도 안 버립니다 | 가능 | 없음 |
| [`02`](../02-handle-ref/run.ipynb) | 밖에 두고 핸들만 | 꺼내면 원문 | 없음 |
| **`03`** | **버립니다** | **불가** | **API** |

버리는 만큼 많이 줄어듭니다. 문제는 **무엇을 버렸는지 모른다**는 것입니다.

> **이 랩의 결론을 미리 말하면** — 같은 모델·같은 문서·같은 목표 길이인데
> 프롬프트만 바꿨더니 보존율이 33.3% → 88.9% 가 됐습니다.
> 그러면서 **절감도 더 커졌습니다.**

## ⚠️ 이 노트북은 유료입니다

케이스 N건 = 요약 호출 N회입니다. 같은 프롬프트는 디스크에 캐시되므로
두 번째 실행부터 0회입니다. 아래 셀에서 예상 호출 수를 먼저 확인합니다.
"""),
        md("## 1. kit 과 요약기 불러오기"),
        code(BOOTSTRAP + '''
from summarize import STYLES, Summarizer
from compress import compress

DEPLOY = env.get("AZURE_OPENAI_DEPLOYMENT")
print("배포명    :", DEPLOY or "(없음 — .env 를 확인하세요)")
print("엔드포인트:", env.mask_endpoint(env.get("AZURE_OPENAI_ENDPOINT")))
print("스타일    :", list(STYLES))'''),

        md("""
## 2. 프롬프트 세 가지

압축률을 정하는 건 알고리즘이 아니라 **무엇을 지키라고 말했는지**입니다.

| 스타일 | 무엇을 알려주나 |
|---|---|
| `plain` | 그냥 요약하라고만 합니다 |
| `question_aware` | 질문을 알려주고 그에 필요한 것을 남기라고 합니다 |
| `preserve` | 숫자·식별자·부정어를 **글자 그대로** 남기라고 못 박습니다 |

`preserve` 가 필요한 이유는, 요약 모델이 "결제금액의 12%" 를 "일정 비율" 로
바꾸는 것을 요약이라고 생각하기 때문입니다.
"""),
        code('''
cases = dataset.load("../data/sample")
c = cases[1]          # doc-002 — 금액이 답인 케이스

print(f"[{c.id}] {c.kind} · 질문: {c.question}")
print(f"must_include: {c.must_include}\\n")

for style in STYLES:
    s = Summarizer(DEPLOY, style=style, target_ratio=0.5)
    p = s.prompt_for(c.text, c.question)
    head = p.split("문서:")[0].strip()
    print(f"── {style} ──")
    print(head[:300])
    print()'''),

        md("""
## 3. 한 케이스로 눈으로 보기

캐시가 있으면 호출이 안 나갑니다. 아래는 스타일마다 1회씩, 최대 3회입니다.
"""),
        code('''
counter = T.make_counter({}, "gpt-5.4")
print(f"원문 {len(c.text)}자 · {counter(c.text)} 토큰")
print(c.text, "\\n")

for style in STYLES:
    s = Summarizer(DEPLOY, style=style, target_ratio=0.5)
    out, meta = s(c.text, c.question)
    s.save()
    kept = [m for m in c.must_include if m.replace(",", "") in out.replace(",", "")]
    print(f"── {style} · {len(out)}자 · {counter(out)} 토큰 · "
          f"{'캐시' if meta['cached'] else '호출'} ──")
    print(out)
    print(f"   남은 정답 문자열 {kept} / {c.must_include}\\n")'''),

        md(ALL_CONFIGS_MD.format(n=4, lab="03-summarize-llm") + """
| 설정 | 코퍼스 | 무엇을 보려고 |
|---|---|---|
| `plain` | 장문 8건 | **대조군** — 지시 없이 요약하면 |
| `question-aware` | 장문 8건 | 질문을 알려주면 |
| `preserve` | 장문 8건 | 지킬 것을 못 박으면 |
| `plain-short` | 산문 12건 | 짧고 숫자가 밀집한 입력 |
| `preserve-short` | 산문 12건 | 같은 입력에 지시를 주면 |

**먼저 예상 호출 수를 셉니다.** 캐시에 있으면 0회입니다.
"""),
        code('''
plan = []
for p in sorted(Path("configs").glob("*.yaml")):
    cfg = C.load(p)
    cs = dataset.load(cfg.dataset["path"], limit=cfg.dataset.get("limit"))
    s = Summarizer(DEPLOY, style=cfg.params["style"],
                   target_ratio=float(cfg.params["target_ratio"]))
    need = sum(1 for x in cs if not s.cached(x.text, x.question or ""))
    plan.append([cfg.name, Path(cfg.dataset["path"]).name, len(cs), need])

table(["설정", "코퍼스", "케이스", "예상 호출"], plan,
      align=["left", "left", "right", "right"],
      title="비용 예상", note="캐시에 있으면 0회입니다. 합계를 보고 진행하세요.")
print(f"합계 {sum(r[3] for r in plan)}회 — 캐시가 있으면 0 입니다.")'''),

        code('''
def run_config(path):
    cfg = C.load(path)
    cs = dataset.load(cfg.dataset["path"], limit=cfg.dataset.get("limit"))
    cnt = T.make_counter(cfg.tokenizer, cfg.model)
    smr = Summarizer(DEPLOY, style=cfg.params["style"],
                     target_ratio=float(cfg.params["target_ratio"]),
                     max_calls=int(cfg.params.get("max_calls", 200)),
                     max_output_tokens=int(cfg.params.get("max_output_tokens", 2048)))

    run = Run(cfg, RUNS)
    try:
        for x in cs:
            after, extra = compress(x.text, question=x.question or "",
                                    summarizer=smr)
            run.add(metrics.per_case(x.id, x.kind, x.text, after,
                                     x.must_include, cnt, extra),
                    before=x.text, after=after)
    finally:
        smr.save()

    m = metrics.aggregate(run.records, cnt)
    m.update(smr.stats())
    m["dataset_name"] = Path(cfg.dataset["path"]).name
    m["style"] = smr.style
    return cfg, m, run.finish(m, ["요약은 되돌릴 수 없습니다."])


results = []
for p in sorted(Path("configs").glob("*.yaml")):
    cfg, m, out = run_config(p)
    results.append((cfg.name, m, out))
    print(f\'{cfg.name:18s} 절감 {m["saved"]:6.1%} · \'
          f\'평균 보존율 {m["survival_mean"]:6.1%} · \'
          f\'최저 {m["survival_worst"]:6.1%} · \'
          f\'호출 {m["summary_calls"]}회\')'''),

        md(COMPARE_MD.format(n=5) + """
**절감률만 보면 `plain` 이 멀쩡해 보입니다.** 최저 보존율을 함께 봐야
무슨 일이 벌어졌는지 보입니다.
"""),
        code('''
table(
    ["설정", "코퍼스", "스타일", "절감", "평균 보존율", "최저 보존율", "온전한 케이스"],
    [[n, m["dataset_name"], m["style"], pct(m["saved"]),
      pct(m["survival_mean"]), pct(m["survival_worst"]),
      pct(m["survived_all_rate"])] for n, m, _ in results],
    align=["left", "left", "left", "right", "right", "right", "right"],
    title="조건 비교",
    note="절감이 커도 최저 보존율이 0% 면 그 질문에는 답할 수 없습니다.",
)

by = {n: m for n, m, _ in results}
if "plain" in by and "question-aware" in by:
    a, b = by["plain"], by["question-aware"]
    print(f\'장문: 질문을 알려주면 절감 {a["saved"]:.1%} → {b["saved"]:.1%}, \'
          f\'최저 보존율 {a["survival_worst"]:.1%} → {b["survival_worst"]:.1%}\')
    print("무엇을 남길지 판단할 근거가 생기면 나머지를 과감히 버릴 수 있습니다.")
if "plain-short" in by and "preserve-short" in by:
    a, b = by["plain-short"], by["preserve-short"]
    print(f\'\\\n산문: 지시를 주면 절감 {a["saved"]:.1%} → {b["saved"]:.1%}, \'
          f\'평균 보존율 {a["survival_mean"]:.1%} → {b["survival_mean"]:.1%}\')
    print("**더 줄이면서 더 지켰습니다.** 압축률과 보존율이 꼭 상충하지는 않습니다.")'''),

        md("""
## 6. 무엇이 사라졌나 — 실패를 눈으로

숫자만 보면 "보존율 33%" 가 무슨 뜻인지 안 와닿습니다. 실제 요약문을 봅니다.
"""),
        code('''
import json

worst_name = min(results, key=lambda r: r[1]["survival_worst"])[0]
d = dict((n, o) for n, _, o in results)[worst_name]
recs = [json.loads(l) for l in
        (d / "records.jsonl").read_text(encoding="utf-8").splitlines()]

# must_include 는 지표 레코드에 없습니다. 코퍼스에서 가져옵니다.
cfg_w = C.load(f"configs/{worst_name}.yaml")
want = {x.id: x.must_include
        for x in dataset.load(cfg_w.dataset["path"],
                              limit=cfg_w.dataset.get("limit"))}

broken = [r for r in recs if r["survival"] == 0.0][:4]
print(f"── {worst_name} 에서 보존율 0% 인 케이스 ──\\n")
for r in broken:
    print(f"[{r['id']} · {r['kind']}]")
    print(f"  원문   : {r['before'][:80]}…")
    print(f"  요약   : {r['after'][:100]}")
    print(f"  사라진 것: {want.get(r['id'], [])}\\n")

print("식별자와 금액이 '몇 건', '약 얼마' 같은 표현으로 녹아 없어집니다.")
print("문장은 매끄러워서 읽어서는 티가 안 납니다 — 그래서 더 위험합니다.")'''),

        md("""
## 7. 유형별 — 어디가 먼저 무너지나
"""),
        code('''
short = [(n, m) for n, m, _ in results if m["dataset_name"] == "sample"]
if len(short) == 2:
    (na, ma), (nb, mb) = short
    kinds = sorted(set(ma["by_kind"]) | set(mb["by_kind"]))
    table(
        ["유형", f"{na} 최저", f"{nb} 최저", "무슨 일이"],
        [[k,
          pct(ma["by_kind"].get(k, {}).get("survival_worst")),
          pct(mb["by_kind"].get(k, {}).get("survival_worst")),
          {"structured": "표·JSON 이 서술로 바뀌면 끝입니다",
           "identifier": "코드·번호가 '몇 건' 으로 뭉개집니다",
           "similar": "비슷한 항목이 하나로 합쳐집니다",
           "negation": "부정어는 지시해도 잘 안 지켜집니다",
           "numeric": "지시하면 잘 지킵니다",
           "short": "짧으면 요약할 것도 없습니다"}.get(k, "")]
         for k in kinds],
        align=["left", "right", "right", "left"],
        title="유형별 최저 보존율",
        note="부정이 뒤집히면 답이 정반대가 됩니다. 가장 위험한 유형입니다.",
    )'''),

        md("""
## 8. 이 지표가 못 보는 것

보존율은 **문자열 일치**로 잽니다. LLM 호출이 없어 스윕이 공짜라는 장점이
있지만 대가가 있습니다.

```
원문   주말 및 공휴일에는 접수되지 않습니다      must_include: ["않습니다"]
요약   주말·공휴일 제외                        → 보존율 0%
```

**뜻은 지켜졌는데 0% 로 셉니다.** 반대로 숫자를 그대로 베끼되 문맥을 뒤집는
요약은 100% 로 셉니다.

즉 이 지표는 **하한**입니다 — 낮으면 확실히 문제지만, 높다고 안전하다는
뜻은 아닙니다. 의미 수준 평가는 `agentic-eval` 축의 일입니다.
"""),

        *billed_cells(
            9,
            "요약문은 원문과 문체가 다릅니다. 짧아졌다고 토큰이 비례해서 "
            "줄지는 않으므로, 과금 기준으로 다시 재보는 편이 안전합니다.",
            "out_dir = dict((n, o) for n, _, o in results)['preserve']\n"
            "recs = [json.loads(l) for l in\n"
            "        (out_dir / 'records.jsonl').read_text(encoding='utf-8').splitlines()]\n"
            "pairs = [(x['id'], x['before'], x['after']) for x in recs]"),

        md("""
## 정리

- **요약은 되돌릴 수 없습니다** — 보존율이 곧 그 조건의 상한입니다
- **프롬프트가 알고리즘보다 중요합니다** — 지시만 바꿔 33.3% → 88.9%
- **압축률과 보존율은 꼭 상충하지 않습니다** — 무엇을 버려도 되는지 알면 둘 다 좋아집니다
- **식별자·부정어가 먼저 죽습니다** — 문장이 매끄러워서 티가 안 납니다
- **표·JSON 은 요약하지 마세요** — [`01`](../01-lossless-structure/run.ipynb) 이 무손실로 처리합니다

### 다음 랩

`04-llmlingua` — 모델 호출 없이 토큰 단위로 쳐냅니다.
"""),
    ])


# ══════════════════════════════════════════════════════════════════
# 04-llmlingua
# ══════════════════════════════════════════════════════════════════

def nb_04() -> dict:
    return notebook([
        md("""
# 04-llmlingua — 작은 모델이 토큰을 골라 버립니다

앞선 랩들과 판단 주체가 다릅니다.

| 랩 | 누가 판단하나 | 언어 영향 |
|---|---|---|
| `01` 무손실 | 규칙 | 없음 |
| `02` 참조핸들 | 겹침 점수 | 적음 |
| `03` 요약 | **큰 모델**이 다시 씁니다 | 적음 |
| **`04`** 프루닝 | **작은 모델**이 토큰마다 판정합니다 | **큽니다** |

중요도를 매기는 모델이 작아서, 그 모델이 약한 언어에서는 성능이 떨어집니다.
그래서 이 랩만 **한·영 이중언어 코퍼스**를 씁니다.

> **결론을 미리 말씀드리면** — 세 변형 중 `v2` 만 쓸 만했고,
> 같은 설정에서 **한국어가 영어보다 먼저 무너집니다.**

## ⚠️ 처음 실행은 오래 걸립니다

모델을 내려받습니다. `v2` 약 700MB, `v1`/`long` 약 1GB 입니다.
이 랩은 **전용 가상환경**을 쓰므로 커널을 `labs/04-llmlingua/.venv` 로
잡아주세요.
"""),
        md("## 1. kit 과 어댑터 불러오기"),
        code(BOOTSTRAP + '\nimport lingua as L\nfrom compress import compress\nfrom kit.metrics import survival\n\ntable(\n    ["변형", "무엇이 다른가", "필요한 것"],\n    [["v1", "토큰별 정보량으로 프루닝", "인과 LM"],\n     ["long", "질문을 주고 문단별 중요도를 함께 봄", "인과 LM + 질문"],\n     ["v2", "분류 모델이 토큰을 남길지 판정", "전용 인코더"]],\n    align=["left", "left", "left"],\n    title="LLMLingua 3형제 — 같은 클래스, 다른 파라미터",\n)\n\n# 모델은 크기별로 고를 수 있습니다. 기본은 small 입니다.\ntable(\n    ["변형", "별칭", "모델", "크기"],\n    [[v, tier, name.split("/")[-1][:42], size]\n     for v, tiers in L.MODELS.items() for tier, (name, size) in tiers.items()],\n    align=["left", "left", "left", "left"],\n    title="고를 수 있는 모델",\n    note="기본은 small 입니다 — 받자마자 돌려보실 수 있어야 해서입니다. "\n         "config 의 model_name 이나 --model 로 바꾸실 수 있습니다.",\n)\n'),

        md('\n## 1-1. 어느 모델로 돌릴지 고르기\n\n아래 셀을 실행하면 드롭다운이 나옵니다. **바꾸신 뒤 아래 셀들을 다시\n실행하면** 그 모델로 결과가 나옵니다.\n\n| 별칭 | `v1`·`long` | `v2` | 특징 |\n|---|---|---|---|\n| `small` (기본) | Qwen2.5-0.5B · 1GB | bert-base-multilingual · 700MB | 빠릅니다 |\n| `large` | Qwen2.5-1.5B · 3GB | **xlm-roberta-large · 2.2GB** | 정확합니다 |\n| `paper` | Llama-2-7b · 13GB | — | 논문이 쓴 것 |\n\n**처음 고르시는 모델은 내려받느라 몇 분 걸립니다.** `~/.cache/huggingface/`\n에 남아 다음부터는 로딩만 합니다.\n\n> 드롭다운이 안 보이면 `ipywidgets` 가 없는 것입니다. 그때는 아래 셀의\n> `MODEL = "small"` 을 직접 고치셔도 똑같이 동작합니다.\n'),
        code('\n# 이 값을 바꾸면 아래 셀들이 전부 그 모델을 씁니다.\nMODEL = "small"          # small | large | paper | HuggingFace 경로\n\ntry:\n    import ipywidgets as W\n    from IPython.display import display\n\n    _sel = W.Dropdown(\n        options=[("small — 빠릅니다 (기본)", "small"),\n                 ("large — 정확합니다", "large"),\n                 ("paper — 논문이 쓴 모델 (v1/long 만, 13GB)", "paper")],\n        value=MODEL, description="모델:",\n        style={"description_width": "initial"},\n        layout=W.Layout(width="420px"))\n\n    def _on(change):\n        global MODEL\n        MODEL = change["new"]\n        print(f"MODEL = {MODEL!r} · 아래 셀들을 다시 실행해 주세요")\n\n    _sel.observe(_on, names="value")\n    display(_sel)\nexcept ImportError:\n    print("ipywidgets 가 없어 드롭다운을 못 만듭니다.")\n    print("위의 MODEL 값을 직접 고치시면 똑같이 동작합니다.")\n\n\ndef model_for(variant):\n    """고른 모델을 이 변형에 맞게 풀어 줍니다.\n\n    v2 에는 paper 티어가 없습니다. 그때는 large 로 대신합니다 —\n    조용히 small 로 떨어지면 "큰 모델을 골랐는데 결과가 그대로" 가 됩니다.\n    """\n    tiers = L.MODELS[variant]\n    if MODEL in tiers:\n        return MODEL\n    if MODEL == "paper" and "large" in tiers:\n        print(f"  ({variant} 에는 paper 가 없어 large 로 대신합니다)")\n        return "large"\n    return MODEL          # HuggingFace 경로를 직접 주신 경우\n\n\nprint(f"\\n현재 MODEL = {MODEL!r}")\nfor v in ("v1", "long", "v2"):\n    print(f"  {v:5s} → {L.resolve_model(v, model_for(v))}")\n'),

        md("""
## 지표 두 가지 — 표를 읽기 전에

| 이름 | 무엇을 재나 |
|---|---|
| **절감** | 토큰이 얼마나 줄었나 |
| **보존율** | 답에 꼭 필요한 문자열(`must_include`)이 압축 후에도 남은 비율 |

보존율 예시입니다.

```
질문        3월 결제 총액과 환불액은?
필요한 것    ["32,450,000", "1,280,500"]   ← 2개

압축 후 2개 다 남음  → 100%
1개만 남음          →  50%
```

아래 표에서 **`전체` · `한국어` · `영어` 는 전부 같은 보존율**입니다.
전체는 12건 평균이고, 나머지는 그중 해당 언어만 골라 낸 평균입니다.

> 지금은 한·영이 6건씩 같아서 전체가 두 언어의 가운데값과 일치합니다.
> **건수가 달라지면 많은 쪽으로 기웁니다.** 한국어 서비스에 쓰실 거라면
> 전체가 아니라 **한국어 열**을 기준으로 보세요.
"""),
        md("""
## 2. 코퍼스 — 같은 사실을 한국어와 영어로

번역이 아니라 **같은 사실을 담은 쌍**입니다. `pair_id` 로 묶여 있어
언어별 차이를 케이스 단위로 볼 수 있습니다.
"""),
        code('\ncases = dataset.load("../data/sample-bilingual")\ncounter = T.make_counter({"mode": "local"}, "gpt-5.4")\n\nko = [c for c in cases if c.meta["lang"] == "ko"]\nen = [c for c in cases if c.meta["lang"] == "en"]\n\ntable(\n    ["언어", "건수", "문자", "토큰", "문자당 토큰"],\n    [[lg, len(xs), f"{sum(len(c.text) for c in xs):,}",\n      f"{sum(counter(c.text) for c in xs):,}",\n      f"{sum(counter(c.text) for c in xs) / sum(len(c.text) for c in xs):.2f}"]\n     for lg, xs in [("한국어", ko), ("영어", en)]],\n    align=["left", "right", "right", "right", "right"],\n    title="이중언어 코퍼스",\n    note="같은 내용인데 한국어가 문자당 토큰을 더 씁니다. 압축이 더 절실한 "\n         "쪽인데, 아래에서 보시면 품질은 더 나쁩니다.",\n)\n\nc = ko[0]\nprint(f"[{c.id}] {c.question}")\nprint(f"  {c.text[:70]}…")\nprint(f"  정답 문자열 {c.must_include}")\n'),

        md("""
## 3. 세 변형이 같은 문장을 어떻게 다루나 — 한국어와 영어로

**같은 사실을 담은 한·영 쌍**(`ko-01` / `en-01`)에 셋을 각각 겁니다.
언어만 다르고 내용·질문·정답 문자열은 같으므로, 차이가 나면 그건 순전히
언어 때문입니다.

**처음 실행하면 모델 세 개를 받느라 몇 분 걸립니다.**
"""),
        code('# ── 이 셀의 설정 ──────────────────────────────────────────────\nRATE = 0.5               # 남길 비율. 낮출수록 많이 버립니다\nRESERVE_DIGIT = True     # 숫자를 지키려 시도합니다\nPAIR = ["ko-01", "en-01"]\n\n# 같은 사실을 담은 한·영 쌍입니다. 언어만 다르고 내용·질문·정답이 같습니다.\nprint(f"설정 · 모델 {MODEL} · rate {RATE} · force_reserve_digit {RESERVE_DIGIT}")\nprint()\n\nfor cid in PAIR:\n    probe = [c for c in cases if c.id == cid][0]\n    print(f"[{cid}] {probe.question}")\n    print(f"  원문: {probe.text[:88]}…")\n    print(f"  정답 문자열: {probe.must_include}")\n    print()\n\nrows = []\nfor cid in PAIR:\n    probe = [c for c in cases if c.id == cid][0]\n    for v in ["v1", "long", "v2"]:\n        out, meta = compress(probe.text, question=probe.question, variant=v,\n                             model_name=model_for(v),\n                             rate=RATE, force_reserve_digit=RESERVE_DIGIT)\n        kept = [m for m in probe.must_include\n                if m.replace(",", "") in out.replace(" ", "").replace(",", "")]\n        rows.append([cid, v, f"{counter(probe.text)} → {counter(out)}",\n                     pct(1 - counter(out) / counter(probe.text)),\n                     pct(survival(out, probe.must_include)),\n                     ", ".join(kept) if kept else "(전부 사라짐)"])\n        print(f"  {cid} / {v} 완료", flush=True)\n\ntable(\n    ["케이스", "변형", "토큰", "절감", "보존율", "남은 정답 문자열"],\n    rows,\n    align=["left", "left", "right", "right", "right", "left"],\n    title=f"세 변형 비교 · 모델 {MODEL} · rate={RATE} "\n          f"· force_reserve_digit={RESERVE_DIGIT}",\n    note="같은 변형·같은 rate 인데 언어에 따라 남는 것이 다릅니다.",\n)\n'),

        md("""
표에서 세 가지가 보입니다.

**① `v1` 은 거의 압축하지 않습니다.** 한국어 0.0%, 영어 1.1% 입니다.
질문 없이 토큰 정보량만 보는데, 0.5B 모델은 무엇을 버려도 되는지 판단할
자신이 없어서 대부분 그대로 둡니다. 보존율 100% 는 잘해서가 아니라
**아무것도 안 버려서** 나온 값입니다.

**② `long` 은 많이 버리지만 정답까지 버립니다.** 영어는 56.4% 를 줄이면서
정답 문자열을 **전부** 잃었습니다. 토큰 단위로 잘라서 `32,450,000` 이
`32,450,00RW` 처럼 숫자 중간에서 끊깁니다.

**③ `v2` 만 언어에 따라 갈립니다.** 영어는 37.2% 를 줄이고 보존율 100%,
한국어는 36.2% 를 줄이고 보존율 50% 입니다. 같은 설정인데 한국어에서만
`32,450,000` 이 사라졌습니다.

> `v1`/`long` 의 문제는 **작은 모델을 써서** 생깁니다. "LongLLMLingua 가
> 나쁘다" 가 아니라 "작은 순위 모델로는 못 쓴다" 로 읽어주세요.
> 논문은 7B 를 썼고 여기서는 0.5B 를 씁니다.
"""),

        md("""
## 4. 조용히 무시되는 인자 — 이 랩에서 가장 조심할 부분

`use_llmlingua2=True` 인 압축기에 `question` 이나 `rank_method` 를 넘기면
**에러 없이 무시됩니다.** LongLLMLingua 설정을 v2 에 잘못 붙여도 그냥
돌아가고 결과만 v2 그대로입니다.

숫자가 안 바뀌는 이유를 찾느라 시간을 버리기 쉬워서, 어댑터가 거부합니다.
"""),
        code('\ntry:\n    L.check_params("v2", {"rate": 0.5, "question": "환불 수수료는?",\n                          "rank_method": "longllmlingua"})\n    print("통과 — 이러면 안 됩니다")\nexcept ValueError as e:\n    print("거부됨")\n    print()\n    print(e)\n'),

        md(ALL_CONFIGS_MD.format(n=5, lab="04-llmlingua") + """
| 설정 | 무엇을 보려고 |
|---|---|
| `v2` | 이 랩의 권장 조건 |
| `v1` | 질문 없이 토큰 정보량만 |
| `long` | 질문을 주면 나아지나 |
| `v2-noop` | `rate=1.0` **자가 점검** |

`v2-noop` 이 중요합니다. 아무것도 안 버리는 설정인데 **토큰이 늘어납니다.**
"""),
        code('\ndef run_config(path):\n    cfg = C.load(path)\n    cs = dataset.load(cfg.dataset["path"], limit=cfg.dataset.get("limit"))\n    cnt = T.make_counter({"mode": "local"}, cfg.model)\n    params = dict(cfg.params)\n    variant = params.pop("variant", "v2")\n    # 설정 파일이 지정한 모델을 그대로 씁니다. 위에서 고른 MODEL 은\n    # 개별 셀에만 적용되고, 여기서는 config 가 기준입니다.\n    mdl = params.pop("model_name", None)\n\n    run = Run(cfg, RUNS)\n    for x in cs:\n        after, extra = compress(x.text, question=x.question or "",\n                                variant=variant, model_name=mdl, **params)\n        extra["lang"] = x.meta.get("lang", "-")\n        run.add(metrics.per_case(x.id, x.kind, x.text, after,\n                                 x.must_include, cnt, extra),\n                before=x.text, after=after)\n\n    m = metrics.aggregate(run.records, cnt)\n    m["variant"] = variant\n    m["config"] = cfg.name\n    m["model"] = L.resolve_model(variant, mdl)\n    m["rate"] = params.get("rate")\n    for lg in ("ko", "en"):\n        xs = [r for r in run.records if r["lang"] == lg]\n        if xs:\n            m[f"surv_{lg}"] = sum(r["survival"] for r in xs) / len(xs)\n    return cfg, m, run.finish(m, [f"변형 {variant}"])\n\n\nresults = []\nfor p in sorted(Path("configs").glob("*.yaml")):\n    cfg, m, out = run_config(p)\n    results.append((cfg.name, m, out))\n    print(f\'{cfg.name:12s} {m["variant"]:5s} rate={str(m["rate"]):4s} \'\n          f\'{m["model"].split("/")[-1][:34]:36s} \'\n          f\'절감 {m["saved"]:6.1%} · 보존 {m["survival_mean"]:6.1%}\', flush=True)\n'),

        md(COMPARE_MD.format(n=6)),
        code('\nn_ko = len([c for c in cases if c.meta["lang"] == "ko"])\nn_en = len([c for c in cases if c.meta["lang"] == "en"])\n\n# 뒤의 세 열은 같은 보존율을 언어별로 나눈 것입니다. 열 이름에 건수를 적어\n# "전체가 두 언어의 단순평균인가?" 라는 오해를 줄입니다.\nrows = []\nfor n, m, _ in results:\n    ko, en = m.get("surv_ko"), m.get("surv_en")\n    gap = (en - ko) if (ko is not None and en is not None) else None\n    rows.append([n, m["variant"], m["model"].split("/")[-1][:26], m["rate"],\n                 pct(m["saved"]),\n                 pct(m["survival_mean"]), pct(ko), pct(en),\n                 "—" if gap is None else f"{gap * 100:+.1f}%p"])\n\ntable(\n    ["설정", "변형", "모델", "rate", "절감",\n     f"보존율 전체({len(cases)}건)", f"한국어({n_ko}건)", f"영어({n_en}건)",\n     "영−한 격차"],\n    rows,\n    align=["left", "left", "left", "right", "right",\n           "right", "right", "right", "right"],\n    title="조건 비교 — 설정마다 변형·모델·rate 가 다릅니다",\n    note=f"\'전체\' 는 {len(cases)}건 전부의 평균입니다. 지금은 한·영이 {n_ko}건씩 "\n         f"같아서 두 언어 평균의 가운데값과 일치하지만, 건수가 달라지면 "\n         f"많은 쪽으로 기웁니다.",\n)\n\nreal = [m for _, m, _ in results if m.get("rate") != 1.0]\nif real:\n    w = max(real, key=lambda m: (m.get("surv_en") or 0) - (m.get("surv_ko") or 0))\n    print(f"격차가 가장 큰 조건은 {w[\'config\']} 입니다.")\n    print(f"  전체 {w[\'survival_mean\']:.1%} 로는 무난해 보이지만 "\n          f"한국어만 보면 {w[\'surv_ko\']:.1%} 입니다.")\n    print("한국어 서비스에 쓰신다면 \'전체\' 가 아니라 \'한국어\' 열을 보세요.")\n\nby = {n: m for n, m, _ in results}\nif "v2-noop" in by:\n    m = by["v2-noop"]\n    print(f\'v2-noop: rate=1.0 인데 절감 {m["saved"]:.1%} · \'\n          f\'보존율 {m["survival_mean"]:.1%}\')\n    print("아무것도 안 버렸는데 토큰이 늘었습니다. 토큰에서 텍스트를 다시")\n    print("만들면서 \'32,450,000\' 이 \'32, 450, 000\' 처럼 벌어지기 때문입니다.")\nif "v2" in by and "long" in by:\n    print()\n    print(f\'v2 보존 {by["v2"]["survival_mean"]:.1%} vs \'\n          f\'long 보존 {by["long"]["survival_mean"]:.1%} — \'\n          f\'질문을 주는 long 이 오히려 나쁩니다.\')\n    print("작은 모델로 토큰 단위 프루닝을 하면 숫자가 조각나기 때문입니다.")\n'),

        md("""
## 7. 압축률 스윕 — 어디서 무너지나

`rate` 는 **남길 비율**입니다. 낮출수록 많이 버립니다.
언어별로 무너지는 지점이 다른지 봅니다.
"""),
        code('\n# ── 이 셀의 설정 ──────────────────────────────────────────────\nRATES = [0.9, 0.7, 0.5, 0.3]     # 남길 비율\nRESERVE_DIGIT = True\n\nprint(f"설정 · 변형 v2 · 모델 {MODEL} · rate {RATES} "\n      f"· force_reserve_digit {RESERVE_DIGIT}")\nprint()\n\nrows = []\nfor rate in RATES:\n    recs = []\n    for x in cases:\n        out, meta = compress(x.text, variant="v2", model_name=model_for("v2"),\n                             rate=rate, force_reserve_digit=RESERVE_DIGIT)\n        recs.append({"lang": x.meta["lang"],\n                     "s": survival(out, x.must_include),\n                     "tb": counter(x.text), "ta": counter(out)})\n    tb = sum(r["tb"] for r in recs)\n    ta = sum(r["ta"] for r in recs)\n    g = {lg: [r["s"] for r in recs if r["lang"] == lg] for lg in ("ko", "en")}\n    rows.append([rate, pct(1 - ta / tb),\n                 pct(sum(r["s"] for r in recs) / len(recs)),\n                 pct(min(r["s"] for r in recs)),\n                 pct(sum(g["ko"]) / len(g["ko"])),\n                 pct(sum(g["en"]) / len(g["en"]))])\n    print(f"  rate={rate} 완료", flush=True)\n\ntable(\n    ["rate", "절감", f"보존 전체({len(cases)}건)", "보존 최저",\n     f"한국어({n_ko}건)", f"영어({n_en}건)"],\n    rows,\n    align=["right"] * 6,\n    title=f"압축률 스윕 · 변형 v2 · 모델 {MODEL} "\n          f"· force_reserve_digit={RESERVE_DIGIT}",\n    note="rate 0.7 을 보세요. 영어는 아직 멀쩡한데 한국어는 이미 무너집니다. "\n         "\'전체\' 는 12건 평균이라 이 격차를 가립니다.",\n)\n'),

        md('\n## 8. 레이턴시 트레이드오프 — 압축은 공짜가 아닙니다\n\n여기까지는 **얼마나 줄었나**만 봤습니다. 그런데 압축 자체도 시간을 씁니다.\n작은 모델을 한 번 더 돌리는 일이니까요.\n\n그래서 세 조건을 **끝에서 끝까지** 재봅니다.\n\n| 재는 것 | 무엇 |\n|---|---|\n| **압축 소요** | LLMLingua 가 텍스트를 줄이는 데 걸린 시간 |\n| **응답 소요** | 그 컨텍스트로 본 모델에 물어보고 답을 받기까지 |\n| **합계** | 사용자가 실제로 기다리는 시간 |\n\n모델 로딩은 미리 끝내고 잽니다. 한 번만 드는 비용이라 매 요청에 포함하면\n오해를 부릅니다.\n\n> 긴 케이스(`longdoc`·`structured`)만 씁니다. 짧은 글은 압축할 것도 없고\n> 시간 차이도 묻힙니다.\n'),
        code('\nimport time\nimport statistics as st\nfrom kit.provider import complete\n\n# ── 이 셀의 설정 ──────────────────────────────────────────────\nRATE = 0.5\nRESERVE_DIGIT = True\nKINDS = ("longdoc", "structured")   # 긴 것만. 짧은 글은 시간 차이가 묻힙니다\nTIERS = ("none", "small", "large")\n\nDEP = env.get("AZURE_OPENAI_DEPLOYMENT")\nuse = [c for c in cases if c.meta["kind"] in KINDS]\nprint(f"설정 · 변형 v2 · rate {RATE} · 유형 {KINDS} · 본 모델 {DEP}")\n\nfor tier in ("small", "large"):\n    L.load("v2", tier)          # 로딩을 먼저 끝냅니다. 측정에 섞이면 안 됩니다.\nprint(f"케이스 {len(use)}건 · 모델 로딩 완료\\n")\n\n\ndef ask(ctx, q):\n    t0 = time.perf_counter()\n    complete(f"{ctx}\\n\\n질문: {q}\\n한 문장으로 짧게 답하세요.",\n             DEP, max_output_tokens=256)\n    return time.perf_counter() - t0\n\n\nrows, detail = [], {}\nfor cond in TIERS:\n    recs = []\n    for c in use:\n        if cond == "none":\n            comp_ms, out = 0.0, c.text\n        else:\n            t0 = time.perf_counter()\n            out, _ = compress(c.text, variant="v2", model_name=cond,\n                              rate=RATE, force_reserve_digit=RESERVE_DIGIT)\n            comp_ms = (time.perf_counter() - t0) * 1000\n        recs.append(dict(lang=c.meta["lang"], comp_ms=comp_ms, lat=ask(out, c.question),\n                         tb=counter(c.text), ta=counter(out),\n                         s=survival(out, c.must_include)))\n    detail[cond] = recs\n\n    tb, ta = sum(r["tb"] for r in recs), sum(r["ta"] for r in recs)\n    ko = [r["s"] for r in recs if r["lang"] == "ko"]\n    en = [r["s"] for r in recs if r["lang"] == "en"]\n    cm = st.median(r["comp_ms"] for r in recs)\n    lt = st.median(r["lat"] for r in recs)\n    rows.append([{"none": "압축 없음", "small": "v2 small", "large": "v2 large"}[cond],\n                 f"{tb:,} → {ta:,}", pct(1 - ta / tb),\n                 pct(sum(ko) / len(ko)), pct(sum(en) / len(en)),\n                 f"{cm:.0f}ms", f"{lt:.2f}s", f"{cm / 1000 + lt:.2f}s"])\n    print(f"  {cond} 완료", flush=True)\n\ntable(\n    ["조건", "토큰", "절감", "보존 한국어", "보존 영어",\n     "압축 소요", "응답 소요", "합계"],\n    rows,\n    align=["left", "right", "right", "right", "right", "right", "right", "right"],\n    title=f"끝에서 끝까지 · 변형 v2 · rate={RATE} · 케이스 {len(use)}건 "\n          f"· 본 모델 {DEP}",\n    note="\'합계\' 가 사용자가 기다리는 시간입니다. 중앙값이며 응답 시간은 "\n         "호출마다 흔들리므로 소수점 아래는 잡음으로 보세요.",\n)\n'),
        md('\n### 읽어야 할 것\n\n**토큰은 절반으로 줄었는데 합계는 늘었습니다.**\n\n이 규모(약 1,200토큰)에서는 응답 시간이 **입력 길이가 아니라 출력 생성과\n왕복 네트워크**에 좌우됩니다. 입력을 절반으로 줄여도 응답은 거의 그대로인데,\n압축 시간만 얹히는 셈입니다.\n\n| | 무엇을 얻나 | 무엇을 잃나 |\n|---|---|---|\n| 비용 | 입력 토큰 **약 절반** | — |\n| 속도 | — | 압축 시간만큼 **느려짐** |\n| 정확도 | — | 보존율이 100% 아래로 |\n\n**즉 이 규모에서 압축은 비용 최적화이지 속도 최적화가 아닙니다.**\n\n### 그럼 속도에도 도움이 되는 때는\n\n입력이 충분히 커서 **프리필(prefill)이 병목이 될 때**입니다. 수만 토큰을\n넣으면 입력을 읽는 시간 자체가 길어지고, 그때는 절반으로 줄인 효과가\n압축 비용을 넘어섭니다.\n\n경계를 대략 잡으면 이렇습니다.\n\n```\n압축으로 아끼는 시간  ≈  (줄인 토큰 수) × (토큰당 프리필 시간)\n압축에 쓰는 시간      ≈  100~250ms  (v2 기준, 이 코퍼스에서 실측)\n\n앞이 뒤보다 커야 속도로도 이득입니다.\n```\n\n**작은 모델이 압축은 3배 빠릅니다**(100ms vs 232ms). 그런데 보존율은\n`large` 가 낫습니다. 속도가 급하면 `small`, 정확도가 급하면 `large` 로\n가시면 됩니다 — 다만 위에서 보셨듯 **이 규모에서는 둘 다 속도 이득이\n없습니다.**\n'),

        *billed_cells(9, '이 랩은 **압축 결과를 토큰에서 다시 만듭니다.** 그 과정에서 `32,450,000` 이 `32, 450, 000` 으로 벌어지기도 하는데, 그렇게 바뀐 글자를 모델 토크나이저가 어떻게 쪼개는지는 tiktoken 추정으로 알 수 없습니다. `rate=1.0` 인데 토큰이 늘었던 것도 같은 이유였습니다.', 'cfg4 = C.load("configs/v2.yaml")\ncs4 = dataset.load(cfg4.dataset["path"])\nparams4 = dict(cfg4.params)\nparams4.pop("variant", None)\nparams4.pop("model_name", None)\n\n# 코퍼스가 ko/en 교대라 앞에서부터 4건을 뽑으면 두 언어가 2건씩 들어옵니다.\n# 3건만 뽑으면 한국어로 기울어 언어 비교가 안 됩니다.\npairs = [(x.id, x.text,\n          compress(x.text, variant="v2", model_name=model_for("v2"), **params4)[0])\n         for x in cs4]', limit=4),

        md("""
## 정리

- **세 변형 중 `v2` 만 쓸 만했습니다** — 작은 모델로 토큰 단위 프루닝을 하면
  숫자와 식별자가 조각납니다
- **한국어가 영어보다 먼저 무너집니다** — 같은 `rate` 에서 영어가 91.7% 일 때
  한국어는 66.7% 였습니다
- **한국어는 애초에 토큰을 더 씁니다** — 문자당 1.8배. 압축이 더 절실한데
  품질은 더 나쁩니다
- **`rate=1.0` 이 무손실이 아닙니다** — 토큰에서 텍스트를 재구성하면서
  숫자 서식이 벌어져 오히려 늘어납니다
- **숫자·식별자가 답인 문서에는 쓰지 마세요**

### 결론을 일반화하지 마세요

이 랩은 **0.5B 모델**로 돌립니다. 논문은 7B 를 썼습니다.
"LongLLMLingua 가 나쁘다" 가 아니라 **"작은 순위 모델로는 못 쓴다"** 입니다.
`configs/*.yaml` 의 `model_name` 으로 바꾸실 수 있습니다.
"""),
    ])


BUILDERS = {"00": ("00-baseline", nb_00),
            "01": ("01-lossless-structure", nb_01),
            "02": ("02-handle-ref", nb_02),
            "03": ("03-summarize-llm", nb_03),
            "04": ("04-llmlingua", nb_04)}


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
