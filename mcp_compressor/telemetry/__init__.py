"""テレメトリモジュール。

config に telemetry.enabled: true があれば OTel SDK を初期化する。
opentelemetry パッケージが未インストールでも動作する（no-op）。
"""

from __future__ import annotations

from . import metrics
from . import token_counter


def setup(config: dict) -> None:
    tel = config.get("telemetry", {})
    if not tel.get("enabled", False):
        return
    endpoint     = tel.get("endpoint",     "http://localhost:4318")
    service_name = tel.get("service_name", "mcp-compressor")
    metrics.init(endpoint, service_name)


__all__ = ["setup", "metrics", "token_counter"]
