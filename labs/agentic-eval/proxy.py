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

        if self.path.endswith("/chat/completions") and body:
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

        messages = payload.get("messages")
        if not isinstance(messages, list) or not messages:
            return body

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

        after = _chars(compressed)
        payload["messages"] = compressed

        _record({
            "event": "compress",
            "model": payload.get("model"),
            "n_messages": len(messages),
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

        req = urllib.request.Request(
            url, data=body or None, headers=headers, method=self.command
        )

        try:
            resp = urllib.request.urlopen(req, timeout=Config.timeout)
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
