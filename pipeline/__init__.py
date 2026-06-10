"""MCPレスポンス処理パイプライン。

各プロセッサが順に実行され、テキストを段階的に圧縮・要約する。
"""

from .base import BaseProcessor
from .json_compressor import JSONCompressor
from .json_table_converter import JSONTableConverter
from .toon_converter import ToonConverter
from .log_compressor import LogCompressor
from .log_deduplicator import LogDeduplicator
from .llm_summarizer import LLMSummarizer


class Pipeline:
    def __init__(self, processors: list[BaseProcessor]) -> None:
        self.processors = processors

    def process(self, text: str) -> tuple[str, bool]:
        """全プロセッサを順に適用する。戻り値: (最終テキスト, いずれかで変更されたか)"""
        any_modified = False
        current = text
        for processor in self.processors:
            result, modified = processor.process(current)
            if modified:
                current = result
                any_modified = True
        return current, any_modified


def build_pipeline(config: dict) -> Pipeline:
    """設定からパイプラインを構築する。"""
    enabled: list[str] = config.get("pipeline", [
        "toon_converter",
        "log_deduplicator",
        "log_compressor",
        "llm_summarizer",
    ])
    processors: list[BaseProcessor] = []

    if "toon_converter" in enabled:
        processors.append(ToonConverter())

    if "json_compressor" in enabled:
        processors.append(JSONCompressor())

    if "json_table_converter" in enabled:
        processors.append(JSONTableConverter())

    if "log_deduplicator" in enabled:
        processors.append(LogDeduplicator())

    if "log_compressor" in enabled:
        log_cfg = config.get("log_compressor", {})
        processors.append(LogCompressor(
            max_lines=log_cfg.get("max_lines", 50),
            keep_errors=log_cfg.get("keep_errors", True),
        ))

    if "llm_summarizer" in enabled:
        processors.append(LLMSummarizer(
            threshold_chars=config.get("threshold_chars", 5000),
            model=config.get("model", "qwen2.5:3b"),
            ollama_url=config.get("ollama_url", "http://localhost:11434"),
            originals_dir=config.get("originals_dir", "originals"),
        ))

    return Pipeline(processors)


__all__ = [
    "Pipeline", "build_pipeline",
    "BaseProcessor",
    "JSONCompressor", "JSONTableConverter", "ToonConverter",
    "LogCompressor", "LogDeduplicator",
    "LLMSummarizer",
]
