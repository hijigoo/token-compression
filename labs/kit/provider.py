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
                 cache: bool = True, api_version: str = "preview"):
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
        if self.cache_path and self.cache_path.exists():
            try:
                self._mem = json.loads(self.cache_path.read_text(encoding="utf-8"))
            except Exception:
                self._mem = {}

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
                "cached_entries": len(self._mem)}
