"""服务器端运行：在 lcjx.yun.conf 中追加 social-account-api 反代规则。

策略：在 "location /social-ai-credit-api/" 那一行之前插入新 location 块。
幂等：若已存在 social-account-api 则跳过。
"""
import sys

CONF = "/www/server/panel/vhost/nginx/lcjx.yun.conf"

SNIPPET = """    location /social-account-api/ {
        proxy_pass http://127.0.0.1:8200/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 30s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }
"""

ANCHOR = "    location /social-ai-credit-api/ {"

with open(CONF, "r", encoding="utf-8") as f:
    content = f.read()

if "social-account-api" in content:
    print("social-account-api 规则已存在，跳过")
    sys.exit(0)

if ANCHOR not in content:
    print("ERROR: 锚点未找到")
    sys.exit(1)

# 在锚点之前插入新块（保留原锚点）
new_content = content.replace(ANCHOR, SNIPPET + "\n" + ANCHOR, 1)
with open(CONF, "w", encoding="utf-8") as f:
    f.write(new_content)
print("inserted ok")
