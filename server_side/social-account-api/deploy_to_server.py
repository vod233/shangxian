"""部署 social-account-api 到云服务器。

用法（PowerShell）：
    $env:SSH_PASS='your_password'
    python deploy_to_server.py

环境变量：
    SSH_HOST  服务器地址（默认 106.52.54.51）
    SSH_USER  SSH 用户（默认 root）
    SSH_PASS  SSH 密码（必填）
    SSH_PORT  SSH 端口（默认 22）
"""
import os
import sys
import stat
import io
import time

import paramiko

HOST = os.environ.get("SSH_HOST", "106.52.54.51")
USER = os.environ.get("SSH_USER", "root")
PASS = os.environ.get("SSH_PASS", "")
PORT = int(os.environ.get("SSH_PORT", "22"))

# 服务器端目录
REMOTE_DIR = "/www/wwwroot/CloudSever.lcjx.yun/social-account-api"

# 要上传的本地文件（相对脚本目录）
LOCAL_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FILES = ["main.py", "requirements.txt", "start.sh"]


def run(ssh: paramiko.SSHClient, cmd: str, timeout: int = 120) -> tuple[int, str, str]:
    """执行命令并返回 (exit_code, stdout, stderr)。"""
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    return code, out, err


def upload_file(sftp: paramiko.SFTPClient, local: str, remote: str) -> None:
    """上传单个文件。"""
    print(f"  上传 {os.path.basename(local)} -> {remote}")
    sftp.put(local, remote)


def main() -> int:
    if not PASS:
        print("ERROR: 未设置 SSH_PASS 环境变量", file=sys.stderr)
        return 2

    print(f"连接 {USER}@{HOST}:{PORT} ...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, port=PORT, username=USER, password=PASS, timeout=20)
    print("已连接")

    # 1. 创建目录
    print(f"\n[1/5] 创建目录 {REMOTE_DIR}")
    code, out, err = run(ssh, f"mkdir -p {REMOTE_DIR}/data && ls -la {REMOTE_DIR}")
    print(out)
    if err.strip():
        print("STDERR:", err)

    # 2. 上传文件
    print(f"\n[2/5] 上传文件")
    sftp = ssh.open_sftp()
    for fname in UPLOAD_FILES:
        local_path = os.path.join(LOCAL_DIR, fname)
        remote_path = f"{REMOTE_DIR}/{fname}"
        upload_file(sftp, local_path, remote_path)
        if fname.endswith(".sh"):
            # 设置可执行权限
            sftp.chmod(remote_path, stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
    sftp.close()
    print("上传完成")

    # 3. 检查 Python 环境
    print(f"\n[3/5] 检查服务器 Python 环境")
    code, out, err = run(ssh, "python3 --version; which python3; which pip3")
    print(out)

    # 4. 创建虚拟环境并安装依赖
    print(f"\n[4/5] 创建虚拟环境并安装依赖")
    cmds = [
        f"cd {REMOTE_DIR} && python3 -m venv venv 2>&1 | tail -3",
        f"cd {REMOTE_DIR} && venv/bin/pip install --upgrade pip 2>&1 | tail -3",
        f"cd {REMOTE_DIR} && venv/bin/pip install -r requirements.txt 2>&1 | tail -10",
    ]
    for cmd in cmds:
        code, out, err = run(ssh, cmd, timeout=180)
        print(out)
        if err.strip():
            print("STDERR:", err[-500:])

    # 5. 验证模块可导入
    print(f"\n[5/5] 验证模块可导入")
    code, out, err = run(ssh, f"cd {REMOTE_DIR} && venv/bin/python -c 'import main; print(\"import ok\")'")
    print(out)
    if code != 0:
        print("IMPORT FAILED:")
        print(err)
        return 1

    print("\n=== 部署文件就绪，下一步需配置 systemd 与 Nginx ===")
    ssh.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
