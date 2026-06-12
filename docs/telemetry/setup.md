# テレメトリ セットアップガイド

mcp-compressor がどの程度レスポンスを圧縮しているか、GitHub Copilot が実際に何トークン使っているかを可視化するための手順です。

---

## 全体像

```
┌─────────────────────────────────────────────┐
│ あなたのPC                                   │
│                                              │
│  VS Code + Copilot ──(トレース)──┐           │
│                                  │           │
│  mcp-compressor ──(メトリクス)──▶ otel-collector:4318
│                                             │
│  otel-collector ──┬──(メトリクス)──▶ Prometheus:9090
│                   └──(トレース)───▶ Tempo:3200
│                                             │
│  Grafana:3000 ◀── Prometheus + Tempo        │
└─────────────────────────────────────────────┘
```

**用語メモ:**
- **メトリクス** … 「圧縮前 1200文字 → 圧縮後 300文字」のような数値の記録
- **トレース** … 「Copilot がこの LLM 呼び出しで 800 input tokens 使った」のような処理の記録
- **otel-collector** … メトリクスとトレースを受け取って振り分けるハブ
- **Prometheus** … メトリクスの時系列データベース
- **Tempo** … トレースの時系列データベース
- **Grafana** … Prometheus + Tempo のデータをグラフで見る画面

---

## ステップ 1：Docker スタックを起動する

テレメトリ用の設定ファイルはすべて **`telemetry/` ディレクトリ**にまとめてあります。

```bash
cd telemetry
docker compose up -d
```

起動を確認：

```bash
docker compose ps
```

全コンテナが `running` になったら OK。起動に10〜20秒かかることがあります。

| サービス | URL | 用途 |
|---|---|---|
| Grafana | http://localhost:3000 | ダッシュボード |
| Prometheus | http://localhost:9090 | メトリクス確認（上級者向け） |
| Tempo | http://localhost:3200 | トレース確認（上級者向け） |
| otel-collector | localhost:4318 | データ受信口（直接は開かない） |

> **mcp-compressor を fork していない場合:** `telemetry/` ディレクトリだけ入手して `docker compose up -d` するだけで動きます。

---

## ステップ 2：mcp-compressor を設定する

プロジェクトの `config.yaml` に追記します：

```yaml
telemetry:
  enabled: true
  endpoint: "http://localhost:4318"
```

次に、テレメトリ用のパッケージをインストールします：

```powershell
# トークン推定も含む場合（推奨）
pip install "mcp-compressor[telemetry-tokens]"

# OTel のみの場合（tiktoken なし）
pip install "mcp-compressor[telemetry]"
```

> **ヒント:** `telemetry-tokens` を選ぶと `tiktoken` も入り、GPT-4 ベースのトークン数をより正確に推定できます。

インストール後、**VS Code を再起動**して mcp-compressor を再起動させます。

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

設定後、**VS Code を再起動**してください。

> **この設定で取れるデータ:**
> Copilot が LLM を呼ぶたびに「何トークン使ったか」「どのモデルを使ったか」「何ミリ秒かかったか」がトレースとして記録されます。

---

## ステップ 4：Grafana でデータを確認する

http://localhost:3000 を開きます（ログイン不要）。

左メニュー → **Dashboards** から以下の2つが自動で登録されています：

| ダッシュボード | 内容 |
|---|---|
| **MCP Compressor** | mcp-compressor の圧縮率・ステージ別効果 |
| **GitHub Copilot Telemetry** | Copilot の実際のトークン使用量・モデル別内訳 |

**データが表示されるまでの流れ:**
1. VS Code で Copilot に何か質問する（ツールを使うような質問が望ましい）
2. 10〜30秒待つ
3. Grafana をリロードする

---

## よくある問題

**「No data」と表示される**

```bash
cd telemetry
docker compose ps   # 全コンテナが running か確認
```

- VS Code を再起動したか確認
- 時間範囲を「Last 5 minutes」に変更してみる

**mcp-compressor のメトリクスは見えるが Copilot のトレースが見えない**

- VS Code settings.json の設定を確認（`github.copilot.chat.otel.enabled`）
- VS Code を完全に再起動（ウィンドウを閉じて再度開く）

**Docker が起動しない**

```bash
cd telemetry
docker compose logs otel-collector
docker compose logs tempo
```

---

## 停止する

```bash
cd telemetry
docker compose down
```

データを全部消す場合：

```bash
docker compose down -v
```
