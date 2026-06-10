"""JSON レスポンスを TOON 形式に変換するプロセッサ。

TOON (Token-Oriented Object Notation) はLLM向けに設計されたコンパクト形式。
- オブジェクト配列: ヘッダー1行 + CSV 形式の行
- ネストオブジェクト: インデントベースの表現
- JSON より 30–64% 削減、Markdown テーブルよりもさらにコンパクト

https://toonformat.dev/
"""

import json
import logging

from .base import BaseProcessor

logger = logging.getLogger(__name__)

try:
    import toon as _toon_lib
    _TOON_AVAILABLE = True
except ImportError:
    _TOON_AVAILABLE = False
    logger.warning("python-toon が未インストールのため ToonConverter は無効。`uv add python-toon` で追加可能。")


class ToonConverter(BaseProcessor):
    """JSON テキストを TOON 形式に変換する。

    json_compressor や json_table_converter より高い圧縮率を持つ。
    python-toon がインストールされていない場合は何もしない（スキップ）。
    """

    def should_apply(self, text: str) -> bool:
        if not _TOON_AVAILABLE:
            return False
        stripped = text.strip()
        return stripped.startswith(("{", "["))

    def process(self, text: str) -> tuple[str, bool]:
        if not self.should_apply(text):
            return text, False

        try:
            data = json.loads(text.strip())
        except (json.JSONDecodeError, ValueError):
            return text, False

        try:
            toon_str = _toon_lib.encode(data)
        except Exception as e:
            logger.debug("TOON エンコード失敗: %s", e)
            return text, False

        if len(toon_str) >= len(text):
            return text, False

        return toon_str, True
