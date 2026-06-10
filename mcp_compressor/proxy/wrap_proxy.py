"""MCP マルチプレクサ（wrap モード）。

mcp.json（または --mcp-config で指定したファイル）を読み込み、
定義された全サーバーに接続して、単一の MCP サーバーとして Copilot に見せる。

ツール名は "{サーバー名}__{元のツール名}" にプレフィックスされる。
例: filesystem__read_file, atlassian__create_issue

## セットアップ方法

1. 既存の .vscode/mcp.json を mcp.servers.json にコピー
2. .vscode/mcp.json を以下に書き換え:
   {
     "servers": {
       "mcp-compressor": {
         "type": "stdio",
         "command": "python",
         "args": ["-m", "mcp_compressor", "--mode", "wrap",
                  "--mcp-config", "mcp.servers.json"]
       }
     }
   }
"""

import json
import logging
import sys
from pathlib import Path

from .base import BaseProxy
from .server_connection import BaseServerConnection, create_connection

logger = logging.getLogger("mcp_proxy.wrap")

# ツール名のサーバー名プレフィックス区切り文字
_SEP = "__"


class WrapProxy(BaseProxy):
    def __init__(self, args, pipeline) -> None:
        super().__init__(args, pipeline)
        self.connections: dict[str, BaseServerConnection] = {}

    # ─────────────────────────────────────────
    # 起動・接続
    # ─────────────────────────────────────────

    def _load_servers_config(self) -> dict[str, dict]:
        """--mcp-config のファイルからサーバー定義を読み込む。"""
        candidates = [
            Path(self.args.mcp_config),
            Path("mcp.servers.json"),
            Path(".vscode/mcp.servers.json"),
        ]
        for path in candidates:
            if path.exists():
                logger.info("サーバー設定を読み込み: %s", path)
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                return data.get("servers", {})

        raise FileNotFoundError(
            "サーバー設定ファイルが見つかりません。\n"
            "--mcp-config <path> でパスを指定するか、"
            "mcp.servers.json をプロジェクトルートに置いてください。\n"
            f"探したパス: {[str(p) for p in candidates]}"
        )

    def _connect_all(self, servers: dict[str, dict]) -> None:
        for name, config in servers.items():
            try:
                conn = create_connection(name, config)
                conn.connect()
                self.connections[name] = conn
            except Exception as e:
                logger.warning("サーバー接続失敗（スキップ）: %s — %s", name, e)

    # ─────────────────────────────────────────
    # ツール一覧の集約
    # ─────────────────────────────────────────

    def _aggregated_tools(self) -> list[dict]:
        """全サーバーのツールをプレフィックス付きで返す。"""
        tools = []
        for server_name, conn in self.connections.items():
            for tool in conn.tools:
                t = dict(tool)
                t["name"] = f"{server_name}{_SEP}{tool['name']}"
                t["description"] = f"[{server_name}] {tool.get('description', '')}".strip()
                tools.append(t)
        return tools

    # ─────────────────────────────────────────
    # ツール呼び出しのルーティング
    # ─────────────────────────────────────────

    def _route_call(self, prefixed_name: str, arguments: dict) -> dict:
        """プレフィックスからサーバーを特定して転送し、パイプラインを適用する。"""
        if _SEP not in prefixed_name:
            return _error_result(f"ツール名にサーバープレフィックスがありません: {prefixed_name}")

        server_name, tool_name = prefixed_name.split(_SEP, 1)
        conn = self.connections.get(server_name)
        if not conn:
            return _error_result(f"サーバーが見つかりません: {server_name}")

        try:
            result = conn.call_tool(tool_name, arguments)
        except Exception as e:
            return _error_result(f"ツール呼び出しエラー ({server_name}/{tool_name}): {e}")

        return self._apply_pipeline(result)

    def _apply_pipeline(self, result: dict) -> dict:
        content = result.get("content", [])
        text_items = [
            c for c in content
            if isinstance(c, dict) and c.get("type") == "text" and c.get("text")
        ]
        if not text_items:
            return result

        combined = "\n".join(c["text"] for c in text_items)
        processed, was_modified = self.pipeline.process(combined)
        if not was_modified:
            return result

        non_text = [c for c in content if c.get("type") != "text"]
        return {**result, "content": non_text + [{"type": "text", "text": processed}]}

    # ─────────────────────────────────────────
    # メインループ
    # ─────────────────────────────────────────

    def _send(self, message: dict) -> None:
        sys.stdout.buffer.write((json.dumps(message, ensure_ascii=False) + "\n").encode())
        sys.stdout.buffer.flush()

    def run(self) -> None:
        try:
            servers = self._load_servers_config()
        except FileNotFoundError as e:
            print(str(e), file=sys.stderr)
            sys.exit(1)

        if not servers:
            print("サーバーが1つも定義されていません", file=sys.stderr)
            sys.exit(1)

        self._connect_all(servers)

        if not self.connections:
            print("接続できたサーバーがありません", file=sys.stderr)
            sys.exit(1)

        logger.info(
            "wrap モード起動: %d / %d サーバーに接続",
            len(self.connections), len(servers)
        )

        for raw_line in sys.stdin.buffer:
            line = raw_line.rstrip(b"\r\n").decode("utf-8", errors="replace")
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue

            method = msg.get("method", "")
            msg_id = msg.get("id")

            if method == "initialize":
                self._send({
                    "jsonrpc": "2.0", "id": msg_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "mcp-compressor", "version": "0.1.0"},
                    },
                })

            elif method == "notifications/initialized":
                pass

            elif method == "tools/list":
                self._send({
                    "jsonrpc": "2.0", "id": msg_id,
                    "result": {"tools": self._aggregated_tools()},
                })

            elif method == "tools/call":
                params = msg.get("params", {})
                result = self._route_call(
                    params.get("name", ""),
                    params.get("arguments", {}),
                )
                self._send({"jsonrpc": "2.0", "id": msg_id, "result": result})

            elif msg_id is not None:
                self._send({
                    "jsonrpc": "2.0", "id": msg_id,
                    "error": {"code": -32601, "message": f"Method not found: {method}"},
                })

        for conn in self.connections.values():
            conn.close()


def _error_result(message: str) -> dict:
    return {"content": [{"type": "text", "text": message}], "isError": True}
