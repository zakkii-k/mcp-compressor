# テレメトリ セットアップガイド

---

## 全体像

```
VS Code + Copilot ──(OTLP JSON)──┐
                                  ├──▶ telemetry/server.py:4318
mcp-compressor ──(HTTP JSON)──────┘         │
                                            ▼
                                     SQLite（ローカル）
                                            │
                                 ブラウザ ◀─ :3000 ダッシュボード
```

**使用技術:** Python stdlib のみ。Grafana・Prometheus・Tempo 等の外部ツール不要。

---

## ステップ 1：server.py を起動する

`telemetry/` ディレクトリで：

```bash
# Python で直接起動（推奨）
python server.py

# または Docker で起動
docker compose up -d
```

http://localhost:3000 でダッシュボードが開きます。

---

## ステップ 2：mcp-compressor を設定する

`config.yaml` に追記するだけです：

```yaml
telemetry:
  enabled: true
  endpoint: "http://localhost:4318"
```

**パッケージのインストールは不要になりました。**

トークン推定精度を上げたい場合のみ（任意）：

```powershell
pip install tiktoken
```

設定後は VS Code を再起動して mcp-compressor を再起動させます。

---

## ステップ 3：VS Code の settings.json を設定する

VS Code の **ユーザー設定**（`Ctrl+Shift+P` → "Open User Settings JSON"）に追加します：

```json
{
  "github.copilot.chat.otel.enabled": true,
  "github.copilot.chat.otel.otlpEndpoint": "http://localhost:4318",
  "github.copilot.chat.otel.captureContent": true
}
```

設定後は **VS Code を再起動**してください。

---

## ステップ 4：ダッシュボードを確認する

http://localhost:3000 を開きます。

- 上段：mcp-compressor の圧縮効果（削減率・サーバー別・ステージ別）
- 下段：Copilot の実際のトークン使用量（入出力・モデル別・最近の呼び出し）

データが表示されるまで：VS Code で Copilot を使い → 10〜30秒待つ → ページをリロード。

---

## セキュリティとライセンス

| 項目 | 内容 |
|---|---|
| 外部通信 | **なし**（全データはローカル SQLite に保存） |
| 依存パッケージ | **なし**（Python 3.11+ stdlib のみ） |
| ライセンス | Python PSF License（企業利用可） |

---

## よくある問題

**「データなし」と表示される**
- server.py が起動しているか確認（Ctrl+C で止まっていないか）
- config.yaml の `telemetry.enabled: true` を確認
- VS Code を完全に再起動（ウィンドウを閉じて再度開く）

**停止する**
```bash
Ctrl+C          # 直接起動の場合
docker compose down   # Docker の場合（-v で DB も削除）
```
