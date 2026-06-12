"""トークン数推定モジュール。

tiktoken がインストールされていれば GPT-4 系の実際のトークナイザーを使用する。
インストールされていなければ chars/4 の heuristic で推定する（±20% 程度の誤差）。
"""

from __future__ import annotations

_encoder = None
_tiktoken_available = False

try:
    import tiktoken
    _encoder = tiktoken.get_encoding("cl100k_base")
    _tiktoken_available = True
except Exception:
    pass


def count(text: str) -> int:
    if _tiktoken_available and _encoder is not None:
        return len(_encoder.encode(text))
    return max(1, len(text) // 4)


def is_exact() -> bool:
    return _tiktoken_available
