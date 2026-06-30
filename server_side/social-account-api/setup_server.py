"""服务器配置：创建 systemd 服务、配置 Nginx 反代、启动服务、测试。

用法：
    $env:SSH_PASS='your_password'
    python setup_server.py
"""
import os
import sys
import time

import paramiko

HOST = os.environ.get("SSH_HOST", "106.52.54.51")
USER = os.environ.get("SSH_USER", "root")
PASS = os.environ.get("SSH_PASS", "")
PORT = int(os.environ.get("SSH_PORT", "22"))

REMOTE_DIR = "/www/wwwroot/CloudSever.lcjx.yun/social-account-api"
SERVICE_NAME = "social-account-api"
SERVICE_FILE = f"/etc/systemd/system/{SERVICE_NAME}.service"
NGINX_CONF_SEARCH = "/www/wwwroot/CloudSever.lcjx.yun"  # 用作参考的 nginx 配置目录


def run(ssh: paramiko.SSHClient, cmd: str, timeout: int = 120) -> tuple[int, str, str]:
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    return code, out, err


def step(ssh: paramiko.SSHClient, num: str, desc: str, cmd: str, timeout: int = 120) -> None:
    print(f"\n[{num}] {desc}")
    print(f"$ {cmd}")
    code, out, err = run(ssh, cmd, timeout=timeout)
    if out.strip():
        print(out.rstrip())
    if err.strip():
        print("STDERR:", err.rstrip())
    print(f"exit_code={code}")


def main() -> int:
    if not PASS:
        print("ERROR: 未设置 SSH_PASS 环境变量", file=sys.stderr)
        return 2

    print(f"连接 {USER}@{HOST}:{PORT} ...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, port=PORT, username=USER, password=PASS, timeout=20)
    print("已连接")

    # 0. 先查看现有 Nginx 配置（了解 social-ai-credit-api 怎么反代的）
    step(ssh, "0a", "查看现有 Nginx 配置（找 social-ai-credit-api 反代规则）",
         "grep -rl 'social-ai-credit-api' /etc/nginx/ /www/server/panel/vhost/nginx/ 2>/dev/null | head -5")
    step(ssh, "0b", "查看 lcjx.yun 站点 Nginx 配置位置",
         "find /www/server/panel/vhost/nginx/ -name '*lcjx*' 2>/dev/null; ls /www/server/panel/vhost/nginx/ 2>/dev/null | head -20")
    step(ssh, "0c", "查看现有 social-ai-credit-api 服务部署方式",
         "ls -la /www/wwwroot/CloudSever.lcjx.yun/ 2>/dev/null; systemctl list-units --type=service | grep -i social 2>/dev/null")

    # 1. 创建 systemd 服务文件
    service_content = f"""[Unit]
Description=Social Account API
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory={REMOTE_DIR}
Environment=PG_HOST=127.0.0.1 PG_PORT=5432 PG_DB=scout PG_USER=scout PG_PASSWORD=scout123
Environment=HOST=127.0.0.1
Environment=PORT=8200
ExecStart={REMOTE_DIR}/venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8200 --workers 2
Restart=on-failure
RestartSec=5
StandardOutput=append:{REMOTE_DIR}/service.log
StandardError=append:{REMOTE_DIR}/service.err.log

[Install]
WantedBy=multi-user.target
"""
    # 用 heredoc 写文件
    step(ssh, "1", "创建 systemd 服务文件",
         f"cat > {SERVICE_FILE} <<'SERVICE_EOF'\n{service_content}SERVICE_EOF\n")
    step(ssh, "1b", "查看服务文件内容", f"cat {SERVICE_FILE}")

    # 2. 启动服务
    step(ssh, "2a", "reload systemd", "systemctl daemon-reload")
    step(ssh, "2b", "enable 开机自启", f"systemctl enable {SERVICE_NAME}")
    step(ssh, "2c", "restart 启动服务", f"systemctl restart {SERVICE_NAME}")
    time.sleep(3)
    step(ssh, "2d", "查看服务状态", f"systemctl status {SERVICE_NAME} --no-pager -l | head -20")

    # 3. 本机直连测试
    step(ssh, "3a", "本机 health 测试", "curl -s http://127.0.0.1:8200/health")
    step(ssh, "3b", "本机 register 测试",
         'curl -s -X POST http://127.0.0.1:8200/auth/register -H "Content-Type: application/json" -d \'{"email":"init@example.com","password":"init123"}\'')

    # 4. 检查 Nginx 配置（待手动处理）
    step(ssh, "4", "查看 lcjx.yun 站点完整 Nginx 配置（确定反代规则追加位置）",
         "find /www/server/panel/vhost/nginx/ -name '*lcjx*' -exec cat {} \\; 2>/dev/null | head -100")

    ssh.close()
    print("\n=== 配置脚本完成，下一步根据 Nginx 配置追加反代规则 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
