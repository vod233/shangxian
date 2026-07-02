import atexit
import signal
import subprocess

_active_procs = []


def track(proc) -> None:
    _active_procs.append(proc)


def cleanup_subprocesses(procs) -> None:
    """优雅终止子进程，避免端口残留。"""
    for proc in procs:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        except Exception:
            pass


def _exit_hook(*_):
    cleanup_subprocesses(_active_procs)


atexit.register(_exit_hook)
signal.signal(signal.SIGTERM, _exit_hook)
