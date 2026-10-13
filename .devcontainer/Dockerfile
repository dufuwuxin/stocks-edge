FROM mcr.microsoft.com/devcontainers/python:3.12-bookworm

# 零构建原则: 全部依赖在镜像构建时装好, Codespace 启动即可跑
RUN apt-get update && apt-get install -y --no-install-recommends \\
        git curl jq sqlite3 \\
    && rm -rf /var/lib/apt/lists/*

# Python 依赖 (与项目一致)
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# 预创建工作目录结构, 避免首次 clone 权限问题
RUN mkdir -p /workspaces/stocks-data-kline/data/bulk \\
             /workspaces/stocks-data-live/data \\
             /workspaces/stocks-ai-view/data

WORKDIR /workspaces/stocks-data-kline
