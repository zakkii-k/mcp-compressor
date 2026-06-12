# mcp-compressor telemetry

mcp-compressor の圧縮効果と GitHub Copilot のトークン使用量を可視化するサーバーです。

**外部パッケージ不要 / 外部への通信なし / Python 標準ライブラリのみ**

---

## 起動方法

### Python で直接起動（推奨）

```bash
python server.py
```

### Docker で起動

```bash
docker compose up -d
```

| ポート | 用途 |
|---|---|
| **3000** | ダッシュボード → http://localhost:3000 |
| **4318** | データ受信口（mcp-compressor と Copilot が送信） |

---

## データを送る側の設定

### mcp-compressor

`config.yaml` に追記：

```yaml
telemetry:
  enabled: true
  endpoint: "http://localhost:4318"
```

（外部パッケージのインストールは不要になりました。tiktoken でトークン推定精度を上げたい場合のみ `pip install tiktoken`）

### GitHub Copilot（VS Code）

VS Code の `settings.json` に追記：

```json
"github.copilot.chat.otel.enabled": true,
"github.copilot.chat.otel.otlpEndpoint": "http://localhost:4318",
"github.copilot.chat.otel.captureContent": true
```

追記後は **VS Code を再起動**してください。

---

## オプション

```
python server.py --ingest-port 4318 --dashboard-port 3000 --db telemetry.db
```

---

## セキュリティ・ライセンス

| 項目 | 内容 |
|---|---|
| 外部通信 | **なし**（全データはローカル SQLite に保存） |
| 依存パッケージ | **なし**（Python 3.11+ stdlib のみ） |
| ライセンス | Python Software Foundation License（商用利用可） |
| Docker イメージ | `python:3.11-slim`（PSF License、外部送信なし） |
