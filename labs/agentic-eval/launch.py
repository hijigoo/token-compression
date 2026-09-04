#!/usr/bin/env python3
"""실험 조건(arm)을 읽어 프록시를 전부 띄우고 pier 설정을 생성한다.

    python launch.py experiments/ratio-sweep.yaml

하는 일:
    1. arm 마다 포트를 자동 배정한다 (8801, 8802, ...)
    2. Headroom / 로컬 프록시를 각각 기동하고 헬스체크한다
    3. pier 설정 yaml 을 만든다 (agents 블록 = arm 목록)
    4. `pier run --config ...` 명령을 출력하고, Ctrl+C 까지 프록시를 유지한다

왜 스크립트인가:
    긴 headroom CLI 를 손으로 여러 번 치면 "어느 포트가 어느 ratio 였는지" 를
    반드시 헷갈린다. 실험이 오염되는 지점은 대부분 거기다.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
BASE_PORT = 8801

# 컨테이너가 쓸 PyPI 주소. 루트 uv.toml 의 미러를 그대로 쓴다.
PYPI_INDEX = os.environ.get(
    "PYPI_INDEX", "https://mirror.kakao.com/pypi/simple")

# ─────────────────────────────────────────────────────────────
# 벤치마크와 언어 -> 데이터셋 경로
#
# 실험 파일이 경로를 직접 쓰지 않게 한다. 손으로 쓰면 name 은 그대로 둔 채
# path 만 바꾸는 실수가 나고, 그러면 한국어 결과가 영어 실행 폴더에 조용히
# 덮인다. 에러도 나지 않아 나중에는 구분할 방법이 없다.
# ─────────────────────────────────────────────────────────────
BENCHMARKS = {
    "deep-swe": {"root": "datasets/deep-swe", "tasks": "tasks"},
    # Terminal Bench 2.1 은 pier 와 같은 task.toml 스키마를 씁니다(둘 다
    # Harbor 계열). 그래서 로더를 따로 만들 필요 없이 한 줄로 붙습니다.
    "terminal-bench": {"root": "datasets/terminal-bench", "tasks": "tasks"},
}
LANGS = ("en", "ko")


def dataset_dir(benchmark: str, lang: str) -> Path:
    """`en` 은 원본, 그 외 언어는 `<root>-<lang>` 을 쓴다."""
    b = BENCHMARKS[benchmark]
    root = b["root"] if lang == "en" else f"{b['root']}-{lang}"
    return HERE / root / b["tasks"]

# ─────────────────────────────────────────────────────────────
# 벤치마크 전제조건. yaml 에 노출하지 않는다.
#
#   --no-cache : 시맨틱 캐시가 켜지면 토큰 절감이 "압축 덕분" 인지
#                "캐시 덕분" 인지 분리할 수 없다.
#   --no-ccr   : CCR 은 원문을 로컬에 두고 모델이 headroom_retrieve 툴로
#                되찾게 하는데, mini-swe-agent 는 bash 밖에 없어 그 툴을
#                호출할 수 없다. 켜두면 정보가 그냥 사라진다.
#
# 스윕 항목을 복붙하다 한 arm 에서 이 플래그가 빠지면, 결과만 봐서는
# 절대 알아챌 수 없다. 그래서 선언 파일이 아니라 코드에 고정한다.
# ─────────────────────────────────────────────────────────────
HEADROOM_FIXED = ["--no-cache", "--no-ccr"]
HEADROOM_FORBIDDEN = {
    "--no-cache", "--cache", "--no-ccr", "--ccr",   # 위 전제조건
    "--port", "--host", "--backend", "--openai-api-url",  # launch.py 가 관리
}


def die(msg: str) -> None:
    print(f"\033[31m✗ {msg}\033[0m", file=sys.stderr)
    raise SystemExit(1)


def info(msg: str) -> None:
    print(f"\033[36m▸ {msg}\033[0m", flush=True)


# ─────────────────────────────────────────────────────────────
# 검증
# ─────────────────────────────────────────────────────────────
def validate(spec: dict) -> None:
    for key in ("name", "model", "benchmark", "dataset", "arms"):
        if key not in spec:
            die(f"실험 파일에 '{key}' 가 없습니다")

    if spec["benchmark"] not in BENCHMARKS:
        die(f"모르는 benchmark: {spec['benchmark']!r} "
            f"(가능: {', '.join(BENCHMARKS)})")

    langs = spec.get("langs", ["en"])
    if not langs:
        die("langs 가 비어 있습니다")
    bad = [x for x in langs if x not in LANGS]
    if bad:
        die(f"모르는 langs: {bad} (가능: {', '.join(LANGS)})")
    if len(set(langs)) != len(langs):
        die(f"langs 에 중복이 있습니다: {langs}")

    ds = spec["dataset"]
    if "path" in ds:
        # 경로를 손으로 쓰면 name 은 그대로 둔 채 path 만 바꾸는 실수가 난다.
        die("dataset.path 는 더 이상 쓰지 않습니다.\n"
            "  benchmark 와 langs 로 지정하세요:\n"
            "    benchmark: deep-swe\n"
            "    langs: [en, ko]")
    if "tasks" in ds:
        if not isinstance(ds["tasks"], list):
            die("dataset.tasks 는 목록이어야 합니다")
        if "n_tasks" in ds or "sample_seed" in ds:
            die("dataset.tasks 를 주셨으면 n_tasks·sample_seed 는 쓰지 않습니다.\n"
                "  목록으로 정하는 것이므로 뽑을 것이 없습니다.\n"
                "  전부 쓰시려면 tasks: [] 로 비워 두세요.")
    elif "sample_seed" not in ds:
        # 시드가 없으면 arm 마다 다른 태스크를 받아 비교 자체가 무의미해진다.
        die("dataset.sample_seed 가 없습니다. 시드가 없으면 arm 간 비교가 성립하지 않습니다.")

    arms = spec["arms"]
    if len(arms) < 2:
        die("arm 이 2개 미만입니다. 비교할 대상이 없습니다.")

    names = [a.get("name") for a in arms]
    if len(set(names)) != len(names):
        die(f"arm 이름이 중복됩니다: {names}")

    for arm in arms:
        kind = arm.get("kind")
        if kind not in ("direct", "headroom", "local"):
            die(f"[{arm.get('name')}] kind 는 direct|headroom|local 이어야 합니다: {kind!r}")

        if kind == "headroom":
            bad = set(arm.get("args", [])) & HEADROOM_FORBIDDEN
            if bad:
                die(
                    f"[{arm['name']}] 이 플래그는 launch.py 가 관리합니다: {sorted(bad)}\n"
                    f"  --no-cache/--no-ccr 는 항상 강제되며 끌 수 없습니다."
                )
        bad = set(arm.get("protect") or {}) - PROTECT_KEYS
        if bad:
            die(f"[{arm.get('name')}] 모르는 protect 키: {sorted(bad)} "
                f"(가능: {sorted(PROTECT_KEYS)})")
        if arm.get("protect") and kind != "local":
            die(f"[{arm.get('name')}] protect 는 local arm 에서만 씁니다.\n"
                f"  headroom 은 자체 옵션(PROTECT_RECENT 등)을 args 로 받습니다.")

        if kind == "local":
            if "compressor" not in arm:
                die(f"[{arm['name']}] local arm 에는 compressor 가 필요합니다")
            ratio = arm.get("ratio", 1.0)
            if not 0 < float(ratio) <= 1:
                die(f"[{arm['name']}] ratio 는 (0, 1] 이어야 합니다: {ratio}")

    if not any(a["kind"] == "direct" for a in arms):
        print("\033[33m! 기준선(kind: direct) arm 이 없습니다. "
              "비교 기준이 없으면 절감률·손실을 해석할 수 없습니다.\033[0m")


# ─────────────────────────────────────────────────────────────
# 태스크 선정
#
# 언어별 풀 크기가 다르면 같은 시드를 줘도 다른 태스크가 뽑힌다. 영어는
# 113건인데 한국어는 번역해 둔 것만 있기 때문이다. 그 상태로 돌리면 두
# 언어가 서로 다른 문제를 푼 결과를 나란히 놓게 되는데, 표에서는 전혀
# 드러나지 않는다.
#
# 그래서 여기서 **교집합을 구해 직접 뽑고**, 그 목록대로 실행 전용 트리를
# 만든다. pier 에게는 정확히 그 태스크만 든 디렉터리를 준다. 샘플링이
# 우리 손을 떠나지 않으므로 언어 간 짝이 어긋날 수가 없다.
# ─────────────────────────────────────────────────────────────
def pick_tasks(benchmark: str, langs: list[str],
               n: int | None, seed: int | None,
               explicit: list[str] | None = None) -> list[str]:
    pools: dict[str, set[str]] = {}
    for lang in langs:
        d = dataset_dir(benchmark, lang)
        if not d.is_dir():
            hint = ("  ./setup.sh 를 실행하세요." if lang == "en" else
                    f"  python translate.py stage -b {benchmark} 로 만드세요.")
            die(f"{lang} 데이터셋이 없습니다: {d.relative_to(REPO)}\n{hint}")
        pools[lang] = {x.name for x in d.iterdir() if x.is_dir()}
        if not pools[lang]:
            die(f"{lang} 데이터셋이 비어 있습니다: {d.relative_to(REPO)}")

    shared = set.intersection(*pools.values())
    if not shared:
        die("모든 언어에 공통으로 있는 태스크가 없습니다.")

    if explicit is not None:
        if not explicit:
            # 빈 목록은 "고르지 않겠다" 는 뜻이다. 공통인 것을 전부 쓴다.
            return sorted(shared)
        missing = [t for t in explicit if t not in shared]
        if missing:
            die(f"모든 언어에 있지는 않은 태스크: {missing}\n"
                f"  번역이 빠졌다면: "
                f"python translate.py translate {' '.join(missing)} -b {benchmark}")
        return list(explicit)

    for lang in langs:
        only = pools[lang] - shared
        if only:
            info(f"{lang} 에만 있는 태스크 {len(only)}건은 제외합니다 "
                 f"(언어 간 짝을 맞추기 위해)")

    if n > len(shared):
        die(f"n_tasks={n} 인데 공통 태스크는 {len(shared)}건뿐입니다.\n"
            f"  n_tasks 를 줄이시거나 번역을 늘리세요:\n"
            f"    python translate.py translate <태스크> -b {benchmark}")

    return random.Random(seed).sample(sorted(shared), n)


def stage_run_tasks(dst: Path, benchmark: str, lang: str, tasks: list[str]) -> Path:
    """실행에 쓸 태스크만 모은 트리를 만든다. 내용은 심볼릭 링크다.

    복사하지 않는 이유는 두 가지다. 태스크 하나가 수십 KB 라 실행마다
    복사하면 쌓이고, 무엇보다 복사본은 원본이 갱신돼도 조용히 그대로 남는다.
    """
    src = dataset_dir(benchmark, lang)
    dst.mkdir(parents=True, exist_ok=True)
    for t in tasks:
        link = dst / t
        if not link.exists():
            link.symlink_to(os.path.relpath(src / t, dst))
    return dst


# ─────────────────────────────────────────────────────────────
# 보호 정책
#
# 무엇을 압축할지가 아니라 **어디를 건드리지 않을지** 를 정한다. 같은
# 압축기로 보호 범위만 바꿔 비교하려고 arm 설정으로 열어 두었다.
#
#   protect: {keep_last: 0, system: true}   ← 공격적
#   protect: {keep_last: 2}                 ← 기본값과 같음
#
# 값을 주지 않은 항목은 compressors 의 기본값을 따른다.
# ─────────────────────────────────────────────────────────────
PROTECT_KEYS = {"keep_last", "min_chars", "system"}


def protect_args(protect: dict) -> list[str]:
    out: list[str] = []
    if "keep_last" in protect:
        out += ["--keep-last", str(int(protect["keep_last"]))]
    if "min_chars" in protect:
        out += ["--min-chars", str(int(protect["min_chars"]))]
    # system: true 는 "system 도 압축한다" 는 뜻이다. 기본은 보호다.
    if protect.get("system"):
        out += ["--compress-system"]
    return out


# ─────────────────────────────────────────────────────────────
# 기동
# ─────────────────────────────────────────────────────────────
def spawn(arm: dict, port: int, upstream: str, stats_dir: Path) -> subprocess.Popen:
    env = {**os.environ, **{k: str(v) for k, v in (arm.get("env") or {}).items()}}
    name = arm["name"]

    if arm["kind"] == "headroom":
        cmd = [
            "headroom", "proxy",
            "--port", str(port), "--host", "0.0.0.0",
            *HEADROOM_FIXED,
            *[str(a) for a in arm.get("args", [])],
            "--backend", "openai", "--openai-api-url", upstream,
        ]
    else:
        cmd = [
            sys.executable, str(HERE / "proxy.py"),
            "--compressor", str(arm["compressor"]),
            "--ratio", str(arm.get("ratio", 1.0)),
            "--port", str(port), "--host", "0.0.0.0",
            "--upstream", upstream,
            "--arm", name,
            "--stats", str(stats_dir / f"{name}.jsonl"),
            *protect_args(arm.get("protect") or {}),
        ]

    info(f"기동 [{name}] :{port}  {' '.join(cmd[:4])} …")
    log = (stats_dir / f"{name}.log").open("w", encoding="utf-8")
    return subprocess.Popen(cmd, env=env, stdout=log, stderr=subprocess.STDOUT)


def free_port(start: int, taken: set[int]) -> int:
    """start 이상에서 실제로 비어 있는 포트를 찾는다.

    다른 프로세스가 이미 쓰는 포트를 배정하면, 프록시는 조용히 죽고 pier 는
    엉뚱한 서버에 요청을 보낸다. 그러면 그 arm 전체가 무의미한 결과가 된다.
    """
    port = start
    while port < start + 200:
        if port not in taken:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                try:
                    s.bind(("0.0.0.0", port))
                except OSError:
                    port += 1
                    continue
            return port
        port += 1
    die(f"{start} 부터 사용 가능한 포트를 찾지 못했습니다")
    raise AssertionError  # unreachable


def wait_healthy(port: int, proc: subprocess.Popen, name: str, timeout: float = 300) -> None:
    """포트가 열릴 때까지 기다린다.

    압축 모델 로딩에 수십 초가 걸릴 수 있으므로 넉넉히 잡는다. 여기서 안 기다리면
    pier 가 먼저 요청을 보내 연결 거부가 나고, 그게 정확도 하락으로 잘못 집계된다.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            die(f"[{name}] 프로세스가 종료됐습니다 (exit={proc.returncode}). 로그를 확인하세요.")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=2):
                pass
        except OSError:
            time.sleep(1)
            continue
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=3) as r:
                info(f"준비됨 [{name}] {json.loads(r.read()).get('compressor', 'headroom')}")
                return
        except (urllib.error.HTTPError, urllib.error.URLError, OSError, json.JSONDecodeError):
            # headroom 은 /healthz 가 없을 수 있다. TCP 가 열렸으면 됐다.
            info(f"준비됨 [{name}] (포트 응답)")
            return
    die(f"[{name}] {timeout}초 안에 뜨지 않았습니다")


# ─────────────────────────────────────────────────────────────
# pier 설정 생성
# ─────────────────────────────────────────────────────────────
# mini-swe-agent 에 얹을 설정. pier 가 `-c <파일>` 로 넘겨 준다.
#
# step_limit 은 "한 과제에 모델을 몇 번까지 부를 수 있는가" 다. 압축 조건이
# 헤매기 시작하면 끝없이 늘어나므로 상한이 필요하다. 60 은 DeepSWE 기준
# 조건의 관측치(35 스텝)에 여유를 얹은 값이다 — 정상적으로 푸는 경로는
# 막지 않으면서, 헤매는 경로는 끊는다.
# trial 하나가 에이전트 단계에서 쓸 수 있는 최대 시간(초).
#
# 관측치: Terminal Bench 기준 조건이 60~80초, DeepSWE 기준 조건이 460초.
# 압축 조건은 3,900~9,300초까지 늘어났다. 1,800초는 정상 경로는 살리고
# 멈춘 경로만 끊는 선이다. DeepSWE 압축 조건 일부가 여기 걸리지만, 그건
# "예산 안에 못 끝냈다" 는 결과이지 측정 실패가 아니다.
AGENT_TIMEOUT_SEC = 1800.0

_STEP_LIMIT_YAML = "agent:\n  step_limit: 60\n"


def build_pier_config(spec: dict, arms: list[dict], public_host: str,
                      upstream: str, lang: str, task_dir: Path,
                      n_tasks: int) -> dict:
    agents = []
    for arm in arms:
        if arm["kind"] == "direct":
            base_url = upstream.rstrip("/") + "/v1"
        else:
            base_url = f"http://{public_host}:{arm['port']}/v1"
        arm["base_url"] = base_url
        agents.append({
            "name": spec.get("agent", "mini-swe-agent"),
            "model_name": spec["model"],
            # ★ 스텝 상한.
            #
            # 압축을 걸면 에이전트가 헤매면서 스텝이 늘어난다. DeepSWE
            # smoke 에서 기준 조건이 35 스텝에 끝난 과제를 압축 조건은
            # 80 스텝을 넘겨도 못 끝냈다(59분 경과). 상한이 없으면 한 trial
            # 이 몇 시간을 잡아먹고, 그동안 다른 조건이 밀린다.
            #
            # 상한은 **모든 조건에 동일하게** 건다. 압축 조건에만 걸면
            # 비교가 깨진다. 상한에 걸린 trial 은 실패로 집계되는데, 이는
            # "주어진 예산 안에 못 끝냈다" 는 뜻이라 정확도 지표로서
            # 타당하다 — 실제 운영에서도 예산은 유한하다.
            "kwargs": {"config_yaml": _STEP_LIMIT_YAML},
            # ★ trial 시간 상한.
            #
            # 태스크의 task.toml 에도 timeout_sec 가 있지만, 에이전트가 모델
            # 응답을 기다리며 멈춰 서면 그 상한이 걸리지 않는 경우가 있다.
            # 실제로 db-wal-recovery 한 건이 92분간 아무 출력 없이 멈춰
            # 파이프라인 전체를 막았다. 그동안 뒤의 롤아웃이 통째로 밀린다.
            #
            # 여기서 거는 상한은 **모든 조건에 동일**하다. 압축 조건에만
            # 걸면 비교가 깨진다. 상한에 걸린 trial 은 실패로 집계되는데,
            # 이는 "주어진 시간 안에 못 끝냈다" 는 뜻이라 정확도 지표로서
            # 타당하다 — 실제 운영에서도 시간은 유한하다.
            "override_timeout_sec": AGENT_TIMEOUT_SEC,
            "max_timeout_sec": AGENT_TIMEOUT_SEC,
            "env": {
                "OPENAI_API_KEY": "${OPENAI_API_KEY}",
                "OPENAI_BASE_URL": base_url,
                # 컨테이너 안에서 에이전트를 설치할 때 쓸 PyPI 주소.
                # 사내망은 files.pythonhosted.org 를 막고 있어서, 이걸 넘기지
                # 않으면 모든 trial 이 설치 단계에서 죽는다. 그 실패는
                # RuntimeError 로만 보여서 압축 탓으로 오해하기 쉽다.
                **({"UV_DEFAULT_INDEX": PYPI_INDEX,
                    "UV_INDEX_URL": PYPI_INDEX,
                    "PIP_INDEX_URL": PYPI_INDEX} if PYPI_INDEX else {}),
            },
        })

    ds = dict(spec["dataset"])
    # 태스크 선정은 launch.py 가 이미 끝냈다. 트리에 뽑힌 것만 들어 있으므로
    # 아래 키들은 pier 에게 넘길 필요가 없고, 모르는 키라 거부당할 수도 있다.
    for k in ("tasks", "sample_seed"):
        ds.pop(k, None)
    ds["path"] = str(task_dir.resolve())
    # 트리에 정확히 뽑힌 태스크만 있으므로 n 중 n 을 고르는 셈이다.
    # 시드는 기록을 위해 남기지만 결과에 영향을 주지 않는다.
    ds["n_tasks"] = n_tasks

    return {
        # 실행 폴더가 언어별로 갈리지만, pier 로그에서도 구분되게 해 둔다.
        "job_name": f"{spec['name']}-{lang}",
        "n_concurrent_trials": spec.get("n_concurrent_trials", 4),
        "n_attempts": spec.get("n_attempts", 3),
        "datasets": [ds],
        "environment": {"type": spec.get("environment", "docker")},
        "agents": agents,
        # ★ 채점 컨테이너에도 같은 미러를 준다.
        #
        # 에이전트만 챙기면 안 된다. Terminal Bench 태스크의 tests/test.sh 는
        # 거의 모두 `uvx -w pytest==8.4.1 ...` 로 시작하는데, 이게 막히면
        # 테스트가 **한 줄도 안 돌고** reward.txt 에 0 이 적힌다.
        #
        # 그러면 에이전트가 과제를 완벽히 풀어도 pass@1 이 0 으로 나온다.
        # 실제로 그렇게 24 trial 을 버렸다 — 표에는 "모든 arm 0%" 로 찍혀서
        # 벤치마크가 어려운 줄로만 보였다. 로그를 열어 보고서야
        # `tls handshake eof` 를 발견했다.
        "verifier": {
            "env": {"UV_DEFAULT_INDEX": PYPI_INDEX,
                    "UV_INDEX_URL": PYPI_INDEX,
                    "PIP_INDEX_URL": PYPI_INDEX},
        } if PYPI_INDEX else {},
    }


def main() -> int:
    p = argparse.ArgumentParser(description="실험 arm 기동 + pier 설정 생성")
    p.add_argument("experiment", type=Path)
    p.add_argument("--public-host", default=os.environ.get("PUBLIC_HOST"),
                   help="컨테이너에서 도달 가능한 호스트명 (localhost 불가)")
    p.add_argument("--upstream", default=os.environ.get("UPSTREAM_BASE_URL", "https://api.openai.com"))
    p.add_argument("--base-port", type=int, default=BASE_PORT)
    p.add_argument("--dry-run", action="store_true", help="프록시를 띄우지 않고 설정만 생성")
    args = p.parse_args()

    if not args.experiment.exists():
        die(f"실험 파일이 없습니다: {args.experiment}")

    spec = yaml.safe_load(args.experiment.read_text(encoding="utf-8"))
    validate(spec)

    public_host = args.public_host
    if not public_host:
        if args.dry_run:
            public_host = "<PUBLIC_HOST>"
        else:
            # 컨테이너 안의 localhost 는 컨테이너 자신이다. 반드시 실패한다.
            die(
                "--public-host 가 필요합니다.\n"
                "  컨테이너에서 프록시에 닿아야 하므로 localhost 는 쓸 수 없습니다.\n"
                "  도달 가능한 호스트명(사내 서버 DNS 또는 터널 도메인)을 지정하세요:\n"
                "    PUBLIC_HOST=benchmark-host python launch.py <실험파일>"
            )

    benchmark = spec["benchmark"]
    langs = spec.get("langs", ["en"])
    ds = spec["dataset"]
    tasks = pick_tasks(
        benchmark, langs,
        int(ds["n_tasks"]) if "n_tasks" in ds else None,
        int(ds["sample_seed"]) if "sample_seed" in ds else None,
        explicit=ds["tasks"] if "tasks" in ds else None)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = REPO / "runs" / "agentic-eval" / benchmark / spec["name"] / stamp
    out_dir.mkdir(parents=True, exist_ok=True)

    info(f"{benchmark} · 언어 {'/'.join(langs)} · 태스크 {len(tasks)}건")
    for t in tasks:
        print(f"    {t}")

    arms = [dict(a) for a in spec["arms"]]
    taken: set[int] = set()
    next_port = args.base_port
    for arm in arms:
        if arm["kind"] != "direct":
            # dry-run 은 포트를 실제로 점유하지 않으므로 순번만 매긴다.
            port = next_port if args.dry_run else free_port(next_port, taken)
            arm["port"] = port
            taken.add(port)
            next_port = port + 1

    procs: list[tuple[str, subprocess.Popen]] = []
    try:
        if not args.dry_run:
            for arm in arms:
                if arm["kind"] == "direct":
                    continue
                procs.append((arm["name"], spawn(arm, arm["port"], args.upstream, out_dir)))
            for arm in arms:
                if arm["kind"] == "direct":
                    continue
                proc = next(pr for nm, pr in procs if nm == arm["name"])
                wait_healthy(arm["port"], proc, arm["name"])

        cfg_paths = []
        for lang in langs:
            lang_dir = out_dir / lang
            task_dir = stage_run_tasks(lang_dir / "tasks", benchmark, lang, tasks)
            cfg = build_pier_config(spec, arms, public_host, args.upstream,
                                    lang, task_dir, len(tasks))
            cfg_path = lang_dir / "pier.yaml"
            cfg_path.write_text(
                yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True),
                encoding="utf-8")
            cfg_paths.append((lang, cfg_path))

        # 이 실행이 무슨 조건이었는지 한 파일로 남긴다. 폴더 이름만으로는
        # 태스크 목록까지 알 수 없다.
        (out_dir / "meta.json").write_text(json.dumps({
            "experiment": spec["name"],
            "benchmark": benchmark,
            "langs": langs,
            "model": spec["model"],
            "agent": spec.get("agent", "mini-swe-agent"),
            "n_attempts": spec.get("n_attempts", 3),
            "sample_seed": ds.get("sample_seed"),
            "task_source": ("전체" if ds.get("tasks") == [] else
                            "명시" if "tasks" in ds else "시드 추출"),
            "tasks": tasks,
            "started_at": stamp,
        }, ensure_ascii=False, indent=2), encoding="utf-8")

        # arm 순서 -> base_url 매핑. analyze.py 가 결과를 arm 에 되돌릴 때 쓴다.
        (out_dir / "arms.json").write_text(
            json.dumps([
                {"index": i, "name": a["name"], "kind": a["kind"],
                 "base_url": a["base_url"], "port": a.get("port"),
                 "ratio": a.get("ratio"), "compressor": a.get("compressor"),
                 "protect": a.get("protect"),
                 "args": a.get("args")}
                for i, a in enumerate(arms)
            ], ensure_ascii=False, indent=2), encoding="utf-8")

        # 실험 파일 원본 스냅샷 — 나중에 "무슨 조건이었지" 를 되짚을 유일한 근거
        (out_dir / "config.snapshot.yaml").write_text(
            args.experiment.read_text(encoding="utf-8"), encoding="utf-8")

        print()
        info(f"설정 생성: {out_dir.relative_to(REPO)}")
        for a in arms:
            print(f"    {a['name']:<24} {a['base_url']}")
        print()
        for lang, cfg_path in cfg_paths:
            print(f"  [{lang}] pier run --config {cfg_path}")
        print()
        info(f"결과 분석:  python analyze.py {out_dir}")

        if args.dry_run:
            return 0

        print()
        info("프록시 유지 중. 평가가 끝나면 Ctrl+C 로 종료하세요.")
        signal.pause()

    except KeyboardInterrupt:
        print()
    finally:
        for name, proc in procs:
            if proc.poll() is None:
                info(f"종료 [{name}]")
                proc.terminate()
        for _, proc in procs:
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
