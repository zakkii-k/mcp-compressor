"""Ollama 経由のローカル LLM でレスポンスを要約するプロセッサ。

閾値以上のテキストを要約し、元データをファイル保存する（可逆圧縮）。
"""

import logging
from datetime import datetime
from pathlib import Path

import httpx

from .base import BaseProcessor

logger = logging.getLogger(__name__)

# Ollama に送るテキストの上限（モデルのコンテキスト長を超えないよう制限）
_MAX_INPUT_CHARS = 12_000

_PROMPT_TEMPLATE = """\
以下はMCPツールの実行結果です。重要な情報を漏らさず、日本語で簡潔に要約してください。
エラー・警告・重要なデータ・次のアクションが必要な情報は必ず含めてください。
詳細な元データはファイルに保存済みであることを末尾に一言記載してください。

--- 結果 ---
{text}
--- ここまで ---

要約:"""


class LLMSummarizer(BaseProcessor):
    def __init__(
        self,
        threshold_chars: int,
        model: str,
        ollama_url: str,
        originals_dir: str,
    ) -> None:
        self.threshold_chars = threshold_chars
        self.model = model
        self.ollama_url = ollama_url.rstrip("/")
        self.originals_dir = Path(originals_dir)
        self.originals_dir.mkdir(parents=True, exist_ok=True)

    def should_apply(self, text: str) -> bool:
        return len(text) > self.threshold_chars

    def _save_original(self, text: str) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        path = self.originals_dir / f"original_{timestamp}.txt"
        path.write_text(text, encoding="utf-8")
        return path

    def _is_qwen3(self) -> bool:
        name = self.model.lower()
        return "qwen3" in name or "qwen3" in name.replace("-", "")

    def _summarize(self, text: str) -> str:
        truncated = text[:_MAX_INPUT_CHARS]
        if len(text) > _MAX_INPUT_CHARS:
            truncated += f"\n\n[... 以降 {len(text) - _MAX_INPUT_CHARS} 文字省略 ...]"

        prompt = _PROMPT_TEMPLATE.format(text=truncated)
        body: dict = {"model": self.model, "prompt": prompt, "stream": False}

        # Qwen3 は thinking mode がデフォルトでオン。
        # 要約タスクでは不要なので /no_think サフィックスで無効化する。
        if self._is_qwen3():
            body["prompt"] = prompt + " /no_think"

        with httpx.Client(timeout=120.0) as client:
            response = client.post(
                f"{self.ollama_url}/api/generate",
                json=body,
            )
            response.raise_for_status()
            raw = response.json()["response"].strip()
            # <think>...</think> ブロックが残っている場合は除去
            import re
            raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
            return raw

    def _is_ollama_running(self) -> bool:
        try:
            with httpx.Client(timeout=3.0) as client:
                r = client.get(f"{self.ollama_url}")
                return r.status_code == 200
        except Exception:
            return False

    def process(self, text: str) -> tuple[str, bool]:
        if not self.should_apply(text):
            return text, False

        # Ollama が起動していなければ LLM ステップをスキップ（前段の圧縮結果をそのまま返す）
        if not self._is_ollama_running():
            logger.warning("Ollama が起動していないため LLM 要約をスキップ: %s", self.ollama_url)
            return text, False

        original_path = self._save_original(text)
        logger.info("元データ保存: %s (%d 文字)", original_path, len(text))

        try:
            summary = self._summarize(text)
            result = (
                f"[LLM要約済み | モデル: {self.model} | "
                f"元データ: {original_path}]\n\n{summary}"
            )
            return result, True
        except Exception as e:
            logger.warning("LLM要約失敗 (%s): %s", type(e).__name__, e)
            # 失敗時は元テキストをそのまま返す（エラーメッセージで汚染しない）
            return text, False
