# テレメトリの仕組みと見方

---

## mcp-compressor が送るデータ（メトリクス）

mcp-compressor はツール呼び出しのたびに以下の数値を記録して otel-collector に送ります。

### リクエスト単位のメトリクス

| メトリクス名 | 単位 | 意味 |
|---|---|---|
| `mcp_compressor.chars.input` | 文字数 | 圧縮前のレスポンスの長さ |
| `mcp_compressor.chars.output` | 文字数 | 圧縮後のレスポンスの長さ |
| `mcp_compressor.tokens.input` | トークン数 | 圧縮前の推定トークン数（※） |
| `mcp_compressor.tokens.output` | トークン数 | 圧縮後の推定トークン数（※） |
| `mcp_compressor.requests.total` | 回数 | 処理したリクエスト数 |

**ラベル（タグ）:** `server`（どの MCP サーバーか）・`tool`（どのツールか）・`modified`（実際に圧縮されたか）

**（※） トークン推定について:**
`tiktoken` がインストールされている場合は GPT-4 系のトークナイザーで実測値に近い推定が出ます。未インストールの場合は「文字数 ÷ 4」という大まかな計算になります。あくまで推定値であり、Copilot の実際の課金トークン数とは異なります。

### ステージ単位のメトリクス

パイプラインの各処理段階ごとにも記録されます。

| メトリクス名 | 単位 | 意味 |
|---|---|---|
| `mcp_compressor.stage.chars.input` | 文字数 | そのステージへの入力 |
| `mcp_compressor.stage.chars.output` | 文字数 | そのステージからの出力 |
| `mcp_compressor.stage.duration` | ms | そのステージの処理時間 |

**ラベル:** `stage`（ステージ名。例: `ToonConverter`・`LLMSummarizer`）

**ステージ名の意味:**

| ステージ名 | 何をするか |
|---|---|
| `ToonConverter` | JSON を人間が読みやすいテーブル形式に変換 |
| `LogDeduplicator` | 同じ行が繰り返されるログを圧縮 |
| `LogCompressor` | ログの行数を上限で切り詰める |
| `LLMSummarizer` | Ollama で LLM 要約 |
| `BedrockSummarizer` | AWS Bedrock で LLM 要約 |

---

## Copilot が送るデータ（トレース）

`github.copilot.chat.otel.enabled: true` にすると、Copilot がすべての LLM 呼び出しを**トレース（スパン）**として送ります。

### スパンの属性（OTel GenAI セマンティック規約準拠）

| 属性名 | 例 | 意味 |
|---|---|---|
| `gen_ai.system` | `"github_copilot"` | AI プロバイダー |
| `gen_ai.operation.name` | `"chat"` | 操作の種類 |
| `gen_ai.request.model` | `"gpt-4o"` | 使用したモデル |
| `gen_ai.usage.input_tokens` | `1240` | プロンプトのトークン数 |
| `gen_ai.usage.output_tokens` | `380` | レスポンスのトークン数 |

`captureContent: true` にすると、プロンプトやレスポンスの本文も記録されます（ローカルの Tempo にのみ保存されます）。

### メトリクス vs トレースの違い（重要）

| | mcp-compressor のメトリクス | Copilot のトレース |
|---|---|---|
| データ形式 | 数値の時系列（Prometheus） | 処理の記録（Tempo） |
| 閲覧場所 | Grafana「MCP Compressor」ダッシュボード | Grafana「Copilot Telemetry」ダッシュボード |
| トークン数 | **推定値**（tiktoken） | **実測値**（Copilot の実際の消費量） |
| 集計クエリ | PromQL（例: `sum(rate(...))`) | TraceQL（例: `{...} \| sum(span.gen_ai.usage.input_tokens)`） |

---

## Grafana ダッシュボードの読み方

### MCP Compressor ダッシュボード

```
┌──────────────────────────────────────────────────────┐
│ トークン削減率   文字削減率   累積削減トークン数   リクエスト数 │
│    35%           42%             12,400             88     │
├──────────────────────────────────────────────────────┤
│ 入出力トークン数（時系列）  │  サーバー別 削減トークン数    │
│  ─── 入力                  │  confluence ████████████    │
│  ─── 出力                  │  filesystem ████            │
├──────────────────────────────────────────────────────┤
│ ステージ別 削減量           │  ステージ別 処理時間(ms)      │
│  ToonConverter  ████████   │  LLMSummarizer  ████████    │
│  LLMSummarizer  ██████     │  ToonConverter  ██          │
└──────────────────────────────────────────────────────┘
```

**「削減率 0%」の場合:** 閾値（デフォルト 5000文字）未満のレスポンスは圧縮されないため、小さいレスポンスだと modified=false になります。

### GitHub Copilot Telemetry ダッシュボード

```
┌──────────────────────────────────────────────────────┐
│ LLM呼び出し回数  入力トークン合計  出力トークン合計  ツール呼び出し │
│     24              48,200           9,800          36      │
├──────────────────────────────────────────────────────┤
│ 入出力トークン数（時系列）  │  モデル別 呼び出し割合        │
│  ─── 入力                  │  gpt-4o    ███████████      │
│  ─── 出力                  │  gpt-4     ███              │
├──────────────────────────────────────────────────────┤
│ LLM 呼び出しレイテンシ      │  最近のトレース（一覧）        │
│                             │  トレースをクリックで詳細表示  │
├──────────────────────────────────────────────────────┤
│ mcp-compressor 削減トークン vs Copilot 入力トークン（比較）   │
│  ─── Copilot 入力（実測）                                    │
│  ─── mcp-compressor 削減（推定）                             │
└──────────────────────────────────────────────────────┘
```

**「mcp-compressor 削減トークン vs Copilot 入力トークン」パネルについて:**
2つのデータが並ぶ比較グラフです。mcp-compressor の削減量（推定）が Copilot の入力トークン全体に対してどの程度の割合かを目視で確認できます。ただし両者は単純に足し引きできる値ではないことに注意してください。Copilot の入力トークンには mcp-compressor が処理した部分以外（会話履歴・システムプロンプト等）も含まれます。

### トレースの詳細を見る

「最近のトレース」テーブルでトレースをクリックすると、Grafana 内でトレースの詳細（スパンツリー）が表示されます。LLM 呼び出しの中で MCP ツールがどのタイミングで呼ばれたかを確認できます。

---

## 高度なクエリ例

Grafana の Explore（左メニュー）から手動でクエリを試せます。

**Prometheus（mcp-compressor メトリクス）:**
```promql
# confluence サーバーの圧縮率だけ見る
1 - sum(rate(mcp_compressor_tokens_output_sum{server="confluence"}[5m]))
  / sum(rate(mcp_compressor_tokens_input_sum{server="confluence"}[5m]))
```

**Tempo（Copilot トレース）- データソースを Tempo に切り替える:**
```
# 全 LLM 呼び出しの入力トークン合計（1分ごと）
{ span.gen_ai.usage.input_tokens > 0 } | sum(span.gen_ai.usage.input_tokens)

# モデル別に分けて見る
{ span.gen_ai.usage.input_tokens > 0 } | sum(span.gen_ai.usage.input_tokens) by (span.gen_ai.request.model)

# MCP ツール呼び出しだけ抽出する
{ span.gen_ai.operation.name = "chat" && duration > 2s }
```
