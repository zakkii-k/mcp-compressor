"""JSON レスポンスを minify して文字数を削減するプロセッサ。"""

import json
from .base import BaseProcessor


class JSONCompressor(BaseProcessor):
    def should_apply(self, text: str) -> bool:
        stripped = text.strip()
        return stripped.startswith(("{", "["))

    def process(self, text: str) -> tuple[str, bool]:
        if not self.should_apply(text):
            return text, False
        try:
            data = json.loads(text)
            compressed = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
            if len(compressed) < len(text):
                return compressed, True
        except (json.JSONDecodeError, ValueError):
            pass
        return text, False
