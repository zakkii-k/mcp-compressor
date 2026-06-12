"""各 MCP サーバーへの接続を管理するモジュール。

stdio サーバー        : 子プロセスとして起動して stdin/stdout で通信
SSE サーバー          : HTTP 接続を維持してリクエスト/レスポンスを処理（旧仕様）
Streamable HTTP サーバー: JSON-RPC を直接 POST（MCP 2025-03-26、OAuth 対応）
"""

import json
import logging
import queue
import subprocess
import threading
from abc import ABC, abstractmethod
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class BaseServerConnection(ABC):
    def __init__(self, name: str) -> None:
        self.name = name
        self._request_id = 0
        self.tools: list[dict] = []

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    @abstractmethod
    def connect(self) -> None:
        """サーバーに接続して MCP ハンドシェイクを完了する。"""

    @abstractmethod
    def _request(self, method: str, params: dict) -> Any:
        """JSON-RPC リクエストを送信して結果を返す。"""

    @abstractmethod
    def _notify(self, method: str, params: dict) -> None:
        """通知（レスポンスなし）を送信する。"""

    def list_tools(self) -> list[dict]:
        result = self._request("tools/list", {})
        return result.get("tools", []) if result else []

    def call_tool(self, tool_name: str, arguments: dict) -> dict:
        return self._request("tools/call", {"name": tool_name, "arguments": arguments}) or {}

    def close(self) -> None:
        pass

    def _do_handshake(self) -> None:
        """initialize → notifications/initialized → tools/list の順に実行する。"""
        self._request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "mcp-compressor", "version": "0.1.0"},
        })
        self._notify("notifications/initialized", {})
        self.tools = self.list_tools()
        logger.info("接続済み: %s (%d ツール)", self.name, len(self.tools))


class StdioServerConnection(BaseServerConnection):
    """子プロセスとして起動する stdio MCP サーバーへの接続。"""

    def __init__(self, name: str, config: dict) -> None:
        super().__init__(name)
        self.config = config
        self.proc: subprocess.Popen | None = None

    def connect(self) -> None:
        cmd = [self.config["command"]] + self.config.get("args", [])
        env = self.config.get("env") or None
        self.proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        self._do_handshake()

    def _request(self, method: str, params: dict) -> Any:
        req_id = self._next_id()
        msg = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
        self.proc.stdin.write((json.dumps(msg, ensure_ascii=False) + "\n").encode())
        self.proc.stdin.flush()

        # ID が一致するまで読む（途中の通知は読み飛ばす）
        while True:
            raw = self.proc.stdout.readline()
            if not raw:
                raise ConnectionError(f"{self.name}: サーバーが終了しました")
            try:
                resp = json.loads(raw.decode("utf-8", errors="replace"))
            except json.JSONDecodeError:
                continue
            if resp.get("id") == req_id:
                if "error" in resp:
                    raise RuntimeError(f"{self.name}: {resp['error']}")
                return resp.get("result")

    def _notify(self, method: str, params: dict) -> None:
        msg = {"jsonrpc": "2.0", "method": method, "params": params}
        self.proc.stdin.write((json.dumps(msg, ensure_ascii=False) + "\n").encode())
        self.proc.stdin.flush()

    def close(self) -> None:
        if self.proc:
            self.proc.terminate()


class SSEServerConnection(BaseServerConnection):
    """HTTP/SSE ベースの外部 MCP サーバーへの接続（Atlassian 等）。"""

    def __init__(self, name: str, config: dict) -> None:
        super().__init__(name)
        self.url = config["url"].rstrip("/")
        self._client = httpx.Client(timeout=60.0)
        self._message_url: str | None = None
        self._endpoint_ready = threading.Event()
        self._response_queues: dict[int, queue.Queue] = {}
        self._lock = threading.Lock()

    def connect(self) -> None:
        reader = threading.Thread(
            target=self._sse_reader, daemon=True, name=f"sse-{self.name}"
        )
        reader.start()
        if not self._endpoint_ready.wait(timeout=10):
            raise ConnectionError(f"{self.name}: SSE エンドポイント URL が取得できませんでした")
        self._do_handshake()

    def _sse_reader(self) -> None:
        """SSE ストリームを常時読み、レスポンスを対応するキューに投入する。"""
        try:
            with self._client.stream(
                "GET", self.url, headers={"Accept": "text/event-stream"}
            ) as resp:
                event_type = None
                for line in resp.iter_lines():
                    line = line.strip()
                    if line.startswith("event:"):
                        event_type = line[6:].strip()
                    elif line.startswith("data:"):
                        data = line[5:].strip()
                        if event_type == "endpoint":
                            # data は "/message?sessionId=xxx" のような相対パス
                            base = self.url.rsplit("/", 1)[0]
                            self._message_url = base + data if data.startswith("/") else data
                            self._endpoint_ready.set()
                        elif event_type == "message":
                            try:
                                msg = json.loads(data)
                                msg_id = msg.get("id")
                                if msg_id is not None:
                                    with self._lock:
                                        q = self._response_queues.get(msg_id)
                                    if q:
                                        q.put(msg)
                            except json.JSONDecodeError:
                                pass
                        event_type = None
        except Exception as e:
            logger.error("SSE 読み取りエラー (%s): %s", self.name, e)

    def _request(self, method: str, params: dict) -> Any:
        req_id = self._next_id()
        q: queue.Queue = queue.Queue()
        with self._lock:
            self._response_queues[req_id] = q

        msg = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
        self._client.post(self._message_url, json=msg)

        try:
            resp = q.get(timeout=30)
            if "error" in resp:
                raise RuntimeError(f"{self.name}: {resp['error']}")
            return resp.get("result")
        finally:
            with self._lock:
                self._response_queues.pop(req_id, None)

    def _notify(self, method: str, params: dict) -> None:
        msg = {"jsonrpc": "2.0", "method": method, "params": params}
        self._client.post(self._message_url, json=msg)

    def close(self) -> None:
        self._client.close()


class StreamableHttpServerConnection(BaseServerConnection):
    """Streamable HTTP (MCP 2025-03-26) ベースの接続。

    JSON-RPC メッセージを直接 POST し、JSON または SSE 形式のレスポンスを処理する。
    Authorization ヘッダーが未指定の場合は OAuth 2.0 PKCE フローで自動認証する。
    """

    def __init__(self, name: str, config: dict) -> None:
        super().__init__(name)
        self.url = config["url"].rstrip("/")
        self._extra_headers: dict = config.get("headers", {})
        self._client = httpx.Client(timeout=60.0)

        # Authorization ヘッダーが明示されていなければ OAuth を試みる
        if "Authorization" not in self._extra_headers:
            from .oauth_client import OAuthClient
            self._oauth: "OAuthClient | None" = OAuthClient(name, self.url)
        else:
            self._oauth = None

    def connect(self) -> None:
        self._do_handshake()

    def _build_headers(self) -> dict:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        headers.update(self._extra_headers)
        if self._oauth:
            try:
                headers["Authorization"] = f"Bearer {self._oauth.get_access_token()}"
            except Exception as e:
                raise ConnectionError(f"{self.name}: OAuth 認証失敗: {e}") from e
        return headers

    def _post(self, msg: dict) -> httpx.Response:
        resp = self._client.post(self.url, json=msg, headers=self._build_headers())
        if resp.status_code == 401 and self._oauth:
            self._oauth.invalidate()
            resp = self._client.post(self.url, json=msg, headers=self._build_headers())
        resp.raise_for_status()
        return resp

    def _request(self, method: str, params: dict) -> Any:
        req_id = self._next_id()
        msg = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
        resp = self._post(msg)
        ct = resp.headers.get("content-type", "")
        if "text/event-stream" in ct:
            return self._extract_from_sse(resp.text, req_id)
        data = resp.json()
        if "error" in data:
            raise RuntimeError(f"{self.name}: {data['error']}")
        return data.get("result")

    def _extract_from_sse(self, text: str, req_id: int) -> Any:
        """SSE レスポンスのボディから指定 id のメッセージを取り出す。"""
        for line in text.splitlines():
            if not line.startswith("data:"):
                continue
            raw = line[5:].strip()
            try:
                msg = json.loads(raw)
                if msg.get("id") == req_id:
                    if "error" in msg:
                        raise RuntimeError(f"{self.name}: {msg['error']}")
                    return msg.get("result")
            except json.JSONDecodeError:
                pass
        return None

    def _notify(self, method: str, params: dict) -> None:
        msg = {"jsonrpc": "2.0", "method": method, "params": params}
        try:
            self._post(msg)
        except Exception as e:
            logger.debug("%s: 通知送信エラー（無視）: %s", self.name, e)

    def close(self) -> None:
        self._client.close()


def create_connection(name: str, config: dict) -> BaseServerConnection:
    """設定からサーバー接続オブジェクトを生成するファクトリ関数。"""
    server_type = config.get("type", "stdio")
    if server_type == "stdio":
        return StdioServerConnection(name, config)
    elif server_type == "sse":
        return SSEServerConnection(name, config)
    elif server_type in ("http", "streamable_http"):
        return StreamableHttpServerConnection(name, config)
    else:
        raise ValueError(f"未対応のサーバータイプ: {server_type} (stdio / sse / streamable_http)")
