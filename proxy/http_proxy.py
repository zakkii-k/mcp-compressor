"""HTTP/SSE MCP プロキシ（外部 MCP サーバー用）。

Atlassian（Jira/Confluence）・GitHub 等の外部 API ベースの
MCP サーバーのレスポンスをインターセプトする HTTP プロキシ。

## 実装予定の仕組み

1. ローカルポートで HTTP サーバーを起動（デフォルト: 8080）
2. VS Code の外部 MCP 設定を以下のように変更:
     変更前: url: "https://mcp.atlassian.com/..."
     変更後: url: "http://localhost:8080/atlassian/..."
3. リクエストを本来の URL に透過転送
4. レスポンスをパイプラインに通して圧縮・要約
5. 処理済みレスポンスを VS Code に返却

## 実装時に必要な依存パッケージ（pyproject.toml に追加）

  - fastapi または aiohttp（HTTP サーバー）
  - httpx（外部 MCP サーバーへの転送）※既存

## ルーティング設定イメージ（config.yaml に追加予定）

  http_proxy:
    port: 8080
    routes:
      - prefix: /atlassian
        target: https://mcp.atlassian.com
      - prefix: /github
        target: https://api.githubcopilot.com/mcp

## VS Code 設定イメージ

  {
    "servers": {
      "atlassian": {
        "type": "sse",
        "url": "http://localhost:8080/atlassian/sse"
      }
    }
  }
"""

from .base import BaseProxy


class HTTPProxy(BaseProxy):
    """HTTP/SSE MCP プロキシ（未実装）。"""

    def run(self) -> None:
        raise NotImplementedError(
            "HTTP プロキシモードは未実装です。\n"
            "外部 MCP（Atlassian / GitHub 等）のインターセプトは今後実装予定。\n"
            "現在は stdio モード（ローカル MCP サーバー）のみ対応しています。\n"
            "\n"
            "ローカル MCP の場合:\n"
            "  python mcp_proxy.py -- <server_command>"
        )
