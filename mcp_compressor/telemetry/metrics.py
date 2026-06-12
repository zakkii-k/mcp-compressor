"""メトリクス送信モジュール。

外部パッケージ不要。stdlib の urllib で telemetry/server.py に JSON を POST する。
サーバーが起動していない場合・送信失敗は全て無視し、メイン処理を止めない。
"""

from __future__ import annotations

import json
import threading
import time
import urllib.request

_endpoint: str | None = None
_enabled = False


def init(endpoint: str, service_name: str = "") -> None:
    global _endpoint, _enabled
    _endpoint = endpoint.rstrip("/")
    _enabled = True


def _send(payload: dict) -> None:
    """daemon スレッドで fire-and-forget 送信する。"""
    ep = _endpoint

    def _post() -> None:
        try:
            data = json.dumps(payload, ensure_ascii=False).encode()
            req = urllib.request.Request(
                f"{ep}/ingest",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=2)
        except Exception:
            pass

    threading.Thread(target=_post, daemon=True).start()


def record_request(
    chars_in: int,
    chars_out: int,
    tokens_in: int,
    tokens_out: int,
    modified: bool,
    server: str,
    tool: str,
) -> None:
    if not _enabled:
        return
    _send({
        "type":       "request",
        "ts":         int(time.time() * 1000),
        "chars_in":   chars_in,
        "chars_out":  chars_out,
        "tokens_in":  tokens_in,
        "tokens_out": tokens_out,
        "modified":   modified,
        "server":     server,
        "tool":       tool,
    })


def record_stage(
    stage: str,
    chars_in: int,
    chars_out: int,
    elapsed_ms: float,
) -> None:
    if not _enabled:
        return
    _send({
        "type":        "stage",
        "ts":          int(time.time() * 1000),
        "stage":       stage,
        "chars_in":    chars_in,
        "chars_out":   chars_out,
        "duration_ms": elapsed_ms,
    })
