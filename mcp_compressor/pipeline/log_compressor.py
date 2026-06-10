"""ログ形式のレスポンスを圧縮するプロセッサ。

エラー行・先頭・末尾を残し、中間の重複する INFO ログなどを除去する。
"""

import re
from .base import BaseProcessor

_LOG_LINE_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}"        # 日付
    r"|\d{2}:\d{2}:\d{2}"       # 時刻
    r"|\b(ERROR|WARN(?:ING)?|INFO|DEBUG|TRACE|FATAL)\b",
    re.IGNORECASE,
)
_ERROR_RE = re.compile(r"(ERROR|FATAL|Exception|Traceback|panic:)", re.IGNORECASE)


class LogCompressor(BaseProcessor):
    def __init__(self, max_lines: int = 50, keep_errors: bool = True) -> None:
        self.max_lines = max_lines
        self.keep_errors = keep_errors

    def should_apply(self, text: str) -> bool:
        lines = text.split("\n")
        if len(lines) < 20:
            return False
        sample = lines[:50]
        log_line_count = sum(1 for l in sample if _LOG_LINE_RE.search(l))
        return log_line_count / len(sample) > 0.3

    def process(self, text: str) -> tuple[str, bool]:
        if not self.should_apply(text):
            return text, False

        lines = text.split("\n")
        total = len(lines)

        head = lines[:10]
        tail = lines[-20:]
        error_lines = (
            [l for l in lines[10:-20] if _ERROR_RE.search(l)][:20]
            if self.keep_errors
            else []
        )

        kept = head + error_lines + tail
        if len(kept) >= total:
            return text, False

        header = (
            f"[ログ圧縮済み: {total} 行 → {len(kept)} 行 "
            f"(先頭10行 + エラー{len(error_lines)}行 + 末尾20行)]\n"
        )
        return header + "\n".join(kept), True
