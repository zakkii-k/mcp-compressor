FROM python:3.11-slim

# Node.js LTS（node ベースの MCP サーバー向け）
# 他のランタイムが必要な場合はここに追加
RUN apt-get update && apt-get install -y curl && \
    curl -fsSL https://deb.nodesource.com/setup_lts.x | bash - && \
    apt-get install -y nodejs && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 依存パッケージを先にコピー（レイヤーキャッシュ活用）
COPY pyproject.toml .
RUN pip install --no-cache-dir httpx pyyaml python-toon

# ソースをコピー
COPY . .

# Docker コンテナ内から host の Ollama に接続するための設定
# Windows / Mac: host.docker.internal で host に到達できる
# Linux (--network host の場合): localhost でも到達できるが統一のためこちらを使用
ENV OLLAMA_URL=http://host.docker.internal:11434

ENTRYPOINT ["python", "mcp_proxy.py"]
