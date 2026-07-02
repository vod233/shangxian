"""SSH 助手"""
import os, sys, paramiko, warnings
warnings.filterwarnings("ignore")
HOST = os.environ.get("SSH_HOST", "106.52.54.51")
USER = os.environ.get("SSH_USER", "root")
PWD = os.environ.get("SSH_PWD", "")
PORT = int(os.environ.get("SSH_PORT", "22"))
def _client():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, port=PORT, username=USER, password=PWD, timeout=15, banner_timeout=15, auth_timeout=15)
    return c
def run(cmd, timeout=180):
    c = _client()
    try:
        _, out, err = c.exec_command(cmd, timeout=timeout, get_pty=False)
        return out.channel.recv_exit_status(), out.read().decode("utf-8","replace"), err.read().decode("utf-8","replace")
    finally:
        c.close()
def download(remote, local):
    c = _client()
    try:
        s = c.open_sftp(); s.get(remote, local); s.close(); return True, f"ok {remote}->{local}"
    finally:
        c.close()
def upload(local, remote):
    c = _client()
    try:
        s = c.open_sftp(); s.put(local, remote); s.close(); return True, f"ok {local}->{remote}"
    finally:
        c.close()
if __name__ == "__main__":
    op = sys.argv[1]
    if op == "download": _, m = download(sys.argv[2], sys.argv[3]); sys.stdout.write(m+"\n")
    elif op == "upload": _, m = upload(sys.argv[2], sys.argv[3]); sys.stdout.write(m+"\n")
    else:
        rc, out, err = run(" ".join(sys.argv[1:]), 180)
        sys.stdout.write(out)
        if err: sys.stderr.write("\n----STDERR----\n"+err)
        sys.exit(rc)
