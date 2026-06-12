"""OTel メトリクス計装。

opentelemetry パッケージが未インストールの場合は全操作が no-op になる。
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

# OTel が使えるかどうかを起動時に1回だけ確認する
_meter = None
_instruments: dict = {}
_enabled = False


def init(endpoint: str, service_name: str) -> None:
    """OTel SDK を初期化する。失敗しても例外を出さず no-op になる。"""
    global _meter, _enabled

    try:
        from opentelemetry import metrics
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter

        resource = Resource.create({"service.name": service_name})
        exporter = OTLPMetricExporter(endpoint=f"{endpoint.rstrip('/')}/v1/metrics")
        reader = PeriodicExportingMetricReader(exporter, export_interval_millis=5000)
        provider = MeterProvider(resource=resource, metric_readers=[reader])
        metrics.set_meter_provider(provider)
        _meter = metrics.get_meter("mcp-compressor")
        _build_instruments()
        _enabled = True
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("OTel 初期化失敗（no-op で続行）: %s", e)


def _build_instruments() -> None:
    global _instruments
    _instruments = {
        "chars_in":    _meter.create_histogram("mcp_compressor.chars.input",    unit="chars",  description="圧縮前の文字数"),
        "chars_out":   _meter.create_histogram("mcp_compressor.chars.output",   unit="chars",  description="圧縮後の文字数"),
        "tokens_in":   _meter.create_histogram("mcp_compressor.tokens.input",   unit="tokens", description="圧縮前の推定トークン数"),
        "tokens_out":  _meter.create_histogram("mcp_compressor.tokens.output",  unit="tokens", description="圧縮後の推定トークン数"),
        "requests":    _meter.create_counter(  "mcp_compressor.requests.total",               description="処理したリクエスト数"),
        "stage_in":    _meter.create_histogram("mcp_compressor.stage.chars.input",  unit="chars", description="ステージ処理前の文字数"),
        "stage_out":   _meter.create_histogram("mcp_compressor.stage.chars.output", unit="chars", description="ステージ処理後の文字数"),
        "stage_ms":    _meter.create_histogram("mcp_compressor.stage.duration",     unit="ms",    description="ステージ処理時間"),
    }


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
    attrs = {"server": server, "tool": tool, "modified": str(modified).lower()}
    _instruments["chars_in"].record(chars_in,   attrs)
    _instruments["chars_out"].record(chars_out,  attrs)
    _instruments["tokens_in"].record(tokens_in,  attrs)
    _instruments["tokens_out"].record(tokens_out, attrs)
    _instruments["requests"].add(1, attrs)


def record_stage(
    stage: str,
    chars_in: int,
    chars_out: int,
    elapsed_ms: float,
) -> None:
    if not _enabled:
        return
    attrs = {"stage": stage}
    _instruments["stage_in"].record(chars_in,    attrs)
    _instruments["stage_out"].record(chars_out,   attrs)
    _instruments["stage_ms"].record(elapsed_ms,   attrs)


@contextmanager
def measure_stage(stage_name: str, text_in: str):
    """with ブロックで囲むとステージのメトリクスを自動記録する。"""
    t0 = time.monotonic()
    result_holder: list[str] = []
    yield result_holder
    if _enabled and result_holder:
        text_out = result_holder[0]
        elapsed = (time.monotonic() - t0) * 1000
        record_stage(stage_name, len(text_in), len(text_out), elapsed)
