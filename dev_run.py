"""开发模式启动器：源码直接运行 PySide6 主窗口（秒级重启）。

用法：
    python dev_run.py            # 完整流程（后端 + 登录 + 主窗口）
    python dev_run.py --no-api   # 跳过后端启动（已有后端在跑时用）
    python dev_run.py --no-auth  # 跳过登录拦截（调试 UI 时用）

开发循环：
    1. 改代码（gui/pages/*.py 或 common.py）
    2. Ctrl+C 停止 dev_run.py
    3. python dev_run.py 重启（2 秒内看到新效果）

与打包流程对比：
    - 打包：PyInstaller 3-5 分钟 + 复制 dist + 启动 exe
    - 开发：Ctrl+C + python dev_run.py（2 秒）

样式调整：
    所有 QSS 样式集中在 gui/pages/common.py 的 qss_xxx() 函数
    改一处 c("context_color") 或字体大小，11 个页面统一生效
"""
import os
import sys
import subprocess
import time
import signal
import threading
import traceback
import faulthandler

# 启用 faulthandler：segfault 时打印 Python 堆栈跟踪到文件和 stderr
_fault_log = open(os.path.join(os.path.dirname(__file__), "crash_trace.log"), "w")
faulthandler.enable(file=_fault_log, all_threads=True)

# M2修复：安装全局 sys.excepthook，捕获 Python 层未捕获异常（如槽函数中的 TypeError），
# faulthandler 只能捕获 C 级 segfault，无法捕获 Python 异常。
# PySide6 槽函数异常会被静默吞掉，excepthook 能在 crash_trace.log 留下痕迹。
_orig_excepthook = sys.excepthook
def _excepthook(exctype, value, tb):
    import traceback as _tb
    _fault_log.write("=" * 60 + "\n")
    _fault_log.write(f"未捕获异常 ({exctype.__name__}): {value}\n")
    _tb.print_exception(exctype, value, tb, file=_fault_log)
    _fault_log.write("=" * 60 + "\n")
    _fault_log.flush()
    # 同时输出到 stderr 便于控制台查看
    _orig_excepthook(exctype, value, tb)
sys.excepthook = _excepthook

# 确保项目根目录在 sys.path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

from launcher.port_allocator import find_free_port
from launcher.health_check import wait_for_port
from launcher.process_manager import track, cleanup_subprocesses


# 全局子进程列表（Ctrl+C 时清理）
_PROCS = []


def log(msg: str):
    """彩色控制台日志。"""
    color = {
        "info": "\033[36m",     # cyan
        "ok": "\033[32m",       # green
        "warn": "\033[33m",     # yellow
        "err": "\033[31m",      # red
        "dim": "\033[90m",      # gray
    }.get(msg.split(":", 1)[0].lower(), "")
    reset = "\033[0m"
    ts = time.strftime("%H:%M:%S")
    print(f"{color}[{ts}] {msg}{reset}")


def start_api(api_port: int) -> subprocess.Popen:
    """启动后端 uvicorn 子进程。

    关键修复：
    1. 移除 --reload：任务执行时数据库文件频繁变化会触发 uvicorn 重启，
       导致 API 中断甚至 GUI 进程被信号终止。
    2. 使用 CREATE_NEW_PROCESS_GROUP：后端在独立进程组中运行，
       避免 Ctrl+C / SIGINT 信号传播到 GUI 主进程。
    """
    env = os.environ.copy()
    env["APP_API_PORT"] = str(api_port)
    env["APP_MODE"] = "api"
    env["PYTHONPATH"] = PROJECT_ROOT
    env["NO_PROXY"] = "127.0.0.1"
    env["no_proxy"] = "127.0.0.1"

    cmd = [
        sys.executable, "-m", "uvicorn", "backend.main:app",
        "--host", "127.0.0.1", "--port", str(api_port),
    ]
    log(f"info:启动后端 uvicorn（端口 {api_port}）")
    proc = subprocess.Popen(
        cmd, cwd=PROJECT_ROOT, env=env,
        # 后端日志直接输出到当前控制台
        stdout=sys.stdout, stderr=sys.stderr,
        # 独立进程组：防止后端信号传播到 GUI 主进程
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    track(proc)
    _PROCS.append(proc)
    return proc


def setup_auth_env(api_port: int):
    """设置登录拦截所需的环境变量。"""
    os.environ["APP_API_URL"] = f"http://127.0.0.1:{api_port}/api"
    os.environ["APP_CONFIG_DIR"] = os.path.join(PROJECT_ROOT, "config")
    os.makedirs(os.environ["APP_CONFIG_DIR"], exist_ok=True)
    os.environ["QT_FONT_DPI"] = "96"


def run_pyside_with_auth(api_port: int, skip_auth: bool = False):
    """启动 PySide6 主窗口（含登录拦截）。

    skip_auth=True 时跳过登录，直接进主窗口（调试 UI 用）。
    """
    setup_auth_env(api_port)

    if not skip_auth:
        from gui.auth_dialog import require_login
        logged_in, account_email = require_login()
        if not logged_in:
            log("warn:用户未登录，退出")
            return
    else:
        account_email = "dev@debug.test"
        log("warn:已跳过登录拦截（--no-auth 模式）")

    import gui_main
    log(f"ok:主窗口已启动，登录账号: {account_email}")
    try:
        exit_code = gui_main.run_main_window(account_email)
        log(f"info:GUI 事件循环退出，退出码={exit_code}")
    except KeyboardInterrupt:
        log("warn:GUI 收到键盘中断，忽略（仅通过 Ctrl+C 按钮退出）")
    except Exception:
        log("err:GUI 主窗口异常退出：")
        traceback.print_exc()


def cleanup(signum=None, frame=None):
    """Ctrl+C 或异常退出时清理子进程。"""
    log("dim:清理子进程...")
    cleanup_subprocesses(_PROCS)
    _PROCS.clear()


def main():
    # 解析参数
    skip_api = "--no-api" in sys.argv
    skip_auth = "--no-auth" in sys.argv

    # 注册信号处理：Ctrl+C 时清理子进程
    # 注意：后端在独立进程组中，后端的信号不会传播到这里
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    print("\n" + "=" * 60)
    print("  抖音AI群控 - 开发模式启动器")
    print("  PySide6 源码运行（秒级重启，无需打包）")
    print("=" * 60)
    print()
    print("  用法：")
    print("    python dev_run.py             完整流程")
    print("    python dev_run.py --no-api    跳过后端（已有后端时）")
    print("    python dev_run.py --no-auth    跳过登录（调试 UI 时）")
    print()
    print("  样式调整：改 gui/pages/common.py 的 qss_xxx() 函数")
    print("  页面调整：改 gui/pages/<page>_page.py")
    print("  开发循环：Ctrl+C → python dev_run.py（2 秒重启）")
    print()
    print("-" * 60 + "\n")

    api_port = None
    try:
        if not skip_api:
            api_port = find_free_port()
            api_proc = start_api(api_port)
            log(f"info:等待后端就绪（最多 40 秒）...")
            if not wait_for_port(api_port, timeout=40, path="/docs"):
                log("err:后端启动失败，请检查 backend/main.py")
                cleanup()
                return
            log("ok:后端就绪")
        else:
            # --no-api 模式：复用默认端口或环境变量
            api_port = int(os.environ.get("APP_API_PORT", "8000"))
            # 尝试连接，如果失败提示用户先启动后端
            import requests
            try:
                requests.get(f"http://127.0.0.1:{api_port}/docs", timeout=2)
                log(f"ok:检测到后端已在端口 {api_port} 运行")
            except Exception:
                log(f"err:--no-api 模式但端口 {api_port} 无后端，请先运行：")
                print(f"    python -m uvicorn backend.main:app --port {api_port} --reload")
                return

        # 启动 PySide6 主窗口（阻塞）
        run_pyside_with_auth(api_port, skip_auth=skip_auth)

    except KeyboardInterrupt:
        log("warn:收到 Ctrl+C，退出")
    except Exception:
        log("err:开发模式启动异常：")
        traceback.print_exc()
    finally:
        cleanup()


if __name__ == "__main__":
    main()
