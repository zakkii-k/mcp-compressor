#!/usr/bin/env python3
"""
mcp-compressor テレメトリサーバー

依存: Python 3.11+ 標準ライブラリのみ
外部パッケージ不要 / 外部への通信なし / ライセンス問題なし

使い方:
  python server.py                    # デフォルト設定で起動
  python server.py --help             # オプション一覧

受信ポート（デフォルト 4318）:
  POST /ingest       mcp-compressor からのメトリクス（JSON）
  POST /v1/traces    VS Code Copilot からの OTLP トレース（JSON）

ダッシュボードポート（デフォルト 3000）:
  GET /              ブラウザでダッシュボードを表示
  GET /api/summary   JSON サマリー（ダッシュボードが内部で使用）
"""

import argparse
import json
import sqlite3
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


# ──────────────────────────────────────────
# SQLite
# ──────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS mcp_requests (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          INTEGER NOT NULL,
    server      TEXT    NOT NULL DEFAULT '',
    tool        TEXT    NOT NULL DEFAULT '',
    chars_in    INTEGER NOT NULL DEFAULT 0,
    chars_out   INTEGER NOT NULL DEFAULT 0,
    tokens_in   INTEGER NOT NULL DEFAULT 0,
    tokens_out  INTEGER NOT NULL DEFAULT 0,
    modified    INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS mcp_stages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          INTEGER NOT NULL,
    stage       TEXT    NOT NULL,
    chars_in    INTEGER NOT NULL DEFAULT 0,
    chars_out   INTEGER NOT NULL DEFAULT 0,
    duration_ms REAL    NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS copilot_spans (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            INTEGER NOT NULL,
    span_name     TEXT    NOT NULL DEFAULT '',
    duration_ms   REAL    NOT NULL DEFAULT 0,
    model         TEXT    NOT NULL DEFAULT '',
    operation     TEXT    NOT NULL DEFAULT '',
    input_tokens  INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_mcp_req_ts   ON mcp_requests(ts);
CREATE INDEX IF NOT EXISTS idx_mcp_stage_ts ON mcp_stages(ts);
CREATE INDEX IF NOT EXISTS idx_copilot_ts   ON copilot_spans(ts);
"""

_db_path: Path = Path("telemetry.db")
_db_lock = threading.Lock()


def _get_db() -> sqlite3.Connection:
    db = sqlite3.connect(str(_db_path))
    db.executescript(_SCHEMA)
    db.commit()
    return db


def _write(sql: str, params: tuple) -> None:
    with _db_lock:
        db = _get_db()
        try:
            db.execute(sql, params)
            db.commit()
        finally:
            db.close()


def _write_many(sql: str, rows: list[tuple]) -> None:
    if not rows:
        return
    with _db_lock:
        db = _get_db()
        try:
            db.executemany(sql, rows)
            db.commit()
        finally:
            db.close()


def _query(sql: str, params: tuple = ()) -> list:
    db = _get_db()
    try:
        return db.execute(sql, params).fetchall()
    finally:
        db.close()


# ──────────────────────────────────────────
# OTLP JSON トレース パーサー
# ──────────────────────────────────────────

def _attr_val(v: dict):
    """OTLP AnyValue から Python の値を取り出す。"""
    for key in ("stringValue", "intValue", "doubleValue", "boolValue"):
        if key in v:
            raw = v[key]
            try:
                if key == "intValue":
                    return int(raw)
                if key == "doubleValue":
                    return float(raw)
            except (ValueError, TypeError):
                pass
            return raw
    return None


def _parse_attrs(attrs: list) -> dict:
    return {a["key"]: _attr_val(a["value"]) for a in attrs if "key" in a and "value" in a}


def _parse_otlp_traces(payload: dict) -> list[tuple]:
    """OTLP JSON の resourceSpans から copilot_spans 用のタプルリストを返す。"""
    rows = []
    for rs in payload.get("resourceSpans", []):
        for ss in rs.get("scopeSpans", []):
            for span in ss.get("spans", []):
                attrs = _parse_attrs(span.get("attributes", []))
                try:
                    start_ns = int(span.get("startTimeUnixNano", 0))
                    end_ns   = int(span.get("endTimeUnixNano",   0))
                    dur_ms   = max(0.0, (end_ns - start_ns) / 1_000_000)
                    ts       = start_ns // 1_000_000
                except (ValueError, TypeError):
                    continue
                rows.append((
                    ts,
                    span.get("name", ""),
                    dur_ms,
                    str(attrs.get("gen_ai.request.model",   "") or ""),
                    str(attrs.get("gen_ai.operation.name",  "") or ""),
                    int(attrs.get("gen_ai.usage.input_tokens",  0) or 0),
                    int(attrs.get("gen_ai.usage.output_tokens", 0) or 0),
                ))
    return rows


# ──────────────────────────────────────────
# サマリークエリ
# ──────────────────────────────────────────

def _build_summary() -> dict:
    # mcp-compressor 全体集計
    row = _query(
        "SELECT COUNT(*), SUM(tokens_in), SUM(tokens_out), SUM(chars_in), SUM(chars_out) "
        "FROM mcp_requests"
    )[0]
    total_req, tok_in, tok_out, ch_in, ch_out = (v or 0 for v in row)

    by_server = [
        {
            "server": r[0], "tool": r[1], "requests": r[2],
            "tokens_in": r[3] or 0, "tokens_out": r[4] or 0,
            "chars_in":  r[5] or 0, "chars_out":  r[6] or 0,
        }
        for r in _query(
            "SELECT server, tool, COUNT(*), SUM(tokens_in), SUM(tokens_out), "
            "SUM(chars_in), SUM(chars_out) "
            "FROM mcp_requests GROUP BY server, tool "
            "ORDER BY SUM(tokens_in) DESC LIMIT 30"
        )
    ]

    by_stage = [
        {
            "stage": r[0], "count": r[1],
            "chars_in": r[2] or 0, "chars_out": r[3] or 0,
            "avg_ms": round(r[4] or 0, 1),
        }
        for r in _query(
            "SELECT stage, COUNT(*), SUM(chars_in), SUM(chars_out), AVG(duration_ms) "
            "FROM mcp_stages GROUP BY stage "
            "ORDER BY (SUM(chars_in) - SUM(chars_out)) DESC"
        )
    ]

    # Copilot
    crow = _query(
        "SELECT COUNT(*), SUM(input_tokens), SUM(output_tokens) "
        "FROM copilot_spans WHERE input_tokens > 0"
    )[0]
    c_calls, c_in, c_out = (v or 0 for v in crow)

    by_model = [
        {
            "model": r[0] or "unknown", "calls": r[1],
            "input_tokens": r[2] or 0, "output_tokens": r[3] or 0,
        }
        for r in _query(
            "SELECT model, COUNT(*), SUM(input_tokens), SUM(output_tokens) "
            "FROM copilot_spans WHERE input_tokens > 0 "
            "GROUP BY model ORDER BY SUM(input_tokens) DESC"
        )
    ]

    recent = [
        {
            "ts": r[0], "name": r[1], "model": r[2],
            "in": r[3], "out": r[4], "ms": round(r[5], 0),
        }
        for r in _query(
            "SELECT ts, span_name, model, input_tokens, output_tokens, duration_ms "
            "FROM copilot_spans ORDER BY ts DESC LIMIT 15"
        )
    ]

    return {
        "mcp": {
            "total_requests": total_req,
            "tokens_in": tok_in, "tokens_out": tok_out,
            "chars_in":  ch_in,  "chars_out":  ch_out,
            "by_server": by_server,
            "by_stage":  by_stage,
        },
        "copilot": {
            "total_calls": c_calls,
            "tokens_in": c_in, "tokens_out": c_out,
            "by_model": by_model,
            "recent":   recent,
        },
    }


# ──────────────────────────────────────────
# HTTP ハンドラー
# ──────────────────────────────────────────

class _Handler(BaseHTTPRequestHandler):

    def log_message(self, *_):
        pass  # アクセスログは抑制

    # POST ────────────────────────────────

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body   = self.rfile.read(length)
        path   = self.path.split("?")[0]

        ct = self.headers.get("Content-Type", "")
        if "application/x-protobuf" in ct:
            # protobuf は非対応（エラーにはせず空応答を返す）
            self._reply(200, b'{"partialSuccess":{}}', "application/json")
            return

        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            self._reply(400, b"invalid json")
            return

        if path == "/ingest":
            self._handle_ingest(payload)
        elif path in ("/v1/traces", "/v1/traces/"):
            self._handle_traces(payload)
        else:
            self._reply(404, b"not found")

    def _handle_ingest(self, p: dict):
        ts   = p.get("ts", int(time.time() * 1000))
        kind = p.get("type", "")
        if kind == "request":
            _write(
                "INSERT INTO mcp_requests"
                "(ts,server,tool,chars_in,chars_out,tokens_in,tokens_out,modified) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (ts, p.get("server",""), p.get("tool",""),
                 int(p.get("chars_in",0)),  int(p.get("chars_out",0)),
                 int(p.get("tokens_in",0)), int(p.get("tokens_out",0)),
                 1 if p.get("modified") else 0),
            )
        elif kind == "stage":
            _write(
                "INSERT INTO mcp_stages(ts,stage,chars_in,chars_out,duration_ms) "
                "VALUES(?,?,?,?,?)",
                (ts, p.get("stage",""),
                 int(p.get("chars_in",0)), int(p.get("chars_out",0)),
                 float(p.get("duration_ms",0))),
            )
        self._reply(200, b"ok")

    def _handle_traces(self, payload: dict):
        rows = _parse_otlp_traces(payload)
        _write_many(
            "INSERT INTO copilot_spans"
            "(ts,span_name,duration_ms,model,operation,input_tokens,output_tokens) "
            "VALUES(?,?,?,?,?,?,?)",
            rows,
        )
        self._reply(200, b'{"partialSuccess":{}}', "application/json")

    # GET ─────────────────────────────────

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/summary":
            data = json.dumps(_build_summary(), ensure_ascii=False).encode()
            self._reply(200, data, "application/json")
        elif path in ("/", "/index.html"):
            self._reply(200, _DASHBOARD_HTML.encode(), "text/html; charset=utf-8")
        else:
            self._reply(404, b"not found")

    # ─────────────────────────────────────

    def _reply(self, code: int, body: bytes, ct: str = "text/plain") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


# ──────────────────────────────────────────
# ダッシュボード HTML（外部リソース一切なし）
# ──────────────────────────────────────────

_DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<title>mcp-compressor Telemetry</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui,-apple-system,sans-serif;background:#0f1117;color:#e2e8f0;padding:24px;font-size:14px}
h1{font-size:1.3rem;font-weight:700;margin-bottom:3px}
.sub{color:#64748b;font-size:.8rem;margin-bottom:28px}
h2{font-size:.75rem;font-weight:600;color:#64748b;text-transform:uppercase;letter-spacing:.08em;margin:28px 0 10px}
.cards{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:18px}
.card{background:#1a2035;border-radius:8px;padding:14px 18px;min-width:148px;border:1px solid #252d3d}
.card .lbl{font-size:.72rem;color:#64748b;margin-bottom:5px}
.card .val{font-size:1.7rem;font-weight:700}
.val.g{color:#34d399}.val.b{color:#60a5fa}.val.a{color:#fbbf24}
table{width:100%;border-collapse:collapse;margin-bottom:16px}
th{text-align:left;padding:7px 10px;color:#64748b;font-weight:500;font-size:.78rem;border-bottom:1px solid #1e2740}
td{padding:6px 10px;border-bottom:1px solid #161d2e;font-size:.82rem}
tr:hover td{background:#1a2035}
.bar-bg{background:#1e2740;border-radius:3px;height:5px;width:100px;display:inline-block;vertical-align:middle}
.bar-fg{height:5px;border-radius:3px;background:#60a5fa}
.bar-fg.g{background:#34d399}.bar-fg.a{background:#fbbf24}
.none{color:#475569;font-style:italic;padding:10px 0 6px}
.g{color:#34d399}.a{color:#fbbf24}
#footer{color:#334155;font-size:.72rem;margin-top:28px}
</style>
</head>
<body>
<h1>mcp-compressor Telemetry</h1>
<div class="sub">stdlib のみ &nbsp;·&nbsp; 外部通信なし &nbsp;·&nbsp; ローカル SQLite</div>
<div id="root"></div>
<div id="footer"></div>
<script>
const fmt = n => (n||0).toLocaleString('ja-JP');
const pct = (a,b) => b>0 ? ((1-a/b)*100).toFixed(1)+'%' : '—';
const bar = (v,max,cls='') => {
  const w = max>0 ? Math.min(100,Math.round(v/max*100)) : 0;
  return `<span class="bar-bg"><span class="bar-fg ${cls}" style="width:${w}px"></span></span>`;
};

async function refresh() {
  let d;
  try { d = await fetch('/api/summary').then(r=>r.json()); }
  catch(e) { document.getElementById('root').innerHTML='<div class="none">サーバーに接続できません</div>'; return; }

  const m=d.mcp, c=d.copilot;
  const tokSaved = m.tokens_in - m.tokens_out;
  const tokRatio = m.tokens_in>0 ? tokSaved/m.tokens_in : 0;
  let html='';

  // ── mcp-compressor ────────────────────────────
  html += '<h2>mcp-compressor 圧縮効果</h2><div class="cards">';
  html += card('処理リクエスト', fmt(m.total_requests), 'b');
  html += card('トークン削減率（推定）', (tokRatio*100).toFixed(1)+'%', 'g');
  html += card('削減トークン（累計）', fmt(tokSaved), 'g');
  html += card('文字削減率', pct(m.chars_out, m.chars_in), '');
  html += '</div>';

  if (m.by_server.length) {
    const maxI = Math.max(...m.by_server.map(r=>r.tokens_in));
    html += '<table><thead><tr><th>サーバー</th><th>ツール</th><th>呼び出し</th>'
          + '<th>入力 tokens</th><th>出力 tokens</th><th>削減率</th></tr></thead><tbody>';
    for (const r of m.by_server) {
      const ratio = r.tokens_in>0 ? (1-r.tokens_out/r.tokens_in)*100 : 0;
      html += `<tr><td>${esc(r.server)||'—'}</td><td>${esc(r.tool)||'—'}</td><td>${fmt(r.requests)}</td>`
            + `<td>${fmt(r.tokens_in)} ${bar(r.tokens_in,maxI)}</td>`
            + `<td>${fmt(r.tokens_out)}</td>`
            + `<td class="g">${ratio.toFixed(1)}%</td></tr>`;
    }
    html += '</tbody></table>';
  } else {
    html += '<div class="none">データなし（mcp-compressor を起動して Copilot でツールを呼び出してください）</div>';
  }

  if (m.by_stage.length) {
    html += '<h2>パイプライン ステージ別</h2>';
    const maxS = Math.max(...m.by_stage.map(r=>r.chars_in-r.chars_out));
    html += '<table><thead><tr><th>ステージ</th><th>実行回数</th><th>文字削減量</th><th>削減率</th><th>平均処理時間</th></tr></thead><tbody>';
    for (const r of m.by_stage) {
      const saved = r.chars_in - r.chars_out;
      const ratio = r.chars_in>0 ? (1-r.chars_out/r.chars_in)*100 : 0;
      html += `<tr><td>${esc(r.stage)}</td><td>${fmt(r.count)}</td>`
            + `<td>${fmt(saved)} ${bar(saved,maxS,'g')}</td>`
            + `<td class="g">${ratio.toFixed(1)}%</td><td>${r.avg_ms} ms</td></tr>`;
    }
    html += '</tbody></table>';
  }

  // ── Copilot ───────────────────────────────────
  html += '<h2>GitHub Copilot（実際のトークン使用量）</h2>';
  if (c.total_calls > 0) {
    html += '<div class="cards">';
    html += card('LLM 呼び出し回数', fmt(c.total_calls), 'b');
    html += card('入力トークン（実測）', fmt(c.tokens_in), 'a');
    html += card('出力トークン（実測）', fmt(c.tokens_out), '');
    if (m.tokens_in>0 && c.tokens_in>0) {
      const saveRatio = tokSaved/c.tokens_in;
      html += card('圧縮削減 / Copilot 入力', (saveRatio*100).toFixed(1)+'%', 'g');
    }
    html += '</div>';

    if (c.by_model.length) {
      const maxM = Math.max(...c.by_model.map(r=>r.input_tokens));
      html += '<table><thead><tr><th>モデル</th><th>呼び出し</th><th>入力 tokens</th><th>出力 tokens</th></tr></thead><tbody>';
      for (const r of c.by_model) {
        html += `<tr><td>${esc(r.model)}</td><td>${fmt(r.calls)}</td>`
              + `<td>${fmt(r.input_tokens)} ${bar(r.input_tokens,maxM,'a')}</td>`
              + `<td>${fmt(r.output_tokens)}</td></tr>`;
      }
      html += '</tbody></table>';
    }

    if (c.recent.length) {
      html += '<h2>最近の LLM 呼び出し</h2>';
      html += '<table><thead><tr><th>時刻</th><th>スパン名</th><th>モデル</th>'
            + '<th>入力 tokens</th><th>出力 tokens</th><th>処理時間</th></tr></thead><tbody>';
      for (const r of c.recent) {
        const dt = new Date(r.ts).toLocaleTimeString('ja-JP');
        html += `<tr><td>${dt}</td><td>${esc(r.name)}</td><td>${esc(r.model)||'—'}</td>`
              + `<td>${fmt(r.in)}</td><td>${fmt(r.out)}</td><td>${fmt(r.ms)} ms</td></tr>`;
      }
      html += '</tbody></table>';
    }
  } else {
    html += '<div class="none">データなし（VS Code settings.json の OTel 設定を確認してください）</div>';
  }

  document.getElementById('root').innerHTML = html;
  document.getElementById('footer').textContent =
    '最終更新: ' + new Date().toLocaleTimeString('ja-JP') + '  （10 秒ごとに自動更新）';
}

function card(lbl, val, cls) {
  return `<div class="card"><div class="lbl">${lbl}</div><div class="val ${cls}">${val}</div></div>`;
}
function esc(s) {
  return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

refresh();
setInterval(refresh, 10000);
</script>
</body>
</html>"""


# ──────────────────────────────────────────
# メイン
# ──────────────────────────────────────────

def main() -> None:
    global _db_path

    ap = argparse.ArgumentParser(
        description="mcp-compressor テレメトリサーバー（stdlib のみ・外部通信なし）"
    )
    ap.add_argument("--ingest-port",    type=int, default=4318,
                    help="データ受信ポート（デフォルト: 4318）")
    ap.add_argument("--dashboard-port", type=int, default=3000,
                    help="ダッシュボードポート（デフォルト: 3000）")
    ap.add_argument("--db",             default="telemetry.db",
                    help="SQLite DB ファイルパス（デフォルト: telemetry.db）")
    args = ap.parse_args()

    _db_path = Path(args.db)

    ingest_server    = HTTPServer(("0.0.0.0", args.ingest_port),    _Handler)
    dashboard_server = HTTPServer(("0.0.0.0", args.dashboard_port), _Handler)

    print(f"[telemetry] 起動しました", file=sys.stderr)
    print(f"  データ受信:    http://localhost:{args.ingest_port}", file=sys.stderr)
    print(f"  ダッシュボード: http://localhost:{args.dashboard_port}", file=sys.stderr)
    print(f"  DB:            {_db_path.resolve()}", file=sys.stderr)
    print(f"  停止: Ctrl+C", file=sys.stderr)

    threading.Thread(target=ingest_server.serve_forever, daemon=True).start()

    try:
        dashboard_server.serve_forever()
    except KeyboardInterrupt:
        print("\n[telemetry] 停止しました", file=sys.stderr)
    finally:
        ingest_server.shutdown()
        dashboard_server.shutdown()


if __name__ == "__main__":
    main()
