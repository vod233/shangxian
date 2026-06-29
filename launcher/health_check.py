import time
import requests


def wait_for_port(port: int, timeout: int = 30, path: str = "") -> bool:
    """轮询端口直到就绪或超时。"""
    deadline = time.time() + timeout
    url = f"http://127.0.0.1:{port}{path}"
    while time.time() < deadline:
        try:
            r = requests.get(url, timeout=0.5)
            if r.status_code < 500:
                return True
        except Exception:
            pass
        time.sleep(0.3)
    return False
