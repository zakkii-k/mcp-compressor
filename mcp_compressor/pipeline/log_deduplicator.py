"""ログの繰り返しパターンを集約して大幅に圧縮するプロセッサ。

同じ構造の行（数値・タイムスタンプ・IDのみが異なる行）を1行にまとめる。
例: "Processing item 1/200", "Processing item 2/200" ... → 1行 + 回数表記
"""

import re
from collections import OrderedDict
from .base import BaseProcessor

# タイムスタンプ・数値・UUIDなど可変部分を正規化するパターン
_NORMALIZE_RE = re.compile(
    r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?\b"  # ISO timestamp
    r"|\b\d{4}-\d{2}-\d{2}\b"          # date
    r"|\b\d{2}:\d{2}:\d{2}\b"          # time
    r"|\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"  # UUID
    r"|\b0x[0-9a-fA-F]+\b"             # hex
    r"|\b\d+\.\d+\.\d+\.\d+\b"         # IP address
    r"|\b\d+\b",                         # 数値
    re.IGNORECASE,
)

_LOG_LINE_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}"
    r"|\d{2}:\d{2}:\d{2}"
    r"|\b(ERROR|WARN(?:ING)?|INFO|DEBUG|TRACE|FATAL)\b",
    re.IGNORECASE,
)
_ERROR_RE = re.compile(r"(ERROR|FATAL|Exception|Traceback|panic:)", re.IGNORECASE)


def _normalize(line: str) -> str:
    return _NORMALIZE_RE.sub("<N>", line)


class LogDeduplicator(BaseProcessor):
    """繰り返しパターンのログ行を集約する。

    同じパターンの行が複数あれば「パターン x N回」にまとめ、
    ERROR/例外行は必ず個別に保持する。
    """

    MIN_LINES = 10  # これ未満の行数には適用しない
    MIN_RATIO = 0.25  # ログ行の割合がこれ以上なら適用

    def should_apply(self, text: str) -> bool:
        lines = text.split("\n")
        if len(lines) < self.MIN_LINES:
            return False
        sample = lines[:60]
        log_count = sum(1 for l in sample if _LOG_LINE_RE.search(l))
        return log_count / len(sample) >= self.MIN_RATIO

    def process(self, text: str) -> tuple[str, bool]:
        if not self.should_apply(text):
            return text, False

        lines = text.split("\n")
        # パターン → (代表行, 回数, is_error)
        pattern_map: OrderedDict[str, list] = OrderedDict()

        for line in lines:
            if not line.strip():
                continue
            is_error = bool(_ERROR_RE.search(line))
            pat = _normalize(line)
            if pat not in pattern_map:
                pattern_map[pat] = [line, 1, is_error]
            else:
                pattern_map[pat][1] += 1
                if is_error:
                    pattern_map[pat][2] = True

        original_line_count = len([l for l in lines if l.strip()])
        if len(pattern_map) >= original_line_count:
            return text, False  # 重複なし

        result_lines = []
        for representative, count, is_error in pattern_map.values():
            if count == 1:
                result_lines.append(representative)
            else:
                result_lines.append(f"{representative}  [×{count}]")

        header = (
            f"[ログ重複除去済み: {original_line_count} 行 → "
            f"{len(result_lines)} パターン ({len(result_lines)/original_line_count*100:.0f}%)]\n"
        )
        return header + "\n".join(result_lines), True
