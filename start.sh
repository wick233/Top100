#!/usr/bin/env bash
# 启动美股Top100历史报表 (默认端口8000)
cd "$(dirname "$0")"
PORT="${1:-8000}"
shift $(( $# > 0 ? 1 : 0 ))
exec .venv/bin/python -m uvicorn server:app --host 0.0.0.0 --port "$PORT" "$@"