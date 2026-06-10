# MCP Summarizer セットアップガイド

GitHub Copilot の MCP レスポンスをローカル LLM で要約し、トークン消費を削減するプロキシのセットアップ手順です。

## 全体の流れ

```
GitHub Copilot → mcp_proxy.py → 実際の MCP サーバー
                     ↓（レスポンスをインターセプト）
                 パイプライン処理
                   1. JSON 圧縮（minify）
                   2. ログ圧縮（先頭/エラー/末尾を抽出）
                   3. LLM 要約（Ollama 経由、閾値超えのみ）
                     ↓
                 GitHub Copilot へ返却
```

---

## 前提条件

- Windows 11 + PowerShell
- Rancher Desktop（インストール済み）
- Python 3.11 以上（WSL2 内 or Windows 直接）

---

## Step 1: Ollama のセットアップ（Rancher Desktop / Docker）

### 1-1. Ollama コンテナを起動

PowerShell で実行:

```powershell
# Ollama コンテナを起動（GPU なし・CPU モード）
docker run -d `
  --name ollama `
  -p 11434:11434 `
  -v ollama_data:/root/.ollama `
  --restart unless-stopped `
  ollama/ollama:latest
```

> **GPU (NVIDIA) を使う場合（VRAM が使えるとさらに高速）:**
> ```powershell
> docker run -d `
>   --name ollama `
>   -p 11434:11434 `
>   -v ollama_data:/root/.ollama `
>   --restart unless-stopped `
>   --gpus all `
>   ollama/ollama:latest
> ```

### 1-2. 起動確認

```powershell
docker ps
# ollama コンテナが "Up" になっていれば OK

curl http://localhost:11434
# {"status":"Ollama is running"} が返ればOK
```

---

## Step 2: モデルのダウンロード

### 推奨モデル（16GB RAM 環境）

| モデル | RAM目安 | 特徴 |
|--------|--------|------|
| `qwen2.5:3b` | ~2GB | **デフォルト推奨**。安定・高速・シンプル |
| `qwen3:4b` | ~3GB | Qwen2.5より高品質。thinking mode は本プロキシが自動無効化 |
| `gemma4:e4b` | ~3GB | Google製 Gemma4 の主力軽量モデル。gemma3:4b より高品質 |
| `gemma4:e2b` | ~1.5GB | Gemma4 の最小版。RAM を節約したい場合のみ |
| `qwen2.5:7b` | ~4.5GB | 要約精度を上げたい場合 |
| `gemma3:4b` | ~3GB | 旧世代だが安定。gemma4:e4b が利用可能なら不要 |

> **Qwen3 について**: thinking mode（内部推論）がデフォルトでオンのため、
> 要約タスクでは無駄なトークンが発生します。本プロキシでは自動的に無効化するため
> 意識せず使えます。

### モデルをダウンロード

```powershell
# デフォルト推奨（qwen2.5:3b）
docker exec ollama ollama pull qwen2.5:3b

# より高品質な代替（どちらかお好みで）
docker exec ollama ollama pull qwen3:4b
docker exec ollama ollama pull gemma4:e4b
```

### ダウンロード確認

```powershell
docker exec ollama ollama list
```

### モデルの切り替え方

`config.yaml` の `model:` を変更するだけです:

```yaml
# qwen2.5:3b から gemma3:4b に切り替える場合
model: "gemma3:4b"
```

---

## Step 3: Python 環境のセットアップ

### 3-1. uv のインストール（推奨）

```powershell
# PowerShell
irm https://astral.sh/uv/install.ps1 | iex
```

### 3-2. 依存パッケージのインストール

```powershell
cd C:\path\to\mcp-summarizer   # このリポジトリのパス
uv sync
```

WSL2 を使っている場合:

```bash
cd /path/to/mcp-summarizer
uv sync
```

---

## Step 4: GitHub Copilot の MCP 設定を変更

### VS Code の場合（`.vscode/mcp.json` または `settings.json`）

**変更前（直接 MCP サーバーを指定）:**

```json
{
  "servers": {
    "my-mcp-server": {
      "type": "stdio",
      "command": "node",
      "args": ["/path/to/mcp-server.js"]
    }
  }
}
```

**変更後（プロキシ経由）:**

```json
{
  "servers": {
    "my-mcp-server": {
      "type": "stdio",
      "command": "uv",
      "args": [
        "run",
        "--project", "C:\\path\\to\\mcp-summarizer",
        "python", "mcp_proxy.py",
        "--config", "C:\\path\\to\\mcp-summarizer\\config.yaml",
        "--",
        "node", "/path/to/mcp-server.js"
      ]
    }
  }
}
```

> **WSL2 経由で Python を動かす場合:**
> ```json
> {
>   "command": "wsl",
>   "args": ["-e", "uv", "run", "--project", "/path/to/mcp-summarizer",
>            "python", "mcp_proxy.py", "--", "node", "/path/to/server.js"]
> }
> ```

### 複数の MCP サーバーがある場合

各サーバーの `command` と `args` を上記のパターンでラップするだけです。`mcp_proxy.py` は `--` 以降を実際のサーバーコマンドとして起動します。

---

## Step 5: 動作確認

### Ollama の疎通確認

```powershell
# 要約テスト
$body = '{"model":"qwen2.5:3b","prompt":"以下を一文で要約: Pythonはシンプルで読みやすい文法を持つプログラミング言語です。","stream":false}'
curl -X POST http://localhost:11434/api/generate -H "Content-Type: application/json" -d $body
```

### プロキシの単体テスト（echo コマンドで MCP を模擬）

```powershell
# Windows の場合（cmd/PowerShell）
echo '{"jsonrpc":"2.0","id":1,"result":{"content":[{"type":"text","text":"test response"}]}}' | `
  uv run python mcp_proxy.py -- cmd /c type CON
```

### ログレベルを上げてデバッグ

```powershell
# INFO レベルで処理状況を確認
uv run python mcp_proxy.py --log-level INFO -- node /path/to/server.js
```

---

## 設定のカスタマイズ

`config.yaml` で動作を細かく調整できます:

```yaml
# 閾値を下げると要約が増える、上げると減る
threshold_chars: 3000   # デフォルト: 5000

# 特定のパイプラインステージを無効化
pipeline:
  - json_compressor     # JSON minify のみ（LLM 要約なし）
  # - log_compressor    # ← コメントアウトで無効
  # - llm_summarizer    # ← LLM 要約を無効にしたい場合
```

---

## 元データの確認（可逆性）

LLM 要約されたレスポンスには元データのファイルパスが含まれます:

```
[LLM要約済み | モデル: qwen2.5:3b | 元データ: originals/original_20240610_143022_123456.txt]

（要約内容）
```

`originals/` ディレクトリに元のレスポンスが保存されているため、必要に応じて参照できます。

---

## トラブルシューティング

### Ollama に接続できない

```powershell
docker ps       # ollama コンテナが起動しているか確認
docker logs ollama  # エラーログを確認
```

### モデルが見つからない

```powershell
docker exec ollama ollama list   # インストール済みモデルを確認
docker exec ollama ollama pull qwen2.5:3b   # 再度 pull
```

### Python パッケージが見つからない

```powershell
uv sync   # 依存関係を再インストール
```

### MCP サーバーが起動しない

`--log-level DEBUG` オプションでプロキシのデバッグログを有効にして確認してください。

---

---

## 動作確認: MCP Inspector で Copilot を使わずにテスト

GitHub Copilot のトークンを消費せずに、プロキシ＋要約の動作を確認する方法です。

### テスト構成

```
MCP Inspector (ブラウザ UI)
        ↓ stdio
  mcp_proxy.py        ← レスポンスをインターセプト
        ↓ stdio
  tests/mock_server.py ← 大きなレスポンスを返すモックサーバー
```

### A) pytest で自動テスト（推奨・最速）

```powershell
cd C:\path\to\mcp-summarizer

# Ollama なしでパイプラインのみテスト（JSON圧縮・ログ圧縮）
uv run pytest tests/test_proxy.py -v

# Ollama 起動後にLLM要約も含めてテスト
uv run pytest tests/test_proxy.py -v   # TestLLMSummarizer が自動で有効化される
```

テスト内容:
| テスト | 確認内容 | Ollama 必要 |
|--------|----------|-------------|
| `test_handshake_works` | MCP 初期化が通る | 不要 |
| `test_tools_list` | ツール一覧が取得できる | 不要 |
| `test_small_response_passes_through` | 閾値以下はそのまま通過 | 不要 |
| `test_json_compressor` | 大きな JSON が minify される | 不要 |
| `test_log_compressor` | 大量ログが圧縮される | 不要 |
| `test_large_text_is_summarized` | LLM 要約が動く | **必要** |
| `test_original_is_saved` | 元データが保存される | **必要** |

### B) MCP Inspector でブラウザから対話確認（npx が使える場合）

```powershell
# npx でインストール不要、その場実行
npx @modelcontextprotocol/inspector `
  uv run python mcp_proxy.py --log-level INFO `
  -- `
  python tests/mock_server.py
```

ブラウザが `http://localhost:5173` で開く。
左ペインの **Tools** から以下のツールを呼び出して動作確認できる:

| ツール名 | レスポンス | 期待される処理 |
|----------|-----------|---------------|
| `get_small_response` | 小さいテキスト | そのまま通過 |
| `get_large_json` | 大きな JSON | minify されて返る |
| `get_large_log` | 200行のログ | 先頭/エラー/末尾に圧縮 |
| `get_large_text` | 大量テキスト | LLM 要約（Ollama 起動時のみ） |

### C) コマンドラインで手動確認（最もシンプル）

PowerShell:

```powershell
# モック → プロキシ の出力を直接見る（initializeレスポンスが返れば動作OK）
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}' | `
  uv run python mcp_proxy.py -- python tests/mock_server.py
```

WSL2:

```bash
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}
{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"get_large_log","arguments":{}}}' \
  | uv run python mcp_proxy.py -- python tests/mock_server.py
```

---

## アンインストール

```powershell
# Ollama コンテナの停止・削除
docker stop ollama
docker rm ollama
docker volume rm ollama_data

# モデルデータのみ削除（コンテナは残す）
docker exec ollama ollama rm qwen2.5:3b
```
