# mcp-compressor

GitHub Copilot の MCP レスポンスをインターセプトし、トークン消費を削減するプロキシ。

## 解決する問題

| 問題 | 対策 |
|------|------|
| MCP のレスポンスが大きくてトークンを食う | 圧縮パイプラインで削減 |
| ツール定義が多くて毎ターン固定コストがかかる | メタツール方式で常に2ツールだけ公開 |
| 内部・外部 MCP が混在していてインターセプトが難しい | wrap モードで一箇所に集約 |

---

## 仕組み

### 圧縮パイプライン

MCP のレスポンスを以下の順で処理する。

```
MCP レスポンス
  ↓ TOON 変換        JSON を 36〜64% 削減（LLM 可読のまま）
  ↓ ログ重複除去      繰り返しパターンを集約、最大 98% 削減
  ↓ ログ圧縮         大量ログを先頭 / エラー / 末尾に絞る
  ↓ LLM 要約        閾値超えのみ Ollama で要約（元データ保存）
  ↓
Copilot へ返却
```

### プロキシモード

#### stdio モード（デフォルト）

MCP サーバーを1つずつラップする。既存の設定に1行追加するだけ。

```
Copilot → mcp-compressor → 実際の MCP サーバー（子プロセス）
```

#### wrap モード

`mcp.servers.json` に書いた全サーバーに接続し、Copilot には1つのサーバーとして見せる。内部（stdio）・外部（SSE/HTTP）問わず一箇所でインターセプトできる。

```
Copilot → mcp-compressor ┬→ filesystem サーバー（stdio）
                          ├→ atlassian サーバー（SSE）
                          └→ github サーバー（SSE）
```

**メタツール方式（デフォルト）**

Copilot に公開するのは常に2ツールだけ。

```
mcp__list_tools(query?)              ← ツール一覧を返す（TOON 圧縮対象）
mcp__invoke_tool(server, tool, args) ← ツールを実行する
```

ツール定義は LLM に毎ターン送られる。ツールが多いほど固定コストが増えるため、
常に2つに絞ることで削減する。

```
通常方式: ツール定義 × 30個 × 会話10ターン = 300回分の定義コスト
メタツール: ツール定義 × 2個 × 会話10ターン = 20回分
           + list_tools の結果（TOON 圧縮済み）が履歴に1回
```

---

## セットアップ

詳細は [docs/setup.md](docs/setup.md) を参照。

### 1. Ollama を起動

WSL または PowerShell どちらでも同じ（Rancher Desktop が起動していれば `docker` が使える）:

```bash
docker compose up -d
docker exec ollama ollama pull qwen2.5:3b
```

### 2. mcp-compressor のインストール

3通りある。**Docker が一番シンプル**。

---

#### A. Docker（推奨・Python 環境不要）

```bash
git clone https://github.com/zakkii-k/mcp-compressor.git
cd mcp-compressor
docker build -t mcp-compressor .
```

VS Code の MCP 設定で `docker run` を指定するだけで動く。

---

#### B. Windows ネイティブ Python（VS Code が Windows 側の場合）

VS Code が Windows で動いているなら、Python も Windows 側に置くのがシンプル。
MCP 設定に `python` を直接書けばいい。

```powershell
# PowerShell または WSL から
git clone https://github.com/zakkii-k/mcp-compressor.git
cd mcp-compressor

# pyenv-win でバージョン指定（インストール済みの場合）
pyenv local 3.11.9

pip install httpx pyyaml python-toon
```

---

#### C. WSL 内 Python（VS Code が Windows 側の場合は非推奨）

WSL 内に置くと MCP 設定で `wsl -e python ...` を挟む必要があり冗長になる。
WSL で VS Code を開いて開発する場合（`code .` を WSL から実行）は問題ない。

```bash
git clone https://github.com/zakkii-k/mcp-compressor.git
cd mcp-compressor
pip install httpx pyyaml python-toon
```

---

## 使い方

### stdio モード

既存の MCP 設定を `mcp-compressor` でラップする。

**変更前:**
```json
{
  "servers": {
    "filesystem": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path"]
    }
  }
}
```

**変更後:**
```json
{
  "servers": {
    "filesystem": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "mcp_compressor", "--",
               "npx", "-y", "@modelcontextprotocol/server-filesystem", "/path"]
    }
  }
}
```

Docker の場合:
```json
{
  "command": "docker",
  "args": ["run", "--rm", "-i", "mcp-compressor", "--",
           "npx", "-y", "@modelcontextprotocol/server-filesystem", "/path"]
}
```

### wrap モード

全 MCP サーバーを1エントリに集約する。

**Step 1:** 既存の `.vscode/mcp.json` の `servers` 部分を `mcp.servers.json` にコピー。

```json
// mcp.servers.json
{
  "servers": {
    "filesystem": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path"]
    },
    "atlassian": {
      "type": "sse",
      "url": "https://mcp.atlassian.com/v1/sse"
    }
  }
}
```

`mcp.servers.example.json` をコピーして編集してください。

**Step 2:** `.vscode/mcp.json` を書き換え。

```json
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
```

**Copilot から見えるツール:**

```
mcp__list_tools   → query="atlassian" で Jira 関連ツールを検索できる
mcp__invoke_tool  → server="atlassian", tool="create_issue" で実行
```

`mcp__list_tools` の description にサーバー名と主要ツールが含まれるため、
Copilot はユーザーの意図に応じた query を組み立てられる。

プレフィックス方式に戻す場合は `--no-meta-tools` を追加。

---

## 設定

`config.yaml`:

```yaml
# 要約閾値（パイプライン処理後にこの文字数を超えたら LLM 要約）
threshold_chars: 5000

# 使用モデル（1行変更で切り替え）
model: "qwen2.5:3b"

# パイプラインステージ（実行順）
pipeline:
  - toon_converter      # JSON → TOON 形式（36〜64% 削減）
  - log_deduplicator    # 繰り返しパターンのログを集約
  - log_compressor      # ログの先頭/エラー/末尾を抽出
  - llm_summarizer      # LLM で要約（Ollama 必要）
```

### 推奨モデル（16GB RAM）

| 品質順 | モデル | RAM | 備考 |
|:------:|--------|-----|------|
| 1 | `qwen2.5:7b` | ~4.5GB | 要約タスク最高品質 |
| 2 | `qwen3:4b` | ~3GB | thinking mode を自動無効化して使用 |
| 2 | `gemma4:e4b` | ~3GB | Google 製、バランス良好 |
| 4 | `qwen2.5:3b` | ~2GB | **デフォルト**。安定・高速 |

### 環境変数

| 変数 | 内容 | デフォルト |
|------|------|-----------|
| `OLLAMA_URL` | Ollama の URL（Docker 内は自動設定済み） | `http://localhost:11434` |
| `MCP_MODEL` | 使用モデル | `qwen2.5:3b` |
| `MCP_THRESHOLD` | 要約閾値（文字数） | `5000` |

---

## 圧縮手法の詳細

[docs/compression-techniques.md](docs/compression-techniques.md) を参照。

| 手法 | 削減率 | LLM 不要 | 対象 |
|------|--------|---------|------|
| TOON 変換 | 36〜64% | ✅ | JSON 全般 |
| ログ重複除去 | 80〜98% | ✅ | 繰り返しパターンのログ |
| ログ先頭/エラー/末尾 | 60〜80% | ✅ | 大量ログ |
| LLM 要約 | 70〜90% | ❌ | 汎用テキスト |

---

## テスト

Ollama なしでパイプラインと wrap モードのテストが実行できる。

```bash
pip install pytest
pytest tests/ -v
```

Ollama 起動後は LLM 要約テストも自動で有効になる。

---

## プロジェクト構成

```
mcp-compressor/
├── mcp_compressor/
│   ├── main.py              # エントリーポイント（--mode stdio/wrap/http）
│   ├── config.py            # 設定読み込み（環境変数対応）
│   ├── pipeline/            # 圧縮パイプライン
│   │   ├── toon_converter.py
│   │   ├── log_deduplicator.py
│   │   ├── log_compressor.py
│   │   ├── json_compressor.py
│   │   ├── json_table_converter.py
│   │   └── llm_summarizer.py
│   └── proxy/
│       ├── stdio_proxy.py     # stdio モード（ローカル MCP）
│       ├── wrap_proxy.py      # wrap モード（全 MCP を集約）
│       ├── server_connection.py  # stdio/SSE サーバー接続管理
│       └── http_proxy.py      # HTTP モード（未実装・スタブ）
├── tests/
├── docs/
│   ├── setup.md
│   └── compression-techniques.md
├── config.yaml
├── mcp.servers.example.json
├── Dockerfile
└── docker-compose.yml
```
