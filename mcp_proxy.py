#!/usr/bin/env python3
"""MCP Response Summarizer Proxy

MCPサーバーのレスポンスをインターセプトし、ローカルLLMで要約するプロキシ。

Usage:
    python mcp_proxy.py [--config config.yaml] [--log-level WARNING] -- <server_command> [args...]

Example:
    python mcp_proxy.py -- node /path/to/mcp-server.js
    python mcp_proxy.py --config my_config.yaml -- uvx mcp-server-fetch
"""

import sys
import json
import subprocess
import threading
import argparse
import logging
from pathlib import Path


def setup_logging(level: str = "WARNING") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.WARNING),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )


logger = logging.getLogger("mcp_proxy")


def parse_args() -> argparse.Namespace:
    if "--" in sys.argv:
        sep = sys.argv.index("--")
        proxy_argv = sys.argv[1:sep]
        server_cmd = sys.argv[sep + 1 :]
    else:
        proxy_argv = sys.argv[1:]
        server_cmd = []

    parser = argparse.ArgumentParser(description="MCP Response Summarizer Proxy")
    parser.add_argument("--config", default="config.yaml", help="設定ファイルのパス")
    parser.add_argument("--log-level", default="WARNING", help="ログレベル (DEBUG/INFO/WARNING/ERROR)")

    args = parser.parse_args(proxy_argv)
    args.server_cmd = server_cmd
    return args


def process_message(message: dict, pipeline) -> dict:
    """tool call レスポンスをパイプラインに通して処理する。"""
    result = message.get("result")
    if not isinstance(result, dict):
        return message

    content = result.get("content")
    if not isinstance(content, list):
        return message

    text_items = [
        item for item in content
        if isinstance(item, dict) and item.get("type") == "text" and item.get("text")
    ]
    if not text_items:
        return message

    combined_text = "\n".join(item["text"] for item in text_items)
    original_size = len(combined_text)

    processed_text, was_modified = pipeline.process(combined_text)

    if was_modified:
        logger.info("レスポンス処理: %d → %d 文字", original_size, len(processed_text))
        non_text_items = [item for item in content if item.get("type") != "text"]
        new_content = non_text_items + [{"type": "text", "text": processed_text}]
        message = {**message, "result": {**result, "content": new_content}}

    return message


def _forward_stdin(server_proc: subprocess.Popen) -> None:
    """クライアントの stdin をサーバープロセスの stdin へ転送する。"""
    try:
        for line in sys.stdin.buffer:
            server_proc.stdin.write(line)
            server_proc.stdin.flush()
    except Exception as e:
        logger.debug("stdin 転送終了: %s", e)
    finally:
        try:
            server_proc.stdin.close()
        except Exception:
            pass


def _forward_stdout(server_proc: subprocess.Popen, pipeline) -> None:
    """サーバーの stdout を処理しながらクライアントへ転送する。"""
    out = sys.stdout.buffer
    try:
        for raw_line in server_proc.stdout:
            line = raw_line.rstrip(b"\r\n").decode("utf-8", errors="replace")
            if not line:
                continue
            try:
                message = json.loads(line)
                # JSON-RPC レスポンス（id あり、result あり）のみ処理対象
                if "result" in message and "id" in message:
                    message = process_message(message, pipeline)
                out.write((json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8"))
            except json.JSONDecodeError:
                out.write(raw_line)
            out.flush()
    except Exception as e:
        logger.error("stdout 転送エラー: %s", e)


def _forward_stderr(server_proc: subprocess.Popen) -> None:
    """サーバーの stderr をそのまま転送する。"""
    try:
        for line in server_proc.stderr:
            sys.stderr.buffer.write(line)
            sys.stderr.buffer.flush()
    except Exception:
        pass


def main() -> None:
    args = parse_args()
    setup_logging(args.log_level)

    if not args.server_cmd:
        print(
            "エラー: サーバーコマンドが指定されていません。\n"
            "使い方: python mcp_proxy.py [options] -- <command> [args...]",
            file=sys.stderr,
        )
        sys.exit(1)

    sys.path.insert(0, str(Path(__file__).parent))
    from config import load_config
    from pipeline import build_pipeline

    config = load_config(args.config)
    pipeline = build_pipeline(config)

    logger.info("MCP プロキシ起動: %s", args.server_cmd)

    server_proc = subprocess.Popen(
        args.server_cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    threads = [
        threading.Thread(target=_forward_stdin, args=(server_proc,), daemon=True, name="stdin"),
        threading.Thread(target=_forward_stdout, args=(server_proc, pipeline), daemon=True, name="stdout"),
        threading.Thread(target=_forward_stderr, args=(server_proc,), daemon=True, name="stderr"),
    ]
    for t in threads:
        t.start()

    try:
        server_proc.wait()
    except KeyboardInterrupt:
        server_proc.terminate()
        server_proc.wait()

    sys.exit(server_proc.returncode)


if __name__ == "__main__":
    main()
