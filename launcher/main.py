import os
import sys
import subprocess
import traceback
import datetime
import ctypes
from ctypes import c_int, byref, sizeof

import webview

from launcher.port_allocator import find_free_port
from launcher.health_check import wait_for_port
from launcher.process_manager import track, cleanup_subprocesses


def _log(msg: str) -> None:
    """诊断日志写到 exe 同级 launcher.log（便于排查打包后问题）。"""
    try:
        base = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(base, "launcher.log"), "a", encoding="utf-8") as f:
            f.write(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}\n")
    except Exception:
        pass


def _enable_dark_titlebar(window_title: str) -> None:
    """通过 DWM API 将窗口标题栏设为深色模式（Win10 1809+）。"""
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW(None, window_title)
        if not hwnd:
            _log(f"深色标题栏: 未找到窗口 '{window_title}'")
            return
        dwmapi = ctypes.windll.dwmapi
        value = c_int(1)  # 1 = 深色模式
        # Win10 1903+ 用 attr=20，1809 用 attr=19
        for attr in (20, 19):
            res = dwmapi.DwmSetWindowAttribute(
                hwnd, attr, byref(value), sizeof(value)
            )
            if res == 0:
                _log(f"标题栏深色模式已设置: hwnd={hwnd}, attr={attr}")
                return
        _log("标题栏深色模式设置失败")
    except Exception as e:
        _log(f"设置标题栏深色异常: {e}")


def get_base_dir() -> str:
    """定位项目根目录（兼容源码运行与 PyInstaller 打包后运行）。"""
    if getattr(sys, "frozen", False):
        # 打包后：exe 在 dist/抖音AI群控/，依赖在同级 _internal/
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def setup_env(base_dir: str) -> None:
    os.environ["NO_PROXY"] = "127.0.0.1"
    os.environ["no_proxy"] = "127.0.0.1"
    # 配置目录：exe 同级 config/（便携式、稳定、无需权限）
    config_dir = os.path.join(base_dir, "config")
    os.makedirs(config_dir, exist_ok=True)
    os.environ["APP_CONFIG_DIR"] = config_dir


def _child_cmd(frozen: bool, base_dir: str):
    """构造子进程命令。打包后用 exe 自身重入，源码用 python -m。"""
    if frozen:
        return [sys.executable]
    return [sys.executable, "-m"]


def start_api_proc(base_dir: str, api_port: int, frozen: bool):
    env = os.environ.copy()
    env["APP_API_PORT"] = str(api_port)
    env["APP_MODE"] = "api"
    env["PYTHONPATH"] = base_dir

    if frozen:
        # 打包后：调用自身 exe，由 _run_child_mode 启动 uvicorn
        cmd = [sys.executable]
    else:
        cmd = [sys.executable, "-m", "uvicorn", "backend.main:app",
               "--host", "127.0.0.1", "--port", str(api_port)]

    proc = subprocess.Popen(cmd, cwd=base_dir, env=env)
    track(proc)
    return proc


def start_ui_proc(base_dir: str, ui_port: int, api_port: int, frozen: bool):
    env = os.environ.copy()
    env["APP_API_PORT"] = str(api_port)
    env["APP_MODE"] = "ui"
    env["PYTHONPATH"] = base_dir

    if frozen:
        # 打包后：调用自身 exe，由 _run_child_mode 启动 streamlit
        cmd = [sys.executable, "--ui-port", str(ui_port)]
    else:
        app_py = os.path.join(base_dir, "frontend", "app.py")
        cmd = [
            sys.executable, "-m", "streamlit", "run", app_py,
            "--server.port", str(ui_port),
            "--server.headless", "true",
            "--browser.gatherUsageStats", "false",
            "--server.address", "127.0.0.1",
        ]

    proc = subprocess.Popen(cmd, cwd=base_dir, env=env)
    track(proc)
    return proc


def _run_child_mode():
    """打包后子进程入口：根据 APP_MODE 启动对应服务。"""
    mode = os.environ.get("APP_MODE", "")
    _log(f"子进程重入: APP_MODE={mode}, argv={sys.argv}, _INTERNAL_ROOT={os.environ.get('_INTERNAL_ROOT')}")
    try:
        if mode == "api":
            import uvicorn
            from backend.main import app
            api_port = int(os.environ.get("APP_API_PORT", "8000"))
            _log(f"启动 uvicorn api_port={api_port}")
            uvicorn.run(app, host="127.0.0.1", port=api_port, log_level="info")
        elif mode == "ui":
            from streamlit.web import cli as stcli
            ui_port = None
            args = sys.argv[1:]
            for i, a in enumerate(args):
                if a == "--ui-port" and i + 1 < len(args):
                    ui_port = args[i + 1]
            if not ui_port:
                ui_port = "8501"
            app_py = os.path.join(os.environ.get("_INTERNAL_ROOT", ""), "frontend", "app.py")
            _log(f"启动 streamlit ui_port={ui_port}, app_py={app_py}, exists={os.path.exists(app_py)}")
            streamlit_args = [
                "run", app_py,
                "--server.port", ui_port,
                "--server.headless", "true",
                "--browser.gatherUsageStats", "false",
                "--server.address", "127.0.0.1",
                "--global.developmentMode", "false",
            ]
            sys.argv = ["streamlit"] + streamlit_args
            stcli.main()
        else:
            _log(f"未知 APP_MODE: {mode}")
    except Exception as e:
        _log(f"子进程异常: {e}\n{traceback.format_exc()}")
        raise


def main():
    _log(f"=== main 开始 === frozen={is_frozen()}, APP_MODE={os.environ.get('APP_MODE')}, argv={sys.argv}")
    # 打包后子进程重入点
    if is_frozen() and os.environ.get("APP_MODE") in ("api", "ui"):
        _run_child_mode()
        return

    base_dir = get_base_dir()
    _log(f"base_dir={base_dir}")
    # 告知子进程 _internal 根目录（streamlit 需定位 app.py）
    os.environ["_INTERNAL_ROOT"] = os.path.join(base_dir, "_internal") if is_frozen() else base_dir
    setup_env(base_dir)

    api_port = find_free_port()
    ui_port = find_free_port()
    _log(f"分配端口: api={api_port}, ui={ui_port}")

    api_proc = start_api_proc(base_dir, api_port, is_frozen())
    ui_proc = start_ui_proc(base_dir, ui_port, api_port, is_frozen())
    _log(f"子进程已启动: api_pid={api_proc.pid}, ui_pid={ui_proc.pid}")

    procs = [api_proc, ui_proc]

    try:
        if not wait_for_port(api_port, timeout=40, path="/docs"):
            _log(f"后端健康检查失败: api_port={api_port}")
            cleanup_subprocesses(procs)
            show_error("后端启动失败", f"FastAPI 端口 {api_port} 未就绪")
            return
        _log("后端就绪")
        if not wait_for_port(ui_port, timeout=40):
            _log(f"前端健康检查失败: ui_port={ui_port}")
            cleanup_subprocesses(procs)
            show_error("前端启动失败", f"Streamlit 端口 {ui_port} 未就绪")
            return
        _log("前端就绪")

        window = webview.create_window(
            "抖音AI群控",
            url=f"http://127.0.0.1:{ui_port}",
            width=1440,
            height=900,
            min_size=(1024, 700),
        )

        def on_closing():
            _log("窗口关闭，清理子进程")
            cleanup_subprocesses(procs)

        def on_loaded():
            # 窗口加载完成后设置标题栏深色，与 UI 配色统一
            _enable_dark_titlebar("抖音AI群控")

        window.events.closing += on_closing
        window.events.loaded += on_loaded
        _log("启动 webview 窗口")
        webview.start()
    except Exception:
        _log(f"主流程异常:\n{traceback.format_exc()}")
        cleanup_subprocesses(procs)


def show_error(title: str, msg: str):
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, msg, title, 0x10)
    except Exception:
        print(f"[{title}] {msg}")


if __name__ == "__main__":
    main()
