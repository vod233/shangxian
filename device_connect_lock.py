import os
import time
from contextlib import contextmanager

import uiautomator2 as u2


LOCK_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".uiautomator2_connect.lock")


@contextmanager
def uiautomator2_connect_lock(timeout=1200):
    """
    文件锁，确保同一时间只有一个进程/线程初始化 UIAutomator2 连接。

    FIX(DEV-S1):
    旧实现 timeout=600s，在 50 并发下 u2.connect() 串行通过全局锁，
    单台首次连接（atx-agent 推送 + APK 启动 + 端口转发 + HTTP 健康探测）常耗时 10-30s，
    50 台串行总耗时约 500-1500s，600s 超时在慢机/老 Android 设备场景下会被触发，
    导致后段设备直接 error。这里提高到 1200s（20 分钟），覆盖最坏情况；
    同时修正旧注释（旧注释写"120 秒"但实际默认 600s，文档与代码不符）。
    """
    start = time.time()
    lock_file = open(LOCK_PATH, "a+b")
    locked = False
    try:
        if os.name == "nt":
            import msvcrt

            while not locked:
                try:
                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                    locked = True
                except OSError:
                    if time.time() - start >= timeout:
                        raise TimeoutError("等待 UIAutomator2 连接锁超时")
                    time.sleep(0.2)
            yield
        else:
            import fcntl

            while not locked:
                try:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    locked = True
                except BlockingIOError:
                    if time.time() - start >= timeout:
                        raise TimeoutError("等待 UIAutomator2 连接锁超时")
                    time.sleep(0.2)
            yield
    finally:
        if locked:
            if os.name == "nt":
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        lock_file.close()


def locked_u2_connect(serial):
    with uiautomator2_connect_lock():
        return u2.connect(serial)
