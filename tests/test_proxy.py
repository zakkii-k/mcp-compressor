"""
mcp_proxy + mock_server の結合テスト。

Ollama なしで動く pipeline テスト（json/log compressor）と
Ollama ありの LLM 要約テストを分けて実行できる。
"""

import json
import subprocess
import sys
import pytest
from pathlib import Path

ROOT = Path(__file__).parent.parent
MOCK_SERVER = Path(__file__).parent / "mock_server.py"
PYTHON = sys.executable

MCP_INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
    "protocolVersion": "2024-11-05",
    "capabilities": {},
    "clientInfo": {"name": "test-client", "version": "1.0"},
}}
MCP_INITIALIZED = {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
MCP_TOOLS_LIST = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}


def _ollama_available() -> bool:
    try:
        import httpx
        r = httpx.get("http://localhost:11434", timeout=2.0)
        return r.status_code == 200
    except Exception:
        return False


def build_tool_call(tool_name: str, call_id: int = 3) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": call_id,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": {}},
    }


def run_proxy_session(tool_name: str, config_path: str | None = None) -> dict:
    """プロキシ経由でツールを呼び出し、id→レスポンスの辞書を返す。"""
    cmd = [PYTHON, "-m", "mcp_compressor"]
    if config_path:
        cmd += ["--config", config_path]
    cmd += ["--", PYTHON, str(MOCK_SERVER)]

    messages = [MCP_INIT, MCP_INITIALIZED, MCP_TOOLS_LIST, build_tool_call(tool_name)]
    stdin_data = "\n".join(json.dumps(m) for m in messages) + "\n"

    result = subprocess.run(
        cmd,
        input=stdin_data.encode(),
        capture_output=True,
        timeout=30,
        cwd=ROOT,
    )
    responses = {}
    for line in result.stdout.decode().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
            if "id" in msg:
                responses[msg["id"]] = msg
        except json.JSONDecodeError:
            pass
    return responses


# ─────────────────────────────────────────
# Pipeline 単体テスト（Ollama 不要）
# ─────────────────────────────────────────

class TestPipelineWithoutLLM:
    """LLM 要約を無効にした状態でのパイプラインテスト。"""

    @pytest.fixture(autouse=True)
    def config_no_llm(self, tmp_path):
        import yaml
        cfg = {
            "threshold_chars": 5000,
            "originals_dir": str(tmp_path / "originals"),
            "pipeline": ["json_compressor", "log_compressor"],
        }
        path = tmp_path / "config_no_llm.yaml"
        path.write_text(yaml.dump(cfg))
        self.config_path = str(path)
        self.tmp_path = tmp_path

    def _get_tool_text(self, tool_name: str) -> str:
        responses = run_proxy_session(tool_name, self.config_path)
        assert 3 in responses, f"ツール呼び出しのレスポンスがない: {responses}"
        content = responses[3]["result"]["content"]
        text_items = [c for c in content if c.get("type") == "text"]
        assert text_items, "text コンテンツがない"
        return text_items[0]["text"]

    def test_handshake_works(self):
        """MCP 初期化ハンドシェイクが成功する。"""
        responses = run_proxy_session("get_small_response", self.config_path)
        assert 1 in responses, "initialize レスポンスがない"
        assert "result" in responses[1]

    def test_tools_list(self):
        """tools/list でツール一覧が取得できる。"""
        responses = run_proxy_session("get_small_response", self.config_path)
        assert 2 in responses
        tools = responses[2]["result"]["tools"]
        tool_names = [t["name"] for t in tools]
        assert "get_large_json" in tool_names
        assert "get_large_text" in tool_names

    def test_small_response_passes_through(self):
        """閾値以下のレスポンスはそのまま通過する。"""
        text = self._get_tool_text("get_small_response")
        assert "OK" in text
        assert "LLM要約" not in text
        assert "圧縮" not in text

    def test_json_compressor(self):
        """大きな JSON が minify されてサイズが減少する。"""
        text = self._get_tool_text("get_large_json")
        assert "    " not in text, "minify 後にインデントが残っている"
        data = json.loads(text)
        assert "users" in data
        assert len(data["users"]) == 79

    def test_log_compressor(self):
        """大量ログが先頭/エラー/末尾に圧縮される。"""
        text = self._get_tool_text("get_large_log")
        assert "ログ圧縮済み" in text or "ログ重複除去済み" in text, f"圧縮ヘッダーがない: {text[:300]}"
        assert "ERROR" in text

    def test_log_deduplicator(self):
        """繰り返しパターンのログが集約される。"""
        from mcp_compressor.pipeline.log_deduplicator import LogDeduplicator
        dedup = LogDeduplicator()
        log_text = "\n".join(
            f"2024-06-10 INFO Processing item {i}/200 - status=OK" for i in range(1, 101)
        ) + "\n2024-06-10 ERROR Something failed"
        result, modified = dedup.process(log_text)
        assert modified, "重複ログが変更されなかった"
        assert "重複除去済み" in result
        assert "×" in result  # 繰り返し回数表示
        assert "ERROR" in result  # エラー行は保持

    def test_json_table_converter(self):
        """JSON配列がMarkdownテーブルに変換される。"""
        import json
        from mcp_compressor.pipeline.json_table_converter import JSONTableConverter
        converter = JSONTableConverter()
        data = [{"id": i, "name": f"User{i}", "email": f"u{i}@example.com"} for i in range(1, 20)]
        text = json.dumps(data, indent=2)
        result, modified = converter.process(text)
        assert modified, "JSON配列がテーブルに変換されなかった"
        assert "| id |" in result or "| name |" in result
        assert "---" in result  # Markdownテーブルのセパレータ

    def test_toon_converter(self):
        """JSON が TOON 形式に変換され、サイズが削減される。"""
        import json
        from mcp_compressor.pipeline.toon_converter import ToonConverter, _TOON_AVAILABLE
        if not _TOON_AVAILABLE:
            pytest.skip("python-toon が未インストール")
        converter = ToonConverter()
        data = [{"id": i, "name": f"User{i}", "email": f"u{i}@example.com", "role": "member"} for i in range(1, 30)]
        text = json.dumps(data, indent=2)
        result, modified = converter.process(text)
        assert modified, "TOON変換されなかった"
        assert len(result) < len(text), "TOON変換後のサイズが削減されていない"
        # TOON の tabular 形式の特徴: ヘッダー行に {} が含まれる
        assert "{" in result or "," in result


# ─────────────────────────────────────────
# LLM 要約テスト（Ollama が必要）
# ─────────────────────────────────────────

@pytest.mark.skipif(
    not _ollama_available(),
    reason="Ollama が localhost:11434 で動いていない",
)
class TestLLMSummarizer:
    @pytest.fixture(autouse=True)
    def config_with_llm(self, tmp_path):
        import yaml
        cfg = {
            "threshold_chars": 500,  # テスト用に低い閾値
            "originals_dir": str(tmp_path / "originals"),
            "ollama_url": "http://localhost:11434",
            "model": "qwen2.5:3b",
            "pipeline": ["json_compressor", "log_compressor", "llm_summarizer"],
        }
        path = tmp_path / "config_with_llm.yaml"
        path.write_text(yaml.dump(cfg))
        self.config_path = str(path)
        self.tmp_path = tmp_path

    def test_large_text_is_summarized(self):
        responses = run_proxy_session("get_large_text", self.config_path)
        assert 3 in responses
        content = responses[3]["result"]["content"]
        text = next(c["text"] for c in content if c.get("type") == "text")
        assert "LLM要約済み" in text, f"要約されていない: {text[:200]}"

    def test_original_is_saved(self):
        run_proxy_session("get_large_text", self.config_path)
        originals = list((self.tmp_path / "originals").glob("original_*.txt"))
        assert originals, "元データファイルが保存されていない"
        content = originals[0].read_text()
        assert "セクション" in content


# ─────────────────────────────────────────
# wrap モードのテスト（Ollama 不要）
# ─────────────────────────────────────────

class TestWrapProxy:
    """wrap モード: 複数サーバーを束ねて1つの MCP として見せるテスト。"""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        import yaml
        # パイプラインなし（圧縮動作は別テストで確認済み）
        cfg = {
            "threshold_chars": 99999,
            "originals_dir": str(tmp_path / "originals"),
            "pipeline": [],
        }
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump(cfg))
        self.config_path = str(config_path)

        # モックサーバーを2台定義した mcp.servers.json
        servers_config = {
            "servers": {
                "server_a": {
                    "type": "stdio",
                    "command": sys.executable,
                    "args": [str(MOCK_SERVER)],
                },
                "server_b": {
                    "type": "stdio",
                    "command": sys.executable,
                    "args": [str(MOCK_SERVER)],
                },
            }
        }
        servers_path = tmp_path / "mcp.servers.json"
        servers_path.write_text(json.dumps(servers_config))
        self.servers_path = str(servers_path)
        self.tmp_path = tmp_path

    def _run_wrap_session(self, tool_name: str) -> dict:
        cmd = [
            PYTHON, "-m", "mcp_compressor",
            "--mode", "wrap",
            "--mcp-config", self.servers_path,
            "--config", self.config_path,
        ]
        messages = [MCP_INIT, MCP_INITIALIZED, MCP_TOOLS_LIST,
                    build_tool_call(tool_name)]
        stdin_data = "\n".join(json.dumps(m) for m in messages) + "\n"
        result = subprocess.run(
            cmd, input=stdin_data.encode(), capture_output=True,
            timeout=30, cwd=ROOT,
        )
        responses = {}
        for line in result.stdout.decode().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
                if "id" in msg:
                    responses[msg["id"]] = msg
            except json.JSONDecodeError:
                pass
        return responses

    def test_tools_are_prefixed(self):
        """ツール名がサーバー名でプレフィックスされる。"""
        responses = self._run_wrap_session("server_a__get_small_response")
        assert 2 in responses
        tools = responses[2]["result"]["tools"]
        names = [t["name"] for t in tools]
        # 2台のモックサーバーのツールが両方プレフィックス付きで返る
        assert any(n.startswith("server_a__") for n in names)
        assert any(n.startswith("server_b__") for n in names)

    def test_tool_call_routed_correctly(self):
        """プレフィックスで正しいサーバーにルーティングされる。"""
        responses = self._run_wrap_session("server_a__get_small_response")
        assert 3 in responses
        content = responses[3]["result"]["content"]
        text = next(c["text"] for c in content if c.get("type") == "text")
        assert "OK" in text

    def test_tool_descriptions_show_server(self):
        """ツールの説明にサーバー名が付く。"""
        responses = self._run_wrap_session("server_a__get_small_response")
        tools = responses[2]["result"]["tools"]
        server_a_tools = [t for t in tools if t["name"].startswith("server_a__")]
        assert all("[server_a]" in t.get("description", "") for t in server_a_tools)
