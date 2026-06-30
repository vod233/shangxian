# DEPRECATED: PostgreSQL migration complete. Use psql instead.
# Original script follows:
#!/bin/bash
TS=$(date +%Y%m%d-%H%M%S)
cp /www/wwwroot/CloudSever.lcjx.yun/app/credit_server/server.py /www/wwwroot/CloudSever.lcjx.yun/app/credit_server/server.py.bak-review-$TS
cp /www/wwwroot/CloudSever.lcjx.yun/app/data/credit_server.db /www/wwwroot/CloudSever.lcjx.yun/app/data/credit_server.db.bak-review-$TS
echo "backup done TS=$TS"
ls -la /www/wwwroot/CloudSever.lcjx.yun/app/credit_server/server.py.bak-review-$TS /www/wwwroot/CloudSever.lcjx.yun/app/data/credit_server.db.bak-review-$TS
