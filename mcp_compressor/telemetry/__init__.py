"""テレメトリモジュール。

config に telemetry.enabled: true があれば telemetry/server.py へのデータ送信を開始する。
外部パッケージ不要・外部への通信なし。
"""

from __future__ import annotations

from . import metrics
from . import token_counter


def setup(config: dict) -> None:
    tel = config.get("telemetry", {})
    if not tel.get("enabled", False):
        return
    endpoint = tel.get("endpoint", "http://localhost:4318")
    metrics.init(endpoint)


__all__ = ["setup", "metrics", "token_counter"]
