#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# 验收/联调时可能留有旧的 uvicorn 进程占用 8020；先释放，保证启动的是当前代码与全新内存状态。
pkill -f "[u]vicorn app.main:app" 2>/dev/null || true
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
.venv/bin/pip install -q -r requirements.txt
exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8020
