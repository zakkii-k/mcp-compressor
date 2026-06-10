"""JSON 配列をMarkdownテーブルに変換するプロセッサ。

オブジェクトの配列（例: ユーザーリスト、レコード一覧）をMarkdownテーブルに変換し、
JSONのキー名や括弧・引用符による冗長さを取り除く。
LLMにとってもテーブル形式は読みやすく、トークン効率が高い。
"""

import json
from .base import BaseProcessor

_MAX_CELL_CHARS = 40    # セルの最大文字数
_MAX_ROWS = 50          # テーブルの最大行数
_MIN_ITEMS = 3          # この件数未満なら変換しない
_MIN_KEYS = 2           # この列数未満なら変換しない


def _truncate(value: object, max_len: int = _MAX_CELL_CHARS) -> str:
    s = str(value) if not isinstance(value, str) else value
    if len(s) > max_len:
        return s[:max_len - 1] + "…"
    return s


def _is_array_of_objects(data: object) -> bool:
    return (
        isinstance(data, list)
        and len(data) >= _MIN_ITEMS
        and all(isinstance(item, dict) for item in data[:10])
    )


def _to_markdown_table(items: list[dict], total: int) -> str:
    # 全アイテムに登場するキーを収集（登場頻度順）
    key_freq: dict[str, int] = {}
    for item in items:
        for k in item:
            key_freq[k] = key_freq.get(k, 0) + 1
    # 頻度の高いキーを優先。ネスト値（dict/list）は末尾に
    def key_sort(k: str) -> tuple:
        sample = items[0].get(k)
        is_nested = isinstance(sample, (dict, list))
        return (is_nested, -key_freq[k], k)

    keys = sorted(key_freq.keys(), key=key_sort)
    if len(keys) < _MIN_KEYS:
        return ""

    header = "| " + " | ".join(keys) + " |"
    separator = "|" + "|".join("---" for _ in keys) + "|"
    rows = []
    for item in items:
        cells = []
        for k in keys:
            val = item.get(k, "")
            if isinstance(val, dict):
                val = "{…}"
            elif isinstance(val, list):
                val = f"[{len(val)}件]"
            cells.append(_truncate(val))
        rows.append("| " + " | ".join(cells) + " |")

    table = "\n".join([header, separator] + rows)
    if total > len(items):
        table += f"\n\n*（{total}件中 {len(items)}件を表示）*"
    return table


class JSONTableConverter(BaseProcessor):
    """JSON 配列のオブジェクトを Markdown テーブルに変換する。"""

    def should_apply(self, text: str) -> bool:
        stripped = text.strip()
        if not stripped.startswith("["):
            return False
        try:
            data = json.loads(stripped)
            return _is_array_of_objects(data)
        except (json.JSONDecodeError, ValueError):
            return False

    def process(self, text: str) -> tuple[str, bool]:
        if not self.should_apply(text):
            return text, False
        try:
            data = json.loads(text.strip())
            total = len(data)
            items = data[:_MAX_ROWS]
            table = _to_markdown_table(items, total)
            if not table:
                return text, False
            result = f"[JSON配列→テーブル変換: {total}件]\n\n{table}"
            if len(result) >= len(text):
                return text, False  # 変換後のほうが大きければ元のまま
            return result, True
        except Exception:
            return text, False
