"""在 lcjx.yun.conf 中追加 social-account-api 反代规则并 reload。

用法：
    $env:SSH_PASS='your_password'
    python apply_nginx.py
"""
import os
import sys
import time

import paramiko

HOST = os.environ.get("SSH_HOST", "106.52.54.51")
USER = os.environ.get("SSH_USER", "root")
PASS = os.environ.get("SSH_PASS", "")
PORT = int(os.environ.get("SSH_PORT", "22"))

NGINX_CONF = "/www/server/panel/vhost/nginx/lcjx.yun.conf"

# 要追加的反代规则（紧跟现有 social-ai-credit-api location 块之后）
NGINX_SNIPPET = """
    location /social-account-api/ {
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

# 锚点：在 social-ai-credit-api location 块结束的 } 后插入
# 现有结构：line 203 是 "    }"，line 204 是空行，line 205 是 "    location = /juxing-assistant.apk {"
# 我们在 "    location /social-ai-credit-api/" 块的结尾 "}" 之后插入
ANCHOR = """    location /social-ai-credit-api/ {
        proxy_pass http://127.0.0.1:8020/api/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 30s;
        proxy_send_timeout 120s;
        proxy_read_timeout 120s;
    }
"""


def run(ssh: paramiko.SSHClient, cmd: str, timeout: int = 120) -> tuple[int, str, str]:
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    return code, out, err


def main() -> int:
    if not PASS:
        print("ERROR: 未设置 SSH_PASS", file=sys.stderr)
        return 2

    print(f"连接 {USER}@{HOST}:{PORT} ...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, port=PORT, username=USER, password=PASS, timeout=20)
    print("已连接\n")

    # 1. 备份
    ts = time.strftime("%Y%m%d-%H%M%S")
    backup = f"{NGINX_CONF}.bak-apply-{ts}"
    code, out, err = run(ssh, f"cp {NGINX_CONF} {backup} && echo 'backup ok: {backup}'")
    print(out)

    # 2. 上传 patch 脚本并运行
    sftp = ssh.open_sftp()
    local_patch = os.path.join(os.path.dirname(os.path.abspath(__file__)), "patch_nginx_conf.py")
    remote_patch = "/tmp/patch_nginx_conf.py"
    print(f"上传 {os.path.basename(local_patch)} -> {remote_patch}")
    sftp.put(local_patch, remote_patch)
    sftp.close()

    code, out, err = run(ssh, f"python3 {remote_patch}")
    print("patch 结果:", out)
    if err.strip():
        print("STDERR:", err)
    if code != 0:
        print("patch 失败，终止")
        return 1

    # 4. nginx -t 测试配置
    print("\n=== nginx -t ===")
    code, out, err = run(ssh, "nginx -t 2>&1")
    print(out)
    if code != 0:
        print("nginx -t 失败：")
        print(err)
        return 1

    # 5. reload
    print("\n=== nginx -s reload ===")
    code, out, err = run(ssh, "nginx -s reload 2>&1 && echo reload_ok")
    print(out)
    if code != 0:
        print("reload 失败：", err)
        return 1

    # 6. 验证：通过 https://lcjx.yun/social-account-api/health 测试
    print("\n=== 通过域名验证 ===")
    code, out, err = run(ssh, "curl -s https://lcjx.yun/social-account-api/health")
    print("health:", out)
    if err.strip():
        print("STDERR:", err)

    # 7. 通过域名测试 register
    print("\n=== 通过域名测试 register ===")
    code, out, err = run(ssh,
        'curl -s -X POST https://lcjx.yun/social-account-api/auth/register '
        '-H "Content-Type: application/json" '
        '-d \'{"email":"nginx_test@example.com","password":"nginx123"}\'')
    print("register:", out)

    ssh.close()
    print("\n=== Nginx 配置完成 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
