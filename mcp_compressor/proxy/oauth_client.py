"""MCP OAuth 2.0 PKCE クライアント。

MCP spec 2025-03-26 準拠:
  1. /.well-known/oauth-authorization-server でメタデータ取得
  2. 動的クライアント登録（RFC 7591）
  3. PKCE フロー + ローカルコールバックサーバー
  4. トークンキャッシュ（ファイル）+ 自動リフレッシュ
"""

import base64
import hashlib
import json
import os
import secrets
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

logger = __import__("logging").getLogger(__name__)


def _token_cache_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", "~")).expanduser()
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", "~/.config")).expanduser()
    d = base / "mcp-compressor" / "tokens"
    d.mkdir(parents=True, exist_ok=True)
    return d


class OAuthClient:
    def __init__(self, server_name: str, mcp_url: str) -> None:
        self.server_name = server_name
        self.mcp_url = mcp_url
        self._cache_file = _token_cache_dir() / f"{server_name}.json"
        self._token: dict | None = None
        self._meta: dict | None = None

    # ─────────────────────────────
    # 外部インターフェース
    # ─────────────────────────────

    def get_access_token(self) -> str:
        self._load_cache()
        if self._token and not self._is_expired():
            return self._token["access_token"]
        if self._token and self._token.get("refresh_token"):
            try:
                self._refresh()
                return self._token["access_token"]
            except Exception as e:
                logger.warning("%s: リフレッシュ失敗、再認証します: %s", self.server_name, e)
        self._do_browser_flow()
        return self._token["access_token"]

    def invalidate(self) -> None:
        """401 受信時にアクセストークンを無効化（次回呼び出しで refresh/再認証）。"""
        if self._token:
            self._token["expires_at"] = 0

    # ─────────────────────────────
    # キャッシュ
    # ─────────────────────────────

    def _load_cache(self) -> None:
        if self._cache_file.exists():
            try:
                self._token = json.loads(self._cache_file.read_text(encoding="utf-8"))
            except Exception:
                self._token = None

    def _save_cache(self) -> None:
        self._cache_file.write_text(
            json.dumps(self._token, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _is_expired(self) -> bool:
        return time.time() >= self._token.get("expires_at", 0) - 60

    # ─────────────────────────────
    # OAuth メタデータ
    # ─────────────────────────────

    def _fetch_meta(self) -> dict:
        if self._meta:
            return self._meta
        parsed = urlparse(self.mcp_url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        resp = httpx.get(
            f"{base}/.well-known/oauth-authorization-server",
            timeout=10,
            follow_redirects=True,
        )
        resp.raise_for_status()
        self._meta = resp.json()
        return self._meta

    # ─────────────────────────────
    # ブラウザ認証フロー（PKCE）
    # ─────────────────────────────

    def _do_browser_flow(self) -> None:
        meta = self._fetch_meta()
        auth_url   = meta["authorization_endpoint"]
        token_url  = meta["token_endpoint"]

        client_id = self._get_or_register_client(meta)

        # PKCE
        code_verifier = secrets.token_urlsafe(64)
        digest = hashlib.sha256(code_verifier.encode()).digest()
        code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()

        # ローカルコールバックサーバー（OS がポートを割り当て）
        code_holder: dict = {}
        ready = threading.Event()

        class _Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                qs = parse_qs(urlparse(self.path).query)
                code_holder["code"]  = qs.get("code",  [""])[0]
                code_holder["error"] = qs.get("error", [""])[0]
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(
                    "<h2>認証完了。このタブを閉じてください。</h2>".encode()
                )
                ready.set()

            def log_message(self, *_):
                pass

        callback_server = HTTPServer(("localhost", 0), _Handler)
        port = callback_server.server_address[1]
        redirect_uri = f"http://localhost:{port}/callback"

        t = threading.Thread(target=callback_server.handle_request, daemon=True)
        t.start()

        scopes = " ".join(meta.get("scopes_supported", []))
        params = {
            "response_type":         "code",
            "client_id":             client_id,
            "redirect_uri":          redirect_uri,
            "code_challenge":        code_challenge,
            "code_challenge_method": "S256",
        }
        if scopes:
            params["scope"] = scopes

        print(
            f"\n[mcp-compressor] {self.server_name}: ブラウザで認証してください...",
            file=sys.stderr, flush=True,
        )
        webbrowser.open(f"{auth_url}?{urlencode(params)}")

        if not ready.wait(timeout=120):
            callback_server.server_close()
            raise RuntimeError(f"{self.server_name}: OAuth 認証がタイムアウトしました（120秒）")
        callback_server.server_close()

        if code_holder.get("error"):
            raise RuntimeError(
                f"{self.server_name}: OAuth エラー: {code_holder['error']}"
            )
        code = code_holder.get("code", "")
        if not code:
            raise RuntimeError(f"{self.server_name}: 認証コードを受け取れませんでした")

        # コード → トークン
        resp = httpx.post(
            token_url,
            data={
                "grant_type":    "authorization_code",
                "code":          code,
                "redirect_uri":  redirect_uri,
                "client_id":     client_id,
                "code_verifier": code_verifier,
            },
            timeout=30,
        )
        resp.raise_for_status()
        token_data = resp.json()
        token_data["expires_at"] = time.time() + token_data.get("expires_in", 3600)
        token_data["client_id"]  = client_id
        self._token = token_data
        self._save_cache()

        print(
            f"[mcp-compressor] {self.server_name}: 認証完了。"
            f"トークンを {self._cache_file} に保存しました。",
            file=sys.stderr, flush=True,
        )

    # ─────────────────────────────
    # トークンリフレッシュ
    # ─────────────────────────────

    def _refresh(self) -> None:
        meta = self._fetch_meta()
        resp = httpx.post(
            meta["token_endpoint"],
            data={
                "grant_type":    "refresh_token",
                "refresh_token": self._token["refresh_token"],
                "client_id":     self._token.get("client_id", "mcp-compressor"),
            },
            timeout=30,
        )
        resp.raise_for_status()
        new_data = resp.json()
        new_data["expires_at"] = time.time() + new_data.get("expires_in", 3600)
        new_data.setdefault("client_id", self._token.get("client_id"))
        new_data.setdefault("refresh_token", self._token.get("refresh_token"))
        self._token = new_data
        self._save_cache()

    # ─────────────────────────────
    # 動的クライアント登録（RFC 7591）
    # ─────────────────────────────

    def _get_or_register_client(self, meta: dict) -> str:
        # キャッシュに client_id があれば再利用
        if self._token and self._token.get("client_id"):
            return self._token["client_id"]

        reg_endpoint = meta.get("registration_endpoint")
        if not reg_endpoint:
            return "mcp-compressor"

        resp = httpx.post(
            reg_endpoint,
            json={
                "client_name":                "mcp-compressor",
                "redirect_uris":              ["http://localhost"],
                "grant_types":                ["authorization_code", "refresh_token"],
                "response_types":             ["code"],
                "token_endpoint_auth_method": "none",
            },
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()["client_id"]
