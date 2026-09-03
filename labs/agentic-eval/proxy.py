#!/usr/bin/env python3
"""OpenAI 호환 압축 프록시.

에이전트와 모델 API 사이에 끼어 `messages` 를 압축한 뒤 그대로 전달한다.
에이전트 입장에선 평범한 OpenAI 호환 엔드포인트로 보이므로 deep-swe 도 pier 도
수정할 필요가 없다.

    에이전트 ──▶ proxy.py ──▶ 모델 API
                   └ compressors/<name>.compress()

사용::

    python proxy.py --compressor recomp --ratio 0.5 --port 8802 \
        --upstream https://api.openai.com --arm recomp-r0.5

보통은 직접 실행하지 않고 launch.py 가 띄운다.

의존성 없음(stdlib 전용). 사내망에서 추가 설치 없이 바로 동작해야 하기 때문이다.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import compressors  # noqa: E402

# 프록시가 소비하거나 재계산해야 하는 헤더. 그대로 넘기면 응답이 깨진다.
HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "content-length",
    "content-encoding", "host",
}

_stats_lock = threading.Lock()
_token_lock = threading.Lock()
_token_cache: dict = {"value": None, "until": 0.0}

# Entra ID 토큰을 받을 대상. Azure OpenAI / Foundry 는 이 스코프를 씁니다.
TOKEN_SCOPE = os.environ.get(
    "AZURE_TOKEN_SCOPE", "https://cognitiveservices.azure.com/.default")


def _fresh_token() -> str | None:
    """`az` 로 Entra ID 토큰을 받아 온다. 못 받으면 None.

    30초 동안 캐시합니다. 401 이 여러 요청에서 동시에 터지면 `az` 를 그만큼
    부르게 되는데, 한 번에 1~2초씩 걸려 롤아웃이 눈에 띄게 느려집니다.
    """
    with _token_lock:
        if _token_cache["value"] and time.time() < _token_cache["until"]:
            return _token_cache["value"]
        try:
            import subprocess
            out = subprocess.run(
                ["az", "account", "get-access-token", "--scope", TOKEN_SCOPE,
                 "--query", "accessToken", "-o", "tsv"],
                capture_output=True, text=True, timeout=60)
        except Exception:  # noqa: BLE001
            return None
        token = out.stdout.strip()
        if out.returncode != 0 or not token:
            return None
        _token_cache.update(value=token, until=time.time() + 30)
        return token



class Config:
    compressor_name = "none"
    ratio = 1.0
    policy: dict = {}
    upstream = "https://api.openai.com"
    arm = "unnamed"
    stats_path: Path | None = None
    compress = staticmethod(compressors.get("none"))
    timeout = 600.0


def _record(row: dict) -> None:
    if Config.stats_path is None:
        return
    row["ts"] = time.time()
    row["arm"] = Config.arm
    with _stats_lock:
        with Config.stats_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _chars(messages: list[dict]) -> int:
    return sum(len(m["content"]) for m in messages if isinstance(m.get("content"), str))


# ─────────────────────────────────────────────────────────────
# 요청 본문 → 압축 슬롯
#
# ★ 이 어댑터가 없으면 압축이 **한 글자도 걸리지 않습니다.**
#
# 오래 그런 상태였습니다. 프록시는 `/chat/completions` 의 `messages` 만 보고
# 있었는데, pier 의 mini-swe-agent 는 `model.model_class=litellm_response` 로
# 떠서 `/v1/responses` 를 부릅니다. 그래서 압축 arm 이 사실은 baseline 과
# 똑같은 프롬프트를 보내고 있었고, 로그에는 `usage` 만 남고 `compress` 는
# 하나도 남지 않았습니다. 결과 표만 봐서는 "압축해도 별 차이 없네" 로
# 읽히기 때문에 특히 위험합니다.
#
# 두 API 의 모양이 다릅니다.
#
#   chat/completions   {"messages": [{"role","content": str}]}
#   responses          {"instructions": str,
#                       "input": str | [{"role","content": str | [파트…]},
#                                       {"type":"function_call_output","output":…}]}
#
# 압축기의 계약은 `list[{"role","content": str}]` 하나뿐이라, 여기서 한 번
# 펴 두면 압축기는 어느 API 인지 몰라도 됩니다.
# ─────────────────────────────────────────────────────────────
class _Slot:
    """본문 안의 '압축할 수 있는 문자열' 한 자리."""

    __slots__ = ("role", "text", "_set")

    def __init__(self, role: str, text: str, setter):
        self.role, self.text, self._set = role, text, setter

    def write(self, value: str) -> None:
        if isinstance(value, str):
            self._set(value)


def _slots(payload: dict) -> list[_Slot]:
    out: list[_Slot] = []

    msgs = payload.get("messages")
    if isinstance(msgs, list) and msgs:
        for m in msgs:
            if isinstance(m, dict) and isinstance(m.get("content"), str):
                out.append(_Slot(m.get("role", "user"), m["content"],
                                 lambda v, m=m: m.__setitem__("content", v)))
        return out

    if payload.get("input") is None and "instructions" not in payload:
        return out

    # instructions 는 Responses API 의 system 프롬프트 자리입니다.
    # role 을 system 으로 넘겨야 skip_system 정책이 여기에도 걸립니다.
    if isinstance(payload.get("instructions"), str):
        out.append(_Slot("system", payload["instructions"],
                         lambda v: payload.__setitem__("instructions", v)))

    inp = payload.get("input")
    if isinstance(inp, str):
        out.append(_Slot("user", inp, lambda v: payload.__setitem__("input", v)))
        return out
    if not isinstance(inp, list):
        return out

    for item in inp:
        if not isinstance(item, dict):
            continue
        role = item.get("role") or _ROLE_BY_TYPE.get(item.get("type", ""), "user")
        content = item.get("content")

        if isinstance(content, str):
            out.append(_Slot(role, content,
                             lambda v, i=item: i.__setitem__("content", v)))
        elif isinstance(content, list):
            for part in content:
                # 텍스트 파트만 다룹니다. 이미지·오디오는 문자열이 아니라
                # 압축기에 넘길 수 없고, 넘겨도 뜻이 없습니다.
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    out.append(_Slot(role, part["text"],
                                     lambda v, p=part: p.__setitem__("text", v)))
        # 도구 실행 결과. 에이전트 컨텍스트에서 가장 크게 자라는 자리라
        # 압축 효과가 여기서 제일 크게 납니다.
        elif isinstance(item.get("output"), str):
            out.append(_Slot(role, item["output"],
                             lambda v, i=item: i.__setitem__("output", v)))
    return out


_ROLE_BY_TYPE = {
    "function_call_output": "tool",
    "function_call": "assistant",
    "reasoning": "assistant",
    "message": "user",
}



class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "token-compression-proxy/1.0"

    def log_message(self, fmt, *args):  # noqa: A003
        sys.stderr.write(f"[{Config.arm}] {fmt % args}\n")

    # ── 라우팅 ────────────────────────────────────────────────
    def do_GET(self):  # noqa: N802
        if self.path.rstrip("/") in ("/healthz", "/health"):
            body = json.dumps({
                "status": "ok",
                "arm": Config.arm,
                "compressor": Config.compressor_name,
                "policy": Config.policy,
                "ratio": Config.ratio,
            }).encode()
            self._respond(200, {"Content-Type": "application/json"}, body)
            return
        self._forward(b"")

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""

        if body and (self.path.endswith("/chat/completions")
                     or self.path.rstrip("/").endswith("/responses")):
            body = self._compress_body(body)

        self._forward(body)

    def do_DELETE(self):  # noqa: N802
        self._forward(b"")

    # ── 압축 ──────────────────────────────────────────────────
    def _compress_body(self, body: bytes) -> bytes:
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            return body  # 우리가 못 읽는 형식이면 손대지 않는다

        # Chat Completions 는 messages, Responses 는 input 을 씁니다.
        # 둘의 모양이 다르므로 슬롯으로 한 번 펴서 같게 다룹니다.
        slots = _slots(payload)
        if not slots:
            return body

        messages = [{"role": s.role, "content": s.text} for s in slots]
        before = _chars(messages)
        t0 = time.perf_counter()
        try:
            compressed = Config.compress(messages, Config.ratio)
        except Exception as e:  # noqa: BLE001
            # 압축기 장애가 API 오류로 번지면 그 trial 은 reward 0 이 되고,
            # 집계에서 "압축 때문에 실패" 로 잘못 읽힌다. 원문으로 통과시킨다.
            self.log_message("압축 실패, 원문 전달: %s: %s", type(e).__name__, e)
            _record({"event": "compress_error", "error": f"{type(e).__name__}: {e}"})
            return body

        if len(compressed) != len(slots):
            # 압축기가 메시지 개수를 바꾸면 어느 슬롯에 되돌릴지 알 수 없습니다.
            # 지금 압축기들은 그러지 않지만, 조용히 깨지는 것보다 낫습니다.
            self.log_message("압축기가 메시지 수를 바꿨습니다(%d→%d). 원문 전달",
                             len(slots), len(compressed))
            _record({"event": "compress_error", "error": "message count changed"})
            return body

        after = _chars(compressed)
        for slot, msg in zip(slots, compressed):
            slot.write(msg.get("content", slot.text))

        _record({
            "event": "compress",
            "model": payload.get("model"),
            "endpoint": "responses" if payload.get("input") is not None else "chat",
            "n_messages": len(slots),
            "chars_before": before,
            "chars_after": after,
            "reduction": round(1 - after / before, 4) if before else 0.0,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1),
        })
        return json.dumps(payload).encode("utf-8")


    # ── 전달 ──────────────────────────────────────────────────
    def _forward(self, body: bytes) -> None:
        url = Config.upstream.rstrip("/") + self.path

        headers = {
            k: v for k, v in self.headers.items()
            if k.lower() not in HOP_BY_HOP
        }
        if body:
            headers["Content-Length"] = str(len(body))

        try:
            resp = self._send(url, body, headers)
        except urllib.error.HTTPError as e:
            # 업스트림의 상태코드·본문을 그대로 보존한다. 여기서 200 으로
            # 바꾸면 429/401 을 디버깅할 수 없게 된다.
            payload = e.read()
            self._respond(e.code, self._clean(e.headers.items()), payload)
            return
        except Exception as e:  # noqa: BLE001
            self.log_message("업스트림 오류: %s: %s", type(e).__name__, e)
            _record({"event": "upstream_error", "error": f"{type(e).__name__}: {e}"})
            self._respond(502, {"Content-Type": "application/json"},
                          json.dumps({"error": {"message": str(e), "type": "proxy_error"}}).encode())
            return

        with resp:
            out_headers = self._clean(resp.headers.items())
            ctype = resp.headers.get("Content-Type", "")

            if "text/event-stream" in ctype:
                self._stream(resp, out_headers)
            else:
                payload = resp.read()
                self._record_usage(payload, ctype)
                self._respond(resp.status, out_headers, payload)

    def _send(self, url: str, body: bytes, headers: dict):
        """업스트림에 보낸다. 401 이면 토큰을 새로 받아 **한 번만** 다시 보낸다.

        왜 필요한가. 에이전트는 컨테이너가 뜰 때 받은 토큰 하나를 끝까지 씁니다.
        Entra ID 토큰은 한 시간 남짓이라, 롤아웃이 길어지면 도중에 만료됩니다.
        만료가 아니어도 Azure 쪽에서 간헐적으로 401 이 돌아올 때가 있습니다.

        그런데 mini-swe-agent 는 `--exit-immediately` 로 돌아서 **한 번의 401 에
        루프 전체가 끝납니다.** 실제로 그렇게 죽은 적이 있습니다.

            200 200 200 200 200 200  401  ← 여기서 33 스텝짜리 롤아웃이 중단

        그러면 그 실패가 압축 탓인지 인증 탓인지 결과만 보고는 알 수 없습니다.
        그래서 프록시가 대신 토큰을 새로 받아 재시도합니다. 프록시는 호스트에서
        돌아 `az` 를 쓸 수 있지만 컨테이너 안 에이전트는 그럴 수 없습니다.
        여기 두는 게 유일하게 가능한 자리입니다.

        재발급 수단이 없으면 (az 가 없거나 실패) 원래 401 을 그대로 올립니다.
        조용히 200 으로 바꾸면 인증 문제를 영영 못 보게 됩니다.
        """
        try:
            return urllib.request.urlopen(
                urllib.request.Request(url, data=body or None,
                                       headers=headers, method=self.command),
                timeout=Config.timeout)
        except urllib.error.HTTPError as e:
            if e.code != 401 or "authorization" not in {k.lower() for k in headers}:
                raise
            token = _fresh_token()
            if not token:
                raise
            e.read()                      # 소켓을 닫아 준다
            retry = dict(headers)
            for k in list(retry):
                if k.lower() == "authorization":
                    retry[k] = f"Bearer {token}"
            self.log_message("401 → 토큰 재발급 후 재시도")
            _record({"event": "auth_retry"})
            return urllib.request.urlopen(
                urllib.request.Request(url, data=body or None,
                                       headers=retry, method=self.command),
                timeout=Config.timeout)


    def _record_usage(self, payload: bytes, ctype: str) -> None:
        if "json" not in ctype:
            return
        try:
            usage = json.loads(payload).get("usage")
        except Exception:  # noqa: BLE001
            return
        if isinstance(usage, dict):
            _record({"event": "usage", **usage})

    def _stream(self, resp, headers: dict) -> None:
        headers["Transfer-Encoding"] = "chunked"
        self.send_response(resp.status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.end_headers()
        try:
            while chunk := resp.read(8192):
                self.wfile.write(f"{len(chunk):X}\r\n".encode())
                self.wfile.write(chunk)
                self.wfile.write(b"\r\n")
                self.wfile.flush()
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass  # 클라이언트가 먼저 끊음

    @staticmethod
    def _clean(items) -> dict:
        return {k: v for k, v in items if k.lower() not in HOP_BY_HOP}

    def _respond(self, status: int, headers: dict, body: bytes) -> None:
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass


def main() -> int:
    p = argparse.ArgumentParser(description="OpenAI 호환 압축 프록시")
    p.add_argument("--compressor", default="none", choices=list(compressors.REGISTRY))
    p.add_argument("--ratio", type=float, default=1.0, help="유지 비율 (0.8 = 80%% 유지)")
    p.add_argument("--port", type=int, default=8800)
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--upstream", default=os.environ.get("UPSTREAM_BASE_URL", "https://api.openai.com"))
    p.add_argument("--arm", default="unnamed", help="실험 조건 이름 (로그 식별용)")
    p.add_argument("--stats", type=Path, default=None, help="통계 jsonl 경로")
    p.add_argument("--timeout", type=float, default=600.0)

    # ── 보호 정책 ─────────────────────────────────────────────
    # 무엇을 압축할지가 아니라 **어디를 건드리지 않을지** 를 정한다.
    # 같은 압축기로 보호 범위만 바꿔 비교하려고 열어 두었다.
    g = p.add_argument_group("보호 정책")
    g.add_argument("--keep-last", type=int, default=None,
                   help="마지막 N개 메시지를 원문 유지 (0 이면 보호 안 함)")
    g.add_argument("--min-chars", type=int, default=None,
                   help="이보다 짧은 메시지는 건드리지 않음")
    g.add_argument("--compress-system", action="store_true",
                   help="system 프롬프트도 압축 (기본은 보호)")
    args = p.parse_args()

    if not 0 < args.ratio <= 1:
        p.error(f"--ratio 는 (0, 1] 이어야 합니다: {args.ratio}")
    if args.keep_last is not None and args.keep_last < 0:
        p.error(f"--keep-last 는 0 이상이어야 합니다: {args.keep_last}")
    if args.min_chars is not None and args.min_chars < 0:
        p.error(f"--min-chars 는 0 이상이어야 합니다: {args.min_chars}")

    policy = compressors.set_policy(
        keep_last=args.keep_last,
        min_chars=args.min_chars,
        skip_system=False if args.compress_system else None)

    Config.policy = policy
    Config.compressor_name = args.compressor
    Config.ratio = args.ratio
    Config.upstream = args.upstream
    Config.arm = args.arm
    Config.timeout = args.timeout
    if args.stats:
        args.stats.parent.mkdir(parents=True, exist_ok=True)
        Config.stats_path = args.stats

    # 모델 로딩을 여기서 끝낸다. 첫 요청 때 로딩하면 수십 초가 걸리고,
    # 그게 에이전트 타임아웃으로 잡혀 압축 품질과 무관한 실패가 된다.
    print(f"[{args.arm}] 압축기 로딩: {args.compressor} (ratio={args.ratio})", flush=True)
    Config.compress = compressors.get(args.compressor)
    Config.compress([{"role": "user", "content": "warmup " * 200}], args.ratio)

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.daemon_threads = True
    print(f"[{args.arm}] http://{args.host}:{args.port}/v1 -> {args.upstream}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
