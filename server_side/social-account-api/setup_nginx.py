"""查找 Nginx 中 social-ai-credit-api 反代规则，追加 social-account-api 反代。

用法：
    $env:SSH_PASS='your_password'
    python setup_nginx.py
"""
import os
import sys
import time
import re

import paramiko

HOST = os.environ.get("SSH_HOST", "106.52.54.51")
USER = os.environ.get("SSH_USER", "root")
PASS = os.environ.get("SSH_PASS", "")
PORT = int(os.environ.get("SSH_PORT", "22"))

NGINX_CONF = "/www/server/panel/vhost/nginx/lcjx.yun.conf"


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

    # 1. 备份配置
    ts = time.strftime("%Y%m%d-%H%M%S")
    backup = f"{NGINX_CONF}.bak-account-{ts}"
    code, out, err = run(ssh, f"cp {NGINX_CONF} {backup} && echo 'backup: {backup}'")
    print(out)

    # 2. 查找 social-ai-credit-api 反代规则（包含上下文）
    print("=== 查找 social-ai-credit-api 反代规则 ===")
    code, out, err = run(ssh, f"grep -n 'social-ai-credit-api\\|social-account-api' {NGINX_CONF}")
    print(out)
    if err.strip():
        print("STDERR:", err)

    # 3. 提取包含 social-ai-credit-api 的 location 块（grep -A 30 上下文）
    print("\n=== social-ai-credit-api 反代规则上下文（前40行起）===")
    code, out, err = run(ssh, f"grep -n -B2 -A20 'social-ai-credit-api' {NGINX_CONF} | head -80")
    print(out)

    # 4. 查看现有 social-ai-credit.service 监听端口（参考）
    print("\n=== social-ai-credit 服务监听端口 ===")
    code, out, err = run(ssh, "systemctl cat social-ai-credit.service 2>/dev/null | grep -E 'ExecStart|Environment' | head -10")
    print(out)

    ssh.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
