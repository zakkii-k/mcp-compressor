"""設定ファイルの読み込みモジュール。

優先順位: 環境変数 > config.yaml > デフォルト値

環境変数:
  OLLAMA_URL   Ollama の URL（Docker 内では自動で host.docker.internal を使用）
  MCP_MODEL    使用モデル
  MCP_THRESHOLD 要約閾値（文字数）
"""

import os
from pathlib import Path

import yaml

DEFAULT_CONFIG: dict = {
    "threshold_chars": 5000,
    "originals_dir": "originals",
    "ollama_url": "http://localhost:11434",
    "model": "qwen2.5:3b",
    "pipeline": ["toon_converter", "log_deduplicator", "log_compressor", "llm_summarizer"],
    "log_compressor": {
        "max_lines": 50,
        "keep_errors": True,
    },
}

_ENV_MAP = {
    "OLLAMA_URL": "ollama_url",
    "MCP_MODEL": "model",
    "MCP_THRESHOLD": "threshold_chars",
}


def load_config(path: str = "config.yaml") -> dict:
    config = dict(DEFAULT_CONFIG)

    config_file = Path(path)
    if config_file.exists():
        with open(config_file, encoding="utf-8") as f:
            user_config = yaml.safe_load(f) or {}
        config.update(user_config)

    for env_key, config_key in _ENV_MAP.items():
        val = os.getenv(env_key)
        if val is not None:
            config[config_key] = val

    return config
