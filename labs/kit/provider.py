"""API 토큰 실측.

tiktoken 은 근사치이고, **과금 기준은 API 가 돌려주는 usage** 입니다.
차이는 두 군데서 생깁니다.

  1. 메시지 포맷 오버헤드 — 역할 구분자 등이 더해집니다 (모델당 고정, 보통 +6)
  2. 토크나이저 자체 — 배포 모델과 tiktoken 인코딩이 다를 수 있습니다

정확하지만 대가가 있습니다.

  - 텍스트 하나당 API 호출 1회. 케이스 N건이면 압축 전후로 2N 회입니다
  - 스윕(rate 10단계)을 돌리면 그만큼 곱해집니다

그래서 **캐시가 필수**입니다. 같은 텍스트는 한 번만 부르고 디스크에 남깁니다.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, Optional

SCOPE = "https://cognitiveservices.azure.com/.default"
CACHE_DIR = Path(__file__).resolve().parent / ".cache"


def _find_az() -> str:
    for c in (os.environ.get("AZ_CLI"), shutil.which("az"),
              "/opt/homebrew/bin/az", "/usr/local/bin/az",
              str(Path.home() / ".local/bin/az")):
        if c and Path(c).exists():
            return c
    raise RuntimeError(
        "az CLI 를 찾지 못했습니다.\n"
        "  · .env 에 AZ_CLI=/전체/경로/az 를 넣거나\n"
        "  · AZURE_OPENAI_API_KEY 를 설정하세요"
    )


def _mask(url: str) -> str:
    """오류 메시지에 리소스 이름이 그대로 남지 않게 가립니다."""
    try:
        scheme, rest = url.split("://", 1)
        host = rest.split("/")[0]
        name, _, domain = host.partition(".")
        return f"{scheme}://{name[:5]}***.{domain}"
    except ValueError:
        return "***"


def _headers() -> Dict[str, str]:
    key = os.environ.get("AZURE_OPENAI_API_KEY")
    if key:
        return {"Content-Type": "application/json", "api-key": key}
    r = subprocess.run([_find_az(), "account", "get-access-token",
                        "--scope", SCOPE, "-o", "json"],
                       capture_output=True, text=True, timeout=90)
    if r.returncode != 0:
        raise RuntimeError(f"az 토큰 발급 실패 — `az login` 이 필요할 수 있습니다.\n"
                           f"{r.stderr.strip()[:300]}")
    return {"Content-Type": "application/json",
            "Authorization": "Bearer " + json.loads(r.stdout)["accessToken"]}


class ApiCounter:
    """API 로 input_tokens 를 실측합니다. 결과는 디스크에 캐시합니다.

    주의: 반환값에는 **메시지 포맷 오버헤드가 포함**됩니다.
    압축 전후를 같은 방식으로 재므로 비율 비교에는 문제가 없지만,
    '순수 텍스트 토큰 수' 와는 상수만큼 차이가 납니다.
    """

    backend_name = "api"

    def __init__(self, deployment: str, endpoint: Optional[str] = None,
                 cache: bool = True, api_version: str = "preview",
                 refresh: bool = False):
        self.deployment = deployment
        self.endpoint = (endpoint or os.environ.get("AZURE_OPENAI_ENDPOINT") or "").rstrip("/")
        if not self.endpoint:
            raise RuntimeError("AZURE_OPENAI_ENDPOINT 가 없습니다 (.env 확인)")
        self.api_version = api_version
        self._headers: Optional[Dict[str, str]] = None
        self.calls = 0
        self.hits = 0

        self.cache_path = CACHE_DIR / f"tokens-{deployment}.json" if cache else None
        self._mem: Dict[str, int] = {}
        if self.cache_path and self.cache_path.exists() and not refresh:
            try:
                self._mem = json.loads(self.cache_path.read_text(encoding="utf-8"))
            except Exception:
                self._mem = {}
        # 시작 시점에 몇 건을 들고 있었는지 남깁니다. "이번 실행에서 호출이
        # 0회" 인 것과 "애초에 API 를 안 쓴다" 를 구분해서 보여주려는 것입니다.
        self.preloaded = len(self._mem)

    @property
    def backend(self) -> str:
        return f"api:{self.deployment}"

    def _key(self, text: str) -> str:
        return hashlib.sha256(f"{self.deployment}\x00{text}".encode()).hexdigest()[:24]

    def __call__(self, text: str, model: Optional[str] = None) -> int:
        if not text:
            return 0
        k = self._key(text)
        if k in self._mem:
            self.hits += 1
            return self._mem[k]

        req = urllib.request.Request(
            f"{self.endpoint}/openai/v1/responses?api-version={self.api_version}",
            data=json.dumps({"model": self.deployment, "input": text,
                             "max_output_tokens": 16}).encode(),
            headers=self._auth(), method="POST")
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                d = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            raise RuntimeError(
                f"토큰 실측 실패 HTTP {e.code}: {e.read().decode('utf-8','replace')[:300]}"
            ) from e
        except urllib.error.URLError as e:
            raise RuntimeError(
                f"엔드포인트에 연결하지 못했습니다 ({e.reason}).\n"
                f"  대상: {_mask(self.endpoint)}\n"
                f"  .env 의 AZURE_OPENAI_ENDPOINT 를 확인해 주세요.\n"
                f"  네트워크 없이 돌리시려면 tokenizer.mode 를 local 로 바꾸시면 됩니다."
            ) from e

        n = int((d.get("usage") or {}).get("input_tokens") or 0)
        self.calls += 1
        self._mem[k] = n
        return n

    def _auth(self) -> Dict[str, str]:
        if self._headers is None:
            self._headers = _headers()
        return self._headers

    def save(self) -> None:
        if not self.cache_path:
            return
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(self._mem, ensure_ascii=False),
                                   encoding="utf-8")

    def stats(self) -> Dict[str, int]:
        return {"api_calls": self.calls, "cache_hits": self.hits,
                "cached_entries": len(self._mem), "preloaded": self.preloaded}

    def describe(self) -> str:
        """실행 뒤 무슨 일이 있었는지 한 줄로 설명합니다.

        "API 호출 0회" 만 찍으면 API 를 아예 안 쓴 것처럼 보입니다.
        실제로는 이전 실행에서 받아 둔 값을 재사용한 것이므로 구분해서
        보여줍니다.
        """
        if self.calls and self.hits:
            return (f"API 실측 — 새로 호출 {self.calls}회, "
                    f"캐시 재사용 {self.hits}회 (같은 텍스트)")
        if self.calls:
            return f"API 실측 — 새로 호출 {self.calls}회"
        if self.hits:
            return (f"API 실측값 — 이번 실행은 호출 0회입니다. "
                    f"이전 실행에서 받아 둔 {self.preloaded}건을 {self.hits}회 재사용했습니다")
        return "API 실측 — 잰 텍스트가 없습니다"


def complete(prompt: str, deployment: str, endpoint: Optional[str] = None,
             max_output_tokens: int = 2048, api_version: str = "preview",
             timeout: int = 300) -> tuple:
    """Responses API 로 텍스트를 받습니다. (본문, usage) 를 돌려줍니다.

    랩마다 HTTP 코드를 복사하지 않으려고 여기 둡니다. 인증은 위와 같습니다
    (API 키가 있으면 키, 없으면 az CLI 의 Entra ID 토큰).

    ⚠️ 추론 모델은 출력 토큰을 생각하는 데도 씁니다. `max_output_tokens` 가
    빠듯하면 `status=incomplete` 로 **빈 본문**이 돌아옵니다. 조용히 빈
    문자열을 반환하면 "압축률 100%" 라는 엉터리 결과가 나오므로 예외를 냅니다.
    """
    ep = (endpoint or os.environ.get("AZURE_OPENAI_ENDPOINT") or "").rstrip("/")
    if not ep:
        raise RuntimeError("AZURE_OPENAI_ENDPOINT 가 없습니다 (.env 확인)")

    req = urllib.request.Request(
        f"{ep}/openai/v1/responses?api-version={api_version}",
        data=json.dumps({"model": deployment, "input": prompt,
                         "max_output_tokens": max_output_tokens}).encode(),
        headers=_headers(), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError(
            f"호출 실패 HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}"
        ) from e

    text = d.get("output_text") or ""
    if not text:
        for item in d.get("output") or []:
            for c in item.get("content") or []:
                if c.get("type") == "output_text":
                    text += c.get("text") or ""

    usage = d.get("usage") or {}
    if not text.strip():
        raise RuntimeError(
            f"본문이 비어 있습니다 (status={d.get('status')}, "
            f"reason={(d.get('incomplete_details') or {}).get('reason')}). "
            f"max_output_tokens 를 늘려보세요 — 추론 모델은 생각하는 데도 "
            f"출력 토큰을 씁니다.")
    return text.strip(), usage
