#!/bin/bash
# 启动账号微服务（监听 127.0.0.1:8200，仅本机 Nginx 反代访问）
# PostgreSQL 连接参数通过项目根 .env 或系统环境变量注入 (PG_HOST/PG_PORT/PG_DB/PG_USER/PG_PASSWORD)
cd "$(dirname "$0")"
export HOST="127.0.0.1"
export PORT="8200"
exec python3 -m uvicorn main:app --host 127.0.0.1 --port 8200 --workers 2
