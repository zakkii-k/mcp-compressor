# mcp-compressor

GitHub Copilot の MCP レスポンスをインターセプトし、ローカル LLM で要約してトークン消費を削減するプロキシ。

## 仕組み

```
GitHub Copilot → mcp-compressor → 実際の MCP サーバー
                      ↓ レスポンスをインターセプト
                  圧縮パイプライン
                    1. TOON 変換（JSON を 36〜64% 削減）
                    2. ログ重複除去（繰り返しログを最大 98% 削減）
                    3. ログ圧縮（先頭 / エラー / 末尾を抽出）
                    4. LLM 要約（Ollama 経由、上記で閾値超えのみ）
                      ↓ 要約済みレスポンスを返却
                GitHub Copilot
```

LLM 要約時は元データをファイルに保存するため、必要に応じて参照できます（可逆圧縮）。

## セットアップ

詳細は [docs/setup.md](docs/setup.md) を参照してください。

### クイックスタート

**1. Ollama を起動**

```bash
docker compose up -d
docker exec ollama ollama pull qwen2.5:3b
```

**2. Python 環境をセットアップ（pyenv + pip）**

```bash
git clone https://github.com/zakkii-k/mcp-compressor.git
cd mcp-compressor
pip install httpx pyyaml python-toon
```

**3. VS Code の MCP 設定を変更**

```json
{
  "servers": {
    "my-server": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "mcp_compressor", "--", "node", "/path/to/mcp-server.js"]
    }
  }
}
```

### Docker で使う場合（Python 環境不要）

```bash
docker build -t mcp-compressor .
```

```json
{
  "servers": {
    "my-server": {
      "type": "stdio",
      "command": "docker",
      "args": ["run", "--rm", "-i", "mcp-compressor", "--", "node", "/path/to/server.js"]
    }
  }
}
```

## 設定

`config.yaml` で動作を調整できます。

```yaml
# 要約閾値（この文字数を超えたら LLM 要約を試みる）
threshold_chars: 5000

# 使用モデル（1行変更で切り替え）
model: "qwen2.5:3b"

# パイプラインステージ
pipeline:
  - toon_converter      # JSON を TOON 形式に変換
  - log_deduplicator    # 繰り返しパターンのログを集約
  - log_compressor      # ログの先頭/エラー/末尾を抽出
  - llm_summarizer      # LLM で要約（Ollama 必要）
```

### 推奨モデル（16GB RAM 環境）

| 品質順 | モデル | RAM 使用量 |
|:------:|--------|-----------|
| 1 | `qwen2.5:7b` | ~4.5GB |
| 2 | `qwen3:4b` | ~3GB |
| 2 | `gemma4:e4b` | ~3GB |
| 4 | `qwen2.5:3b` | ~2GB（デフォルト） |

### 環境変数

| 変数 | 内容 | デフォルト |
|------|------|-----------|
| `OLLAMA_URL` | Ollama の URL | `http://localhost:11434` |
| `MCP_MODEL` | 使用モデル | `qwen2.5:3b` |
| `MCP_THRESHOLD` | 要約閾値（文字数） | `5000` |

## 圧縮手法

詳細は [docs/compression-techniques.md](docs/compression-techniques.md) を参照。

| 手法 | 削減率の目安 | LLM 不要 |
|------|------------|---------|
| TOON 変換 | 36〜64% | ✅ |
| ログ重複除去 | 80〜98% | ✅ |
| ログ先頭/エラー/末尾 | 60〜80% | ✅ |
| LLM 要約 | 70〜90% | ❌（Ollama 必要） |

## 動作モード

### stdio モード（デフォルト）

既存の MCP サーバーを1つずつラップする。

```json
{ "command": "python", "args": ["-m", "mcp_compressor", "--", "node", "server.js"] }
```

### wrap モード

全 MCP サーバーを束ねて Copilot に1つのサーバーとして見せる。
内部・外部（Atlassian 等）問わず一箇所でインターセプトできる。

**セットアップ:**

1. 既存の `.vscode/mcp.json` の内容を `mcp.servers.json` にコピー
2. `.vscode/mcp.json` を書き換え:

```json
{
  "servers": {
    "mcp-compressor": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "mcp_compressor", "--mode", "wrap", "--mcp-config", "mcp.servers.json"]
    }
  }
}
```

ツール名は `{サーバー名}__{ツール名}` 形式（例: `filesystem__read_file`、`atlassian__create_issue`）。

`mcp.servers.example.json` を参考にしてください。

## 対応 MCP

| 種別 | 例 | 対応状況 |
|------|-----|---------|
| stdio（ローカル） | mcp-server-filesystem, mcp-server-fetch | ✅ 対応済み |
| HTTP/SSE（外部） | Atlassian, GitHub 等 | ✅ wrap モードで対応 |

## テスト

Ollama なしでパイプラインのテストが実行できます。

```bash
pip install pytest
pytest tests/ -v
```

## プロジェクト構成

```
mcp-compressor/
├── mcp_compressor/
│   ├── main.py              # エントリーポイント
│   ├── config.py            # 設定読み込み
│   ├── pipeline/            # 圧縮パイプライン
│   │   ├── toon_converter.py
│   │   ├── log_deduplicator.py
│   │   ├── log_compressor.py
│   │   ├── json_compressor.py
│   │   ├── json_table_converter.py
│   │   └── llm_summarizer.py
│   └── proxy/               # プロキシモード
│       ├── stdio_proxy.py   # ローカル MCP 対応（実装済み）
│       └── http_proxy.py    # 外部 MCP 対応（未実装）
├── tests/
├── docs/
├── config.yaml
├── Dockerfile
└── docker-compose.yml
```
