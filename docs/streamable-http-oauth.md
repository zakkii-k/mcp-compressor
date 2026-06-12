# Streamable HTTP + OAuth 2.0 対応

## 背景

Atlassian Confluence など、MCP 2025-03-26 仕様の **Streamable HTTP** トランスポートを使うリモート MCP サーバーは、旧 SSE プロトコル実装では接続できない。加えて OAuth 2.0 認証が必須になっている。

VS Code は `.vscode/mcp.json` に `type: "http"` で URL を書くとブラウザ認証を自動で行い、2回目以降はキャッシュトークンで透過的に接続する。今回の改修で mcp-wrapper にも同等の機能を実装した。

---

## 編集ファイル一覧

### 新規: `mcp_compressor/proxy/oauth_client.py`

**目的:** MCP OAuth 2.0 PKCE クライアントを独立モジュールとして実装する。

**内容:**

| 機能 | 詳細 |
|------|------|
| OAuth メタデータ取得 | `/.well-known/oauth-authorization-server` を GETして認可エンドポイント・トークンエンドポイントを自動取得 |
| 動的クライアント登録 | RFC 7591 準拠。`registration_endpoint` があれば自動登録、なければ `client_id = "mcp-compressor"` を使用 |
| PKCE フロー | `code_verifier`（URLsafe 64バイト乱数）→ SHA-256 → Base64url で `code_challenge` 生成 |
| ローカルコールバック | `HTTPServer(localhost, 0)` でランダムポートを取得し、ブラウザのリダイレクトをキャッチ |
| ブラウザ起動 | `webbrowser.open()` 使用。PowerShell から起動しても Windows の既定ブラウザが開く |
| トークンキャッシュ | Windows: `%APPDATA%\mcp-compressor\tokens\<サーバー名>.json` / Linux: `~/.config/mcp-compressor/tokens/` |
| 自動リフレッシュ | 有効期限60秒前に refresh_token でサイレント更新。失敗時は再ブラウザ認証 |
| 401 対応 | `invalidate()` でトークンを無効化 → 次回 `get_access_token()` でリフレッシュまたは再認証 |

**クラス: `OAuthClient`**

```python
client = OAuthClient(server_name="confluence", mcp_url="https://mcp.atlassian.com/v1/mcp")
token = client.get_access_token()  # 初回: ブラウザ認証 / 2回目以降: キャッシュ or リフレッシュ
client.invalidate()                # 401 受信時に呼ぶ
```

---

### 変更: `mcp_compressor/proxy/server_connection.py`

**目的:** Streamable HTTP 接続クラスの追加と、ファクトリ関数の対応型追加。

**追加クラス: `StreamableHttpServerConnection`**

旧 `SSEServerConnection` との違い:

| | SSEServerConnection（旧 SSE） | StreamableHttpServerConnection（新） |
|---|---|---|
| 接続方式 | GET でSSEストリームを張り、`endpoint` イベントでメッセージURLを受け取る | なし（接続フェーズ不要） |
| リクエスト送信 | SSEストリームから得たURLにPOST | MCP URLに直接POST |
| 認証 | なし | OAuth 2.0 Bearer / 静的ヘッダー 両対応 |
| レスポンス | SSEストリームで非同期受信 | JSON または SSEボディを同期で受信 |

**401 ハンドリング:**
```
POST → 401 → OAuthClient.invalidate() → get_access_token()（refresh or 再認証）→ 再POST
```

**ファクトリ `create_connection` の変更:**

```python
# 変更前
elif server_type in ("sse", "http"):
    return SSEServerConnection(name, config)

# 変更後
elif server_type == "sse":
    return SSEServerConnection(name, config)
elif server_type in ("http", "streamable_http"):
    return StreamableHttpServerConnection(name, config)
```

---

### 変更: `mcp.servers.example.json`

**目的:** 新しい `streamable_http` タイプの使い方をサンプルとして追記。

追記したエントリ:

```json
"confluence": {
  "type": "streamable_http",
  "url": "https://mcp.atlassian.com/v1/mcp"
}
```

OAuth なしで静的トークンを使う場合（Atlassian API Token など）:

```json
"confluence-with-token": {
  "type": "streamable_http",
  "url": "https://mcp.atlassian.com/v1/mcp",
  "headers": {
    "Authorization": "Bearer YOUR_ATLASSIAN_API_TOKEN"
  }
}
```

---

## mcp.servers.json の書き方まとめ

| ケース | type | 備考 |
|--------|------|------|
| ローカルプロセス（npx, uvx 等） | `stdio` | 従来通り |
| 旧 Atlassian SSE エンドポイント | `sse` | `url` は `/v1/sse` |
| Atlassian Confluence（現行） | `streamable_http` | `url` は `/v1/mcp`、初回のみブラウザ認証 |
| 静的トークンで接続 | `streamable_http` + `headers.Authorization` | OAuth フロー不要 |

---

## 初回起動時の挙動（PowerShell）

```
PS> python -m mcp_compressor --mode wrap --mcp-config mcp.servers.json

[mcp-compressor] confluence: ブラウザで認証してください...
（ブラウザが開く → Atlassian でログイン → 許可 → タブを閉じる）
[mcp-compressor] confluence: 認証完了。トークンを C:\Users\xxx\AppData\Roaming\mcp-compressor\tokens\confluence.json に保存しました。
```

2回目以降はブラウザなしで起動する。

---

## 未対応・今後の課題

- **OAuth スコープの明示指定:** 現在はサーバーの `scopes_supported` を全部渡している。Atlassian では必要なスコープだけに絞ったほうがよい場合がある。
- **動的クライアント登録の永続化:** 現在は `client_id` をトークンキャッシュに一緒に保存しているが、サーバーによっては登録が失効する可能性がある。
- **Atlassian の実際のエンドポイント確認:** `/v1/mcp/authv2` が `/.well-known` メタデータを返すか、別途調べて必要なら `_fetch_meta` をフォールバック付きにする。
- **streamable HTTP のストリーミングレスポンス:** 現在は `resp.text` で全読みしているため、長時間かかるツール呼び出しでタイムアウト（60秒）が発生する可能性がある。必要なら `httpx.stream()` に切り替える。
