# mcp-compressor telemetry stack

mcp-compressor の圧縮効果と GitHub Copilot のトークン使用量を Grafana で可視化するための Docker スタックです。

**mcp-compressor 本体のコードは含まれていません。**  
このディレクトリだけ入手すれば計測インフラとして動作します。

---

## 含まれるもの

```
telemetry/
  docker-compose.yml            ← 起動はここから
  otel-collector-config.yaml    ← メトリクス（→Prometheus）とトレース（→Tempo）の振り分け設定
  prometheus.yml                ← スクレイプ設定
  tempo-config.yaml             ← トレース DB 設定
  grafana/
    provisioning/               ← 起動時に自動でデータソース・ダッシュボードを登録
    dashboards/
      mcp-compressor.json       ← 圧縮率ダッシュボード（Prometheus）
      copilot-telemetry.json    ← Copilot トークン使用量ダッシュボード（Tempo）
```

---

## 起動

```bash
docker compose up -d
```

| サービス | URL |
|---|---|
| **Grafana**（ダッシュボード） | http://localhost:3000 |
| Prometheus | http://localhost:9090 |
| Tempo | http://localhost:3200 |
| otel-collector（受信口） | localhost:**4318** |

ログイン不要。Grafana を開くと「MCP Compressor」と「GitHub Copilot Telemetry」のダッシュボードが自動で表示されます。

---

## データを送る側の設定

### mcp-compressor からメトリクスを送る

`config.yaml` に追記：

```yaml
telemetry:
  enabled: true
  endpoint: "http://localhost:4318"
```

依存パッケージのインストール（mcp-compressor のプロジェクトで実行）：

```powershell
pip install "mcp-compressor[telemetry-tokens]"
```

### GitHub Copilot からトレースを送る

VS Code の settings.json に追記：

```json
"github.copilot.chat.otel.enabled": true,
"github.copilot.chat.otel.otlpEndpoint": "http://localhost:4318",
"github.copilot.chat.otel.captureContent": true
```

追記後は **VS Code を再起動**してください。

---

## 停止

```bash
docker compose down        # コンテナ停止（データは保持）
docker compose down -v     # コンテナ停止 + データ全削除
```

---

## 詳細ドキュメント

mcp-compressor 本体のリポジトリの `docs/telemetry/` を参照してください：

- `setup.md` … 手順の詳細・トラブルシューティング
- `how-it-works.md` … 各メトリクス・トレースの意味とダッシュボードの読み方
