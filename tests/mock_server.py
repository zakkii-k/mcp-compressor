#!/usr/bin/env python3
"""テスト用モック MCP サーバー。

大きなレスポンスを返す3種類のツールを提供し、プロキシの動作確認に使う。
"""

import json
import sys


TOOLS = [
    {
        "name": "get_large_json",
        "description": "大きな JSON データを返す（JSON圧縮ステージのテスト用）",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_large_log",
        "description": "大量のログを返す（ログ圧縮ステージのテスト用）",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_large_text",
        "description": "大量のテキストを返す（LLM要約ステージのテスト用）",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_small_response",
        "description": "小さいレスポンスを返す（閾値以下なので要約されない）",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def make_large_json() -> str:
    """意図的に空白の多い大きな JSON を生成する。"""
    data = {
        "status": "success",
        "metadata": {
            "generated_at": "2024-06-10T12:00:00Z",
            "source": "mock-database",
            "version": "3.14.159",
        },
        "users": [
            {
                "id": i,
                "name": f"User {i:04d}",
                "email": f"user{i:04d}@example.com",
                "role": "admin" if i % 10 == 0 else "member",
                "created_at": f"2024-0{(i % 9) + 1}-{(i % 28) + 1:02d}T00:00:00Z",
                "preferences": {
                    "theme": "dark" if i % 2 == 0 else "light",
                    "language": "ja",
                    "notifications": True,
                },
            }
            for i in range(1, 80)
        ],
    }
    # 意図的に indent=4 で空白を多くして大きくする
    return json.dumps(data, ensure_ascii=False, indent=4)


def make_large_log() -> str:
    """大量のログ行を生成する。"""
    lines = []
    for i in range(1, 201):
        if i % 50 == 0:
            lines.append(f"2024-06-10 12:{i // 60:02d}:{i % 60:02d} ERROR  Failed to process request #{i}: ConnectionTimeout after 30s")
        elif i % 30 == 0:
            lines.append(f"2024-06-10 12:{i // 60:02d}:{i % 60:02d} WARN   Retry attempt {i % 3 + 1}/3 for task {i}")
        else:
            lines.append(f"2024-06-10 12:{i // 60:02d}:{i % 60:02d} INFO   Processing item {i}/200 - status=OK latency=12ms")
    return "\n".join(lines)


def make_large_text() -> str:
    """要約が必要な大量のテキストを生成する。"""
    sections = []
    for i in range(1, 20):
        sections.append(f"""
## セクション {i}: システムコンポーネント {i} の分析レポート

コンポーネント {i} は現在正常に稼働しています。直近30日間のパフォーマンス指標によると、
平均応答時間は {i * 12}ms であり、前月比で {i % 5 * 2}% 改善しました。
エラー率は {i * 0.01:.2f}% に低下しており、SLO の 0.5% を大幅に下回っています。

リソース使用率については、CPU が平均 {20 + i}%、メモリが {30 + i * 2}% で安定しており、
スケールアウトの必要性は当面ないと判断されます。

次のメンテナンスウィンドウは 2024-07-{i:02d} を予定しており、
バージョン {i}.{i+1}.0 へのアップグレードを実施します。
""")
    return "\n".join(sections)


def handle_tool_call(name: str) -> str:
    if name == "get_large_json":
        return make_large_json()
    elif name == "get_large_log":
        return make_large_log()
    elif name == "get_large_text":
        return make_large_text()
    elif name == "get_small_response":
        return "OK: 処理完了。エラーなし。"
    else:
        return f"Unknown tool: {name}"


def send(message: dict) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main() -> None:
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue

        method = msg.get("method", "")
        msg_id = msg.get("id")

        if method == "initialize":
            send({
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "mock-server", "version": "1.0"},
                },
            })

        elif method == "notifications/initialized":
            pass  # 通知には返答不要

        elif method == "tools/list":
            send({
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {"tools": TOOLS},
            })

        elif method == "tools/call":
            tool_name = msg.get("params", {}).get("name", "")
            text = handle_tool_call(tool_name)
            send({
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "content": [{"type": "text", "text": text}],
                    "isError": False,
                },
            })

        elif msg_id is not None:
            send({"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": f"Method not found: {method}"}})


if __name__ == "__main__":
    main()
