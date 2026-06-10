#!/usr/bin/env python3
"""MCP Response Summarizer Proxy - エントリーポイント

Usage:
  stdio モード（ローカル MCP サーバー用）:
    python -m mcp_compressor [--config config.yaml] -- <server_command> [args...]

  http モード（外部 MCP サーバー用・未実装）:
    python -m mcp_compressor --mode http [--port 8080]

Examples:
    python -m mcp_compressor -- node /path/to/mcp-server.js
    python -m mcp_compressor --config my_config.yaml -- uvx mcp-server-fetch
"""

import argparse
import logging
import sys


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
        "--mode", choices=["stdio", "http", "wrap"], default="stdio",
        help="プロキシモード: stdio=ローカルMCP（デフォルト）/ wrap=全MCPを束ねる / http=外部MCP（未実装）",
    )
    parser.add_argument(
        "--mcp-config", default="mcp.servers.json",
        help="wrap モード時に読むサーバー設定ファイルのパス（デフォルト: mcp.servers.json）",
    )
    parser.add_argument(
        "--no-meta-tools", dest="meta_tools", action="store_false", default=True,
        help="wrap モードでプレフィックス方式を使う（デフォルト: メタツール方式）",
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

    from mcp_compressor.config import load_config
    from mcp_compressor.pipeline import build_pipeline

    config = load_config(args.config)
    pipeline = build_pipeline(config)

    if args.mode == "stdio":
        from mcp_compressor.proxy.stdio_proxy import StdioProxy
        StdioProxy(args, pipeline).run()
    elif args.mode == "wrap":
        from mcp_compressor.proxy.wrap_proxy import WrapProxy
        WrapProxy(args, pipeline).run()
    elif args.mode == "http":
        from mcp_compressor.proxy.http_proxy import HTTPProxy
        HTTPProxy(args, pipeline).run()


if __name__ == "__main__":
    main()
