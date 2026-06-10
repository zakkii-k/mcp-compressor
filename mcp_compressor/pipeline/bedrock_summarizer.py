"""Amazon Bedrock 経由で LLM 要約するプロセッサ。

ローカル Ollama の代わりに Bedrock のモデルを使う。
認証は boto3 のデフォルト credential chain を使用するため、
aws sso login 済みであれば追加設定不要。

設定例（config.yaml）:
  provider: bedrock
  bedrock_model: "us.google.gemma-3-27b-it-v1:0"
  aws_region: "us-east-1"
  # aws_profile: "my-sso-profile"  # プロファイル名（省略時はデフォルト）

利用可能な主なモデル（Bedrock）:
  us.google.gemma-3-4b-it-v1:0    安価・高速
  us.google.gemma-3-12b-it-v1:0   バランス
  us.google.gemma-3-27b-it-v1:0   高品質
  us.meta.llama3-3-70b-instruct-v1:0
  amazon.nova-micro-v1:0          最安
"""

import logging
from datetime import datetime
from pathlib import Path

from .base import BaseProcessor

logger = logging.getLogger(__name__)

_MAX_INPUT_CHARS = 12_000

_PROMPT = """\
以下はMCPツールの実行結果です。重要な情報を漏らさず、日本語で簡潔に要約してください。
エラー・警告・重要なデータ・次のアクションが必要な情報は必ず含めてください。
詳細な元データはファイルに保存済みであることを末尾に一言記載してください。

--- 結果 ---
{text}
--- ここまで ---

要約:"""


class BedrockSummarizer(BaseProcessor):
    def __init__(
        self,
        threshold_chars: int,
        model: str,
        region: str,
        originals_dir: str,
        profile: str | None = None,
    ) -> None:
        self.threshold_chars = threshold_chars
        self.model = model
        self.region = region
        self.originals_dir = Path(originals_dir)
        self.originals_dir.mkdir(parents=True, exist_ok=True)
        self.profile = profile
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                import boto3
            except ImportError:
                raise ImportError(
                    "boto3 が未インストールです。`pip install boto3` を実行してください。"
                )
            session = (
                boto3.Session(profile_name=self.profile)
                if self.profile
                else boto3.Session()
            )
            self._client = session.client("bedrock-runtime", region_name=self.region)
        return self._client

    def should_apply(self, text: str) -> bool:
        return len(text) > self.threshold_chars

    def _save_original(self, text: str) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        path = self.originals_dir / f"original_{timestamp}.txt"
        path.write_text(text, encoding="utf-8")
        return path

    def _summarize(self, text: str) -> str:
        truncated = text[:_MAX_INPUT_CHARS]
        if len(text) > _MAX_INPUT_CHARS:
            truncated += f"\n\n[... 以降 {len(text) - _MAX_INPUT_CHARS} 文字省略 ...]"

        prompt = _PROMPT.format(text=truncated)

        # Converse API はモデル間で共通のインターフェース
        response = self._get_client().converse(
            modelId=self.model,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": 1024, "temperature": 0.3},
        )
        return response["output"]["message"]["content"][0]["text"].strip()

    def process(self, text: str) -> tuple[str, bool]:
        if not self.should_apply(text):
            return text, False

        original_path = self._save_original(text)
        logger.info("元データ保存: %s (%d 文字)", original_path, len(text))

        try:
            summary = self._summarize(text)
            result = (
                f"[Bedrock要約済み | モデル: {self.model} | "
                f"元データ: {original_path}]\n\n{summary}"
            )
            return result, True
        except Exception as e:
            logger.warning("Bedrock要約失敗 (%s): %s", type(e).__name__, e)
            return text, False
