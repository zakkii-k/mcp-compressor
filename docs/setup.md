# MCP Compressor セットアップガイド

GitHub Copilot の MCP レスポンスをローカル LLM で要約し、トークン消費を削減するプロキシのセットアップ手順です。

## 全体の流れ

```
GitHub Copilot → mcp_proxy.py → 実際の MCP サーバー
                     ↓（レスポンスをインターセプト）
                 パイプライン処理
                   1. TOON 変換 / JSON 圧縮
                   2. ログ重複除去 / ログ圧縮
                   3. LLM 要約（Ollama 経由、閾値超えのみ）
                     ↓
                 GitHub Copilot へ返却
```

---

## Step 1: Ollama のセットアップ（共通）

Ollama は Docker コンテナで動かします。Rancher Desktop が起動していれば `docker` コマンドが使えます。
**Windows / WSL どちらから実行しても同じです。**

### 1-1. Ollama コンテナを起動

```bash
docker run -d \
  --name ollama \
  -p 11434:11434 \
  -v ollama_data:/root/.ollama \
  --restart unless-stopped \
  ollama/ollama:latest
```

> **PowerShell の場合はバックスラッシュをバッククォートに変える:**
> ```powershell
> docker run -d `
>   --name ollama `
>   -p 11434:11434 `
>   -v ollama_data:/root/.ollama `
>   --restart unless-stopped `
>   ollama/ollama:latest
> ```

起動確認:

```bash
docker ps                  # ollama が Up になっていれば OK
curl http://localhost:11434  # {"status":"Ollama is running"} が返ればOK
```

### 1-2. モデルをダウンロード

| 品質順 | モデル | ストレージ | RAM使用 | 特徴 |
|:------:|--------|-----------|--------|------|
| 1 | `qwen2.5:7b` | ~4.7GB | ~4.5GB | **要約タスク最高品質** |
| 2 | `qwen3:4b` | ~2.6GB | ~3GB | 本プロキシが thinking mode を自動無効化して使用 |
| 2 | `gemma4:e4b` | ~2.9GB | ~3GB | Google製 Gemma4 の主力軽量モデル |
| 4 | `qwen2.5:3b` | ~2GB | ~2GB | **デフォルト推奨**。安定・高速 |
| 5 | `gemma3:4b` | ~2.9GB | ~3GB | 旧世代だが安定 |
| 6 | `gemma4:e2b` | ~1.6GB | ~1.5GB | RAM節約優先の場合のみ |

> モデルは Docker ボリューム（PC のストレージ）に保存されます。
> コンテナを再作成してもモデルは消えません。
> Ollama はリクエストが来た時点でモデルをメモリにロードするため、
> モデルの「起動」操作は不要です。

まとめて pull しておくのがおすすめ（全部で約14GB）:

```bash
docker exec ollama ollama pull qwen2.5:3b
docker exec ollama ollama pull qwen2.5:7b
docker exec ollama ollama pull qwen3:4b
docker exec ollama ollama pull gemma4:e4b
```

モデルの切り替えは `config.yaml` の 1 行だけ:

```yaml
model: "qwen2.5:7b"
```

---

## Step 2: Python 環境のセットアップ

### pyenv と uv どちらを使うか

| | pyenv + pip | uv |
|--|------------|-----|
| **概要** | Python バージョン管理 + pip でパッケージ管理 | Python バージョン管理・パッケージ管理・仮想環境を一括で担う Rust 製ツール |
| **インストール速度** | 普通 | pip より **10〜100倍速い** |
| **仮想環境** | 自分で `venv` を作って管理 | 自動で `.venv` を作って管理 |
| **既存環境との相性** | pyenv を使っているならそのまま使える | 新規プロジェクトや CI 向き |
| **このプロジェクトでの使い方** | `pip install httpx pyyaml python-toon` | `uv sync`（1コマンドで完結） |

**pyenv を使っているならそのまま pyenv + pip で問題ありません。**
uv の主な利点は速度と仮想環境の自動管理ですが、このプロジェクトでは依存が3つだけなので差はほぼ出ません。

---

### Windows の場合

#### 2-W1. リポジトリをクローン

```powershell
cd C:\Users\yourname\projects   # 任意のディレクトリ
git clone https://github.com/zakkii-k/mcp-compressor.git
cd mcp-compressor
```

#### 2-W2. Python バージョン確認（pyenv-win）

pyenv-win がインストール済みの場合:

```powershell
pyenv install 3.11.9   # 未インストールの場合
pyenv local 3.11.9
python --version       # Python 3.11.9 と表示されればOK
```

> **pyenv-win が入っていない場合:**
> ```powershell
> # Scoop 経由（推奨）
> scoop install pyenv
>
> # または pip 経由
> pip install pyenv-win --target "$HOME\.pyenv"
> ```

#### 2-W3. 依存パッケージをインストール

```powershell
cd C:\Users\yourname\projects\mcp-compressor
pip install httpx pyyaml python-toon
```

> **uv を使う場合:**
> ```powershell
> # uv のインストール（未インストールなら）
> irm https://astral.sh/uv/install.ps1 | iex
>
> # 依存パッケージ + 仮想環境をまとめてセットアップ
> uv sync
>
> # 実行時は python の代わりに uv run python を使う
> uv run python mcp_proxy.py --help
> ```

#### 2-W4. 動作確認

```powershell
python mcp_proxy.py --help
```

---

### WSL の場合

#### 2-L1. リポジトリをクローン

```bash
cd ~/projects   # 任意のディレクトリ
git clone https://github.com/zakkii-k/mcp-compressor.git
cd mcp-compressor
```

#### 2-L2. Python バージョン確認（pyenv）

pyenv がインストール済みの場合:

```bash
pyenv install 3.11.9   # 未インストールの場合
pyenv local 3.11.9
python --version       # Python 3.11.9 と表示されればOK
```

> **pyenv が入っていない場合:**
> ```bash
> curl https://pyenv.run | bash
> # .bashrc または .zshrc に以下を追記
> export PYENV_ROOT="$HOME/.pyenv"
> export PATH="$PYENV_ROOT/bin:$PATH"
> eval "$(pyenv init -)"
> # シェルを再起動してから pyenv install 3.11.9
> ```

#### 2-L3. 依存パッケージをインストール

```bash
cd ~/projects/mcp-compressor
pip install httpx pyyaml python-toon
```

> **uv を使う場合:**
> ```bash
> # uv のインストール（未インストールなら）
> curl -Ls https://astral.sh/uv/install.sh | sh
>
> # 依存パッケージ + 仮想環境をまとめてセットアップ
> uv sync
>
> # 実行時は python の代わりに uv run python を使う
> uv run python mcp_proxy.py --help
> ```

#### 2-L4. 動作確認

```bash
python mcp_proxy.py --help
```

---

## Step 3: GitHub Copilot の MCP 設定

VS Code の `.vscode/mcp.json`（またはユーザー設定の `settings.json`）を編集します。

---

### Windows の場合

VS Code が Windows 側で動いているため、Windows のパスを直接指定します。

**変更前:**

```json
{
  "servers": {
    "my-mcp-server": {
      "type": "stdio",
      "command": "node",
      "args": ["C:\\path\\to\\mcp-server.js"]
    }
  }
}
```

**変更後:**

```json
{
  "servers": {
    "my-mcp-server": {
      "type": "stdio",
      "command": "python",
      "args": [
        "C:\\Users\\yourname\\projects\\mcp-compressor\\mcp_proxy.py",
        "--config", "C:\\Users\\yourname\\projects\\mcp-compressor\\config.yaml",
        "--",
        "node", "C:\\path\\to\\mcp-server.js"
      ]
    }
  }
}
```

> `python` で pyenv-win の Python が使われるよう、`pyenv local 3.11.9` を
> mcp-compressor ディレクトリで実行しておくこと。

> **uv を使う場合の MCP 設定:**
> ```json
> {
>   "command": "uv",
>   "args": [
>     "run", "--project", "C:\\Users\\yourname\\projects\\mcp-compressor",
>     "python", "mcp_proxy.py",
>     "--config", "C:\\Users\\yourname\\projects\\mcp-compressor\\config.yaml",
>     "--",
>     "node", "C:\\path\\to\\mcp-server.js"
>   ]
> }
> ```

---

### WSL の場合（Windows 側の VS Code から）

VS Code が Windows 側で動いているため `wsl -e` を挟みます。

**変更後:**

```json
{
  "servers": {
    "my-mcp-server": {
      "type": "stdio",
      "command": "wsl",
      "args": [
        "-e", "python",
        "/home/yourname/projects/mcp-compressor/mcp_proxy.py",
        "--config", "/home/yourname/projects/mcp-compressor/config.yaml",
        "--",
        "node", "/path/to/mcp-server.js"
      ]
    }
  }
}
```

> WSL 内で pyenv を使っている場合、`wsl -e python` は pyenv の Python を使います。
> ただし WSL の初期化が毎回走るため、Windows 側に置く方法より若干起動が遅いです。

> **uv を使う場合の MCP 設定（WSL）:**
> ```json
> {
>   "command": "wsl",
>   "args": [
>     "-e", "uv", "run",
>     "--project", "/home/yourname/projects/mcp-compressor",
>     "python", "mcp_proxy.py",
>     "--config", "/home/yourname/projects/mcp-compressor/config.yaml",
>     "--",
>     "node", "/path/to/mcp-server.js"
>   ]
> }
> ```

---

### 複数の MCP サーバーがある場合

各サーバーを個別にラップします。`mcp_proxy.py` は `--` 以降を実際のサーバーコマンドとして起動します。

```json
{
  "servers": {
    "server-a": {
      "type": "stdio",
      "command": "python",
      "args": ["C:\\...\\mcp_proxy.py", "--", "node", "C:\\...\\server-a.js"]
    },
    "server-b": {
      "type": "stdio",
      "command": "python",
      "args": ["C:\\...\\mcp_proxy.py", "--", "uvx", "mcp-server-fetch"]
    }
  }
}
```

---

## Step 4: 動作確認

### Ollama の疎通確認（共通）

```bash
curl -s http://localhost:11434   # {"status":"Ollama is running"}
docker exec ollama ollama list   # ダウンロード済みモデル一覧
```

### パイプラインのテスト（Ollama 不要）

**Windows:**

```powershell
cd C:\Users\yourname\projects\mcp-compressor
python -m pytest tests/test_proxy.py -v
```

**WSL:**

```bash
cd ~/projects/mcp-compressor
python -m pytest tests/test_proxy.py -v
```

Ollama が起動していれば LLM 要約テストも自動で有効になります。

### MCP Inspector で対話確認（npx が使える場合）

```bash
npx @modelcontextprotocol/inspector \
  python mcp_proxy.py --log-level INFO \
  -- \
  python tests/mock_server.py
```

ブラウザが `http://localhost:5173` で開き、ツールを呼び出して動作確認できます。

---

## トラブルシューティング

### Ollama に接続できない

```bash
docker ps            # ollama コンテナが起動しているか
docker start ollama  # 停止していた場合
docker logs ollama   # エラーログ確認
```

### `python` コマンドが見つからない / バージョンが違う

```bash
# pyenv のバージョン確認
pyenv versions
pyenv local 3.11.9   # プロジェクトディレクトリで実行
python --version
```

### `import httpx` エラー

```bash
pip install httpx pyyaml python-toon
```

### MCP サーバーが起動しない

```bash
# --log-level DEBUG でプロキシのログを確認
python mcp_proxy.py --log-level DEBUG -- node /path/to/server.js
```

---

## アンインストール

```bash
# Ollama コンテナとモデルデータをすべて削除
docker stop ollama
docker rm ollama
docker volume rm ollama_data

# モデルだけ削除してコンテナは残す場合
docker exec ollama ollama rm qwen2.5:3b
```

---

## 動作確認: MCP Inspector（Copilot のトークンを使わずにテスト）

| 方法 | コマンド | Ollama 必要 |
|------|---------|------------|
| pytest 自動テスト | `python -m pytest tests/test_proxy.py -v` | パイプラインのみなら不要 |
| MCP Inspector | `npx @modelcontextprotocol/inspector python mcp_proxy.py -- python tests/mock_server.py` | LLM要約のみ必要 |

テスト用ツール一覧:

| ツール名 | 期待される処理 |
|----------|--------------|
| `get_small_response` | そのまま通過（閾値以下） |
| `get_large_json` | TOON 変換または minify |
| `get_large_log` | ログ重複除去・圧縮 |
| `get_large_text` | LLM 要約（Ollama 起動時のみ） |
