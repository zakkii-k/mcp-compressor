"""設定ファイルの読み込みモジュール。"""

from pathlib import Path
import yaml

DEFAULT_CONFIG: dict = {
    "threshold_chars": 5000,
    "originals_dir": "originals",
    "ollama_url": "http://localhost:11434",
    "model": "qwen2.5:3b",
    "pipeline": ["json_compressor", "log_compressor", "llm_summarizer"],
    "log_compressor": {
        "max_lines": 50,
        "keep_errors": True,
    },
}


def load_config(path: str = "config.yaml") -> dict:
    config = dict(DEFAULT_CONFIG)
    config_file = Path(path)
    if config_file.exists():
        with open(config_file, encoding="utf-8") as f:
            user_config = yaml.safe_load(f) or {}
        config.update(user_config)
    return config
