#!/usr/bin/env python3
"""MCP Response Summarizer Proxy - エントリーポイント

Usage:
  stdio モード（ローカル MCP サーバー用）:
    python mcp_proxy.py [--config config.yaml] -- <server_command> [args...]

  http モード（外部 MCP サーバー用・未実装）:
    python mcp_proxy.py --mode http [--port 8080]

Examples:
    python mcp_proxy.py -- node /path/to/mcp-server.js
    python mcp_proxy.py --config my_config.yaml -- uvx mcp-server-fetch
"""

import argparse
import logging
import sys
from pathlib import Path


def setup_logging(level: str = "WARNING") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.WARNING),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )


def parse_args() -> argparse.Namespace:
    if "--" in sys.argv:
        sep = sys.argv.index("--")
        proxy_argv = sys.argv[1:sep]
        server_cmd = sys.argv[sep + 1:]
    else:
        proxy_argv = sys.argv[1:]
        server_cmd = []

    parser = argparse.ArgumentParser(description="MCP Response Summarizer Proxy")
    parser.add_argument(
        "--mode", choices=["stdio", "http"], default="stdio",
        help="プロキシモード: stdio=ローカルMCP（デフォルト）/ http=外部MCP（未実装）",
    )
    parser.add_argument("--config", default="config.yaml", help="設定ファイルのパス")
    parser.add_argument("--log-level", default="WARNING", help="ログレベル (DEBUG/INFO/WARNING/ERROR)")
    parser.add_argument("--port", type=int, default=8080, help="HTTP モード時のリスンポート（未実装）")

    args = parser.parse_args(proxy_argv)
    args.server_cmd = server_cmd
    return args


def main() -> None:
    args = parse_args()
    setup_logging(args.log_level)

    sys.path.insert(0, str(Path(__file__).parent))
    from config import load_config
    from pipeline import build_pipeline

    config = load_config(args.config)
    pipeline = build_pipeline(config)

    if args.mode == "stdio":
        from proxy.stdio_proxy import StdioProxy
        StdioProxy(args, pipeline).run()
    elif args.mode == "http":
        from proxy.http_proxy import HTTPProxy
        HTTPProxy(args, pipeline).run()


if __name__ == "__main__":
    main()
