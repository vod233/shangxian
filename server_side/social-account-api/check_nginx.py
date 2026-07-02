"""检查 Nginx 配置中 social-account-api location 块的实际位置和上下文。"""
import os
import sys
import paramiko

HOST = os.environ.get("SSH_HOST", "106.52.54.51")
USER = os.environ.get("SSH_USER", "root")
PASS = os.environ.get("SSH_PASS", "")

NGINX_CONF = "/www/server/panel/vhost/nginx/lcjx.yun.conf"


def run(ssh, cmd, timeout=60):
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    return code, out, err


def main():
    if not PASS:
        print("ERROR: 未设置 SSH_PASS", file=sys.stderr)
        return 2
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=PASS, timeout=20)

    # 1. 查看我的 location 块上下文（前后各 15 行）
    print("=== social-account-api location 块上下文 ===")
    code, out, err = run(ssh, f"grep -n -B15 -A5 'social-account-api' {NGINX_CONF} | head -80")
    print(out)

    # 2. 查看所有 location 块（看是否有正则 location 干扰）
    print("\n=== 所有 location 块定义 ===")
    code, out, err = run(ssh, f"grep -n '^[[:space:]]*location' {NGINX_CONF}")
    print(out)

    # 3. 直接本机测试 health（绕过 nginx）
    print("\n=== 本机直连 8200/health ===")
    code, out, err = run(ssh, "curl -s http://127.0.0.1:8200/health")
    print(out)

    # 4. 本机通过 nginx 测试 health
    print("\n=== 本机通过 nginx 测试 /social-account-api/health ===")
    code, out, err = run(ssh, "curl -sv https://lcjx.yun/social-account-api/health 2>&1 | tail -30")
    print(out)

    # 5. 本机通过 nginx 测试 register（已成功，再验证一次）
    print("\n=== 本机通过 nginx 测试 /social-account-api/auth/login ===")
    code, out, err = run(ssh,
        'curl -s -X POST https://lcjx.yun/social-account-api/auth/login '
        '-H "Content-Type: application/json" '
        '-d \'{"email":"nginx_test@example.com","password":"nginx123"}\'')
    print(out)

    ssh.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
