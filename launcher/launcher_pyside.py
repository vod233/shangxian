"""PySide6 版 launcher：启动后端 FastAPI + PySide6 主窗口。

替代旧 launcher/main.py（Streamlit + pywebview），用于验证 PySide6 重构阶段 1。
- 后端：子进程跑 uvicorn（打包后通过 exe 自身重入）
- 前端：主进程直接启动 PySide6（含登录拦截）
"""
import os
import sys
import subprocess
import traceback
import datetime
import ctypes
from ctypes import c_int, byref, sizeof

from launcher.port_allocator import find_free_port
from launcher.health_check import wait_for_port
from launcher.process_manager import track, cleanup_subprocesses


def _log(msg: str) -> None:
    """诊断日志写到 exe 同级 launcher.log。"""
    try:
        base = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(base, "launcher.log"), "a", encoding="utf-8") as f:
            f.write(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}\n")
    except Exception:
        pass


def get_base_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def setup_env(base_dir: str) -> None:
    os.environ["NO_PROXY"] = "127.0.0.1"
    os.environ["no_proxy"] = "127.0.0.1"
    config_dir = os.path.join(base_dir, "config")
    os.makedirs(config_dir, exist_ok=True)
    os.environ["APP_CONFIG_DIR"] = config_dir


def start_api_proc(base_dir: str, api_port: int, frozen: bool):
    """启动后端 uvicorn 子进程。"""
    env = os.environ.copy()
    env["APP_API_PORT"] = str(api_port)
    env["APP_MODE"] = "api"
    env["PYTHONPATH"] = base_dir

    if frozen:
        cmd = [sys.executable]
    else:
        cmd = [sys.executable, "-m", "uvicorn", "backend.main:app",
               "--host", "127.0.0.1", "--port", str(api_port)]

    proc = subprocess.Popen(cmd, cwd=base_dir, env=env)
    track(proc)
    return proc


def _run_api_child():
    """打包后子进程重入：启动 uvicorn。"""
    _log(f"API 子进程重入: APP_MODE={os.environ.get('APP_MODE')}")
    # PyInstaller console=False 时 sys.stderr/stdout 可能为 None，uvicorn 的
    # default formatter 会调用 .isatty() 抛 AttributeError。重定向到文件兜底。
    base_dir = get_base_dir()
    if sys.stderr is None:
        sys.stderr = open(os.path.join(base_dir, "api_stderr.log"), "a", encoding="utf-8")
    if sys.stdout is None:
        sys.stdout = open(os.path.join(base_dir, "api_stdout.log"), "a", encoding="utf-8")
    try:
        import uvicorn
        from backend.main import app
        api_port = int(os.environ.get("APP_API_PORT", "8000"))
        _log(f"启动 uvicorn api_port={api_port}")
        uvicorn.run(app, host="127.0.0.1", port=api_port, log_level="info")
    except Exception as e:
        _log(f"API 子进程异常: {e}\n{traceback.format_exc()}")
        raise


def start_pyside_window(api_port: int):
    """主进程启动 PySide6 主窗口（含登录拦截）。"""
    os.environ["APP_API_URL"] = f"http://127.0.0.1:{api_port}/api"
    os.environ["QT_FONT_DPI"] = "96"

    # PyInstaller COLLECT 模式下 datas 在 _internal/，PyOneDark 用 cwd 找资源
    # （settings.json / gui/themes/*.json / gui/images/*.svg 等），需切 cwd
    base_dir = get_base_dir()
    internal_dir = os.path.join(base_dir, "_internal") if is_frozen() else base_dir
    if os.path.isdir(internal_dir):
        os.chdir(internal_dir)
        _log(f"cwd 已切到: {internal_dir}")

    try:
        # 登录拦截
        from gui.auth_dialog import require_login
        logged_in, account_email = require_login()
        if not logged_in:
            _log("用户未登录，退出")
            sys.exit(0)

        # 启动主窗口（gui_main.run_main_window 阻塞直到窗口关闭）
        import gui_main
        _log(f"主窗口已启动，登录账号: {account_email}")
        sys.exit(gui_main.run_main_window(account_email))
    except SystemExit:
        raise
    except Exception:
        _log(f"PySide6 启动异常:\n{traceback.format_exc()}")
        show_error("启动失败", traceback.format_exc())
        sys.exit(1)


def main():
    _log(f"=== main 开始 === frozen={is_frozen()}, APP_MODE={os.environ.get('APP_MODE')}, argv={sys.argv}")
    # 打包后 API 子进程重入点
    if is_frozen() and os.environ.get("APP_MODE") == "api":
        _run_api_child()
        return

    base_dir = get_base_dir()
    _log(f"base_dir={base_dir}")
    setup_env(base_dir)

    api_port = find_free_port()
    _log(f"分配端口: api={api_port}")

    api_proc = start_api_proc(base_dir, api_port, is_frozen())
    _log(f"API 子进程已启动: api_pid={api_proc.pid}")

    procs = [api_proc]
    try:
        if not wait_for_port(api_port, timeout=40, path="/docs"):
            _log(f"后端健康检查失败: api_port={api_port}")
            cleanup_subprocesses(procs)
            show_error("后端启动失败", f"FastAPI 端口 {api_port} 未就绪")
            return
        _log("后端就绪，启动 PySide6 主窗口")

        # 启动 PySide6 主窗口（阻塞直到窗口关闭）
        start_pyside_window(api_port)
    except Exception:
        _log(f"主流程异常:\n{traceback.format_exc()}")
    finally:
        _log("主窗口退出，清理子进程")
        cleanup_subprocesses(procs)


def show_error(title: str, msg: str):
    try:
        ctypes.windll.user32.MessageBoxW(0, msg, title, 0x10)
    except Exception:
        print(f"[{title}] {msg}")


if __name__ == "__main__":
    main()
