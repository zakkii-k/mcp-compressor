# MCP レスポンス圧縮手法 比較

LLMに渡すテキストのトークン数を削減するために使える手法の比較。
ポイント: **LLMが読めること**（バイナリ圧縮は論外）、**実装コストが低いこと**。

---

## 比較表

| 手法 | 削減率の目安 | LLM不要 | 可逆性 | 実装コスト | 適したデータ | 実装状況 |
|------|------------|---------|--------|-----------|------------|---------|
| **TOON変換** | **36–64%** | ✅ | ⚠️ | 低 | JSON全般（最優先） | ✅ 実装済み |
| **JSON minify** | ~50% | ✅ | ✅ | 低 | JSON（空白多め） | ✅ 実装済み（TOON非使用時の代替） |
| **JSON→Markdownテーブル** | ~40–60% | ✅ | ⚠️ | 低 | オブジェクト配列 | ✅ 実装済み（TOON非使用時の代替） |
| **ログ重複除去** | ~80–98% | ✅ | ⚠️ | 低 | 繰り返しパターンのログ | ✅ 実装済み |
| **ログ先頭/エラー/末尾** | ~60–80% | ✅ | ⚠️ | 低 | 大量ログ（重複なし） | ✅ 実装済み |
| **JSON→YAML変換** | ~10–30% | ✅ | ✅ | 低 | ネストが深いJSON | ❌ 未実装（TOON>YAML） |
| **JSON→CSV変換** | ~50–70% | ✅ | ✅ | 低 | 純粋な表形式データ | ❌ 未実装（TOON>CSV） |
| **LLM要約** | ~70–90% | ❌ | ✅（保存） | 中 | 汎用 | ✅ 実装済み |
| gzip/zlib | ~96% | ✅ | ✅ | 低 | — | ❌ LLMが読めないので不可 |

> **削減率のベンチマーク（実測）:**
> - TOON: 1,836文字 → 663文字（**36%、オブジェクト配列**）/ 108文字 → 71文字（ネストオブジェクト）
> - JSON minify: 20,547文字 → 9,712文字（**53%削減**）
> - ログ重複除去: 200行 → 3パターン（**98%削減**）

---

## 各手法の詳細

### JSON minify
**何をするか:** `json.dumps(data, separators=(',', ':'))` で空白・改行を除去。

**向いているケース:**
- インデント付きで返ってくるJSON（API レスポンスによくある）
- 構造は保ちたいが空白が無駄に多い場合

**向いていないケース:**
- すでに minify されている JSON
- 配列のオブジェクト数が多い（→ テーブル変換の方が効果的）

---

### JSON → Markdown テーブル
**何をするか:** `[{id:1, name:"A"}, ...]` 形式のJSON配列をMarkdownテーブルに変換。

```
元: [{"id": 1, "name": "Alice", "email": "a@example.com"}, ...] × 79件
↓
[JSON配列→テーブル変換: 79件]

| id | name | email |
|---|---|---|
| 1 | Alice | a@example.com |
...
```

**向いているケース:**
- ユーザー一覧、ファイル一覧、レコード一覧など「オブジェクトの配列」
- LLMがテーブルを見て判断するだけで良い場合

**なぜ Markdown テーブルが効果的か:**
- JSON はキー名を全行に繰り返す（`"id"`, `"name"`, ... が79回）
- テーブルはキー名がヘッダー1行のみ
- LLMはMarkdownテーブルを高精度で読める

---

### ログ重複除去
**何をするか:** 数値・タイムスタンプ・UUIDを正規化し、同パターンの行を集約。

```
元: 200行
  2024-06-10 12:00:01 INFO Processing item 1/200 - status=OK
  2024-06-10 12:00:02 INFO Processing item 2/200 - status=OK
  ...（198行続く）
  2024-06-10 12:03:20 ERROR Failed to process request #100

↓ 重複除去後: 2パターン
[ログ重複除去済み: 200行 → 2パターン (1%)]
2024-06-10 12:00:01 INFO Processing item 1/200 - status=OK  [×199]
2024-06-10 12:03:20 ERROR Failed to process request #100
```

**向いているケース:**
- CI/CDのビルドログ
- アプリケーションのアクセスログ
- バッチ処理の進捗ログ

---

### YAML 変換（未実装）
**何をするか:** JSONをYAMLに変換。ネスト構造の表現が簡潔になる。

```json
{"user": {"name": "Alice", "age": 30, "address": {"city": "Tokyo"}}}
→
user:
  name: Alice
  age: 30
  address:
    city: Tokyo
```

**削減率:** 10–30%程度。平坦なJSONにはほぼ効果なし。

**実装難易度:** `yaml.dump(json.loads(text))` の1行。追加依存なし（PyYAML は既存）。

---

### CSV 変換（未実装）
**何をするか:** オブジェクト配列をCSVに変換。Markdownテーブルよりさらに短い。

```
id,name,email
1,Alice,a@example.com
2,Bob,b@example.com
```

**削減率:** Markdownテーブルより10–20%程度さらに削減。
**欠点:** LLMによってはMarkdownテーブルより読みにくい場合がある。

---

## TOON (Token-Oriented Object Notation)

> 公式: https://toonformat.dev/  
> Python パッケージ: `python-toon`（`uv add python-toon`）

LLM 向けに設計されたコンパクトシリアライズ形式。JSON の完全な上位互換で可逆。

### 構文の例

```
# オブジェクト配列（ヘッダー1行 + CSV形式の行）
[19,]{id,name,email,role}:
  1,User1,u1@example.com,member
  2,User2,u2@example.com,member
  ...

# ネストオブジェクト（インデントベース）
status: ok
metadata:
  version: "1.2"
  generated: 2024-06-10
count: 42
```

### なぜ Markdown テーブルより優れるか

| 比較 | Markdown テーブル | TOON |
|------|-----------------|------|
| ヘッダー行 | `\| id \| name \| ... \|` | `{id,name,...}` |
| セパレータ行 | `\|---|---|...\|` | なし |
| データ行 | `\| 1 \| Alice \| ... \|` | `1,Alice,...` |

`|` や `---` がなくなる分さらにコンパクト。

---

## パイプラインの推奨設定

```yaml
# 標準（TOON あり・バランス型）← デフォルト
pipeline:
  - toon_converter        # JSON は TOON で最優先圧縮（要 python-toon）
  - log_deduplicator      # 繰り返しログを集約
  - log_compressor        # まだ長ければ先頭/末尾に
  - llm_summarizer        # それでも長ければ LLM 要約

# python-toon なし / TOON を使わない場合
pipeline:
  - json_compressor
  - json_table_converter
  - log_deduplicator
  - log_compressor
  - llm_summarizer

# LLM なし（Ollama 未セットアップ時）
pipeline:
  - toon_converter
  - log_deduplicator
  - log_compressor

# 高速・最小構成（JSON のみ扱う場合）
pipeline:
  - toon_converter
```
