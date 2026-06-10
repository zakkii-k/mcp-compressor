"""MCP マルチプレクサ（wrap モード）。

mcp.servers.json を読み込み、定義された全サーバーに接続して、
単一の MCP サーバーとして Copilot に見せる。

## ツール公開方式

### メタツール方式（デフォルト）
常に2ツールだけ Copilot に見せる。

  mcp__list_tools(query?)  → ツール一覧を返す（JSON、パイプラインで圧縮）
  mcp__invoke_tool(server, tool, arguments) → 実際のツールを実行

  利点: tools パラメータのトークン消費が常に2ツール分だけ
  ツール一覧はJSONで返るためTOON圧縮がかかり、会話履歴に入っても小さい

### プレフィックス方式（config で切替可能）
全ツールを {server}__{tool} 形式でそのまま返す。従来の挙動。

## セットアップ

1. 既存の .vscode/mcp.json の内容を mcp.servers.json にコピー
2. .vscode/mcp.json を書き換え:
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

_SEP = "__"


class WrapProxy(BaseProxy):
    def __init__(self, args, pipeline) -> None:
        super().__init__(args, pipeline)
        self.connections: dict[str, BaseServerConnection] = {}

    # ─────────────────────────────────────────
    # 起動・接続
    # ─────────────────────────────────────────

    def _load_servers_config(self) -> dict[str, dict]:
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
    # ツール公開: メタツール方式
    # ─────────────────────────────────────────

    def _meta_tools(self) -> list[dict]:
        """常に2つのメタツールだけ返す。description にサーバー概要を含める。"""
        server_lines = []
        for name, conn in self.connections.items():
            # 各サーバーのツール名一覧を最大5件だけ description に含める
            sample = [t["name"] for t in conn.tools[:5]]
            suffix = f", ... 他{len(conn.tools)-5}件" if len(conn.tools) > 5 else ""
            server_lines.append(f"{name}: {', '.join(sample)}{suffix}")
        servers_desc = " / ".join(server_lines)

        return [
            {
                "name": "mcp__list_tools",
                "description": (
                    f"利用可能なツールを検索して一覧を返す。"
                    f"接続中のサーバーと主なツール: {servers_desc}。"
                    f"queryにサーバー名・操作内容を入れると絞り込める（空なら全件）。"
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "検索クエリ（サーバー名・ツール名・説明文で部分一致）",
                        }
                    },
                },
            },
            {
                "name": "mcp__invoke_tool",
                "description": (
                    "ツールを実行する。"
                    "mcp__list_tools で取得した server・tool 名を指定する。"
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "server":    {"type": "string",  "description": "サーバー名"},
                        "tool":      {"type": "string",  "description": "ツール名"},
                        "arguments": {"type": "object",  "description": "ツールの引数"},
                    },
                    "required": ["server", "tool"],
                },
            },
        ]

    def _handle_list_tools(self, query: str) -> dict:
        """query でフィルタリングしたツール一覧を JSON で返す（TOON 圧縮対象）。"""
        results = []
        for server_name, conn in self.connections.items():
            for tool in conn.tools:
                if query:
                    haystack = (
                        f"{server_name} {tool['name']} {tool.get('description', '')}"
                    ).lower()
                    if query.lower() not in haystack:
                        continue

                schema = tool.get("inputSchema", {})
                props  = schema.get("properties", {})
                required = schema.get("required", [])
                results.append({
                    "server": server_name,
                    "tool":   tool["name"],
                    "desc":   tool.get("description", ""),
                    # 引数: 必須は "*" マーク付き、型だけ残す
                    "args": {
                        k: ("*" if k in required else "") + v.get("type", "any")
                        for k, v in props.items()
                    },
                })

        if not results:
            text = f"該当するツールが見つかりません: '{query}'"
        else:
            # JSON 配列で返す → TOON がテーブル形式に圧縮してくれる
            text = json.dumps(results, ensure_ascii=False)

        return {"content": [{"type": "text", "text": text}], "isError": False}

    # ─────────────────────────────────────────
    # ツール公開: プレフィックス方式（代替）
    # ─────────────────────────────────────────

    def _prefixed_tools(self) -> list[dict]:
        """全ツールを {server}__{tool} 形式で返す（メタツール方式を使わない場合）。"""
        tools = []
        for server_name, conn in self.connections.items():
            for tool in conn.tools:
                t = dict(tool)
                t["name"] = f"{server_name}{_SEP}{tool['name']}"
                t["description"] = f"[{server_name}] {tool.get('description', '')}".strip()
                tools.append(t)
        return tools

    # ─────────────────────────────────────────
    # ルーティング
    # ─────────────────────────────────────────

    def _route_call(self, tool_name: str, arguments: dict) -> dict:
        # メタツール
        if tool_name == "mcp__list_tools":
            result = self._handle_list_tools(arguments.get("query", ""))
            return self._apply_pipeline(result)

        if tool_name == "mcp__invoke_tool":
            return self._invoke(
                arguments.get("server", ""),
                arguments.get("tool", ""),
                arguments.get("arguments", {}),
            )

        # プレフィックス方式（フォールバック）
        if _SEP not in tool_name:
            return _error_result(f"不明なツール: {tool_name}")
        server_name, real_tool = tool_name.split(_SEP, 1)
        return self._invoke(server_name, real_tool, arguments)

    def _invoke(self, server_name: str, tool_name: str, arguments: dict) -> dict:
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

        # config で方式を切り替える（デフォルト: メタツール方式）
        use_meta = self.args.meta_tools
        logger.info(
            "wrap モード起動: %d サーバー接続済み（%s方式）",
            len(self.connections),
            "メタツール" if use_meta else "プレフィックス",
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
                tools = self._meta_tools() if use_meta else self._prefixed_tools()
                self._send({
                    "jsonrpc": "2.0", "id": msg_id,
                    "result": {"tools": tools},
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
