"""stdio MCP プロキシ（ローカル MCP サーバー用）。

VS Code が起動するプロセスとして動作し、実際の MCP サーバーを
子プロセスとして起動してレスポンスをインターセプトする。

対応する MCP サーバー:
  - node 製（例: mcp-server-filesystem）
  - Python/uvx 製（例: mcp-server-fetch）
  - その他 stdio ベースの MCP サーバー全般
"""

import json
import logging
import subprocess
import sys
import threading

from .base import BaseProxy

logger = logging.getLogger("mcp_proxy.stdio")


class StdioProxy(BaseProxy):
    def run(self) -> None:
        if not self.args.server_cmd:
            print(
                "エラー: サーバーコマンドが指定されていません。\n"
                "使い方: python mcp_proxy.py [options] -- <command> [args...]",
                file=sys.stderr,
            )
            sys.exit(1)

        logger.info("stdio プロキシ起動: %s", self.args.server_cmd)

        server_proc = subprocess.Popen(
            self.args.server_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        threads = [
            threading.Thread(target=self._forward_stdin, args=(server_proc,), daemon=True, name="stdin"),
            threading.Thread(target=self._forward_stdout, args=(server_proc,), daemon=True, name="stdout"),
            threading.Thread(target=self._forward_stderr, args=(server_proc,), daemon=True, name="stderr"),
        ]
        for t in threads:
            t.start()

        try:
            server_proc.wait()
        except KeyboardInterrupt:
            server_proc.terminate()
            server_proc.wait()

        sys.exit(server_proc.returncode)

    def _process_message(self, message: dict) -> dict:
        result = message.get("result")
        if not isinstance(result, dict):
            return message
        content = result.get("content")
        if not isinstance(content, list):
            return message
        text_items = [
            item for item in content
            if isinstance(item, dict) and item.get("type") == "text" and item.get("text")
        ]
        if not text_items:
            return message

        combined_text = "\n".join(item["text"] for item in text_items)
        original_size = len(combined_text)
        processed_text, was_modified = self.pipeline.process(combined_text)

        if was_modified:
            logger.info("レスポンス処理: %d → %d 文字", original_size, len(processed_text))
            non_text_items = [item for item in content if item.get("type") != "text"]
            new_content = non_text_items + [{"type": "text", "text": processed_text}]
            message = {**message, "result": {**result, "content": new_content}}

        return message

    def _forward_stdin(self, server_proc: subprocess.Popen) -> None:
        try:
            for line in sys.stdin.buffer:
                server_proc.stdin.write(line)
                server_proc.stdin.flush()
        except Exception as e:
            logger.debug("stdin 転送終了: %s", e)
        finally:
            try:
                server_proc.stdin.close()
            except Exception:
                pass

    def _forward_stdout(self, server_proc: subprocess.Popen) -> None:
        out = sys.stdout.buffer
        try:
            for raw_line in server_proc.stdout:
                line = raw_line.rstrip(b"\r\n").decode("utf-8", errors="replace")
                if not line:
                    continue
                try:
                    message = json.loads(line)
                    if "result" in message and "id" in message:
                        message = self._process_message(message)
                    out.write((json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8"))
                except json.JSONDecodeError:
                    out.write(raw_line)
                out.flush()
        except Exception as e:
            logger.error("stdout 転送エラー: %s", e)

    def _forward_stderr(self, server_proc: subprocess.Popen) -> None:
        try:
            for line in server_proc.stderr:
                sys.stderr.buffer.write(line)
                sys.stderr.buffer.flush()
        except Exception:
            pass
