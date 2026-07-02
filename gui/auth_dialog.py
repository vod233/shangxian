"""账号登录对话框（PySide6 版）。

启动应用时弹出，未登录则不允许进入主面板。
登录态通过 config/auth.json 持久化，已登录下次自动跳过。
"""
import os
import requests
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import (
    QApplication, QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QTabWidget, QFormLayout, QFrame,
    QMessageBox, QSizePolicy
)

# 后端 API 地址（与 launcher 一致，由环境变量覆盖）
# 问题4修复：默认端口由 8300 改为 8000，与 common.py 和 backend/main.py 实际监听端口一致
API_BASE_URL = os.environ.get("APP_API_URL", "http://127.0.0.1:8000/api")


# ======================== 异步网络请求线程 ========================
class _AuthWorker(QThread):
    """在后台线程发起 HTTP 请求，避免阻塞 UI。

    P7修复：类级别引用池，防止 worker 在 run() 未结束时被 GC 过早回收。
    P9修复（根因）：原代码用 `finished = Signal(dict)` 覆盖了 QThread 内置的
           finished 信号，破坏 Qt 内部线程管理，导致 run() 返回时
           STATUS_STACK_BUFFER_OVERRUN (0xC0000409) 崩溃。
           改用自定义信号 result_ready 传递结果，保留内置 finished 用于清理。
    """
    result_ready = Signal(dict)
    _alive_workers = set()

    def __init__(self, method: str, path: str, json_body: dict = None, token: str = ""):
        super().__init__()
        self.method = method
        self.path = path
        self.json_body = json_body or {}
        self.token = token
        # 连接到 QThread 内置 finished 信号（run() 返回后自动发射），用于清理
        self.finished.connect(self._on_finished_cleanup)
        self._alive_workers.add(self)

    def _on_finished_cleanup(self, *_):
        self._alive_workers.discard(self)
        self.deleteLater()

    def run(self):
        url = f"{API_BASE_URL.rstrip('/')}{self.path}"
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        try:
            if self.method == "GET":
                resp = requests.get(url, headers=headers, timeout=15)
            else:
                resp = requests.post(url, json=self.json_body, headers=headers, timeout=20)
            try:
                data = resp.json()
            except Exception:
                data = {"success": False, "message": f"服务响应异常：HTTP {resp.status_code}"}
            data["_status_code"] = resp.status_code
        except requests.RequestException as exc:
            data = {"success": False, "message": f"网络错误：{exc}", "_status_code": 0}
        self.result_ready.emit(data)


# ======================== 登录对话框 ========================
class LoginDialog(QDialog):
    """登录/注册对话框。成功登录返回 QDialog.Accepted。"""

    THEME = {
        "bg": "#0D1117",
        "card_bg": "#161B28",
        "border": "#30363D",
        "text": "#FFFFFF",
        "text_sub": "#D1D5DB",
        "text_muted": "#6B7280",
        "accent": "#6366F1",
        "accent_hover": "#818CF8",
        "accent_pressed": "#4F46E5",
        "danger": "#EF4444",
        "input_bg": "#0D1117",
        "input_border": "#30363D",
    }

    @staticmethod
    def _title_font():
        """获取标题字体：Microsoft YaHei UI（Windows 系统自带，合法商用）。"""
        f = QFont("Microsoft YaHei UI", 18)
        f.setBold(True)
        return f

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None  # 防止被 GC
        self._email = ""
        self._build_ui()
        self._apply_styles()

    # ---------- UI 构建 ----------
    def _build_ui(self):
        self.setWindowTitle("抖音AI群控 · 账号登录")
        self.setFixedSize(440, 540)

        # 外层容器（背景色）
        outer = QWidget(self)
        outer.setGeometry(0, 0, 440, 540)
        outer.setStyleSheet(f"background-color: {self.THEME['bg']};")

        # 卡片容器
        card = QFrame(outer)
        card.setGeometry(50, 50, 340, 440)
        card.setStyleSheet(
            f"background-color: {self.THEME['card_bg']};"
            f"border: 1px solid {self.THEME['border']};"
            f"border-radius: 12px;"
        )

        # 主布局
        layout = QVBoxLayout(card)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(12)

        # 标题
        title = QLabel("抖音AI群控")
        title.setAlignment(Qt.AlignCenter)
        title.setFont(self._title_font())
        title.setStyleSheet(f"color: {self.THEME['text']}; border: none; background: transparent;")
        layout.addWidget(title)

        subtitle = QLabel("请登录账号后进入管理面板")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet(
            f"color: {self.THEME['text_muted']}; font-size: 12px; "
            f"border: none; background: transparent;"
        )
        layout.addWidget(subtitle)

        layout.addSpacing(8)

        # tab：登录 / 注册
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(self._tab_style())
        self.tabs.addTab(self._build_login_tab(), "登录")
        self.tabs.addTab(self._build_register_tab(), "注册")
        layout.addWidget(self.tabs, 1)

        # 底部提示
        foot = QLabel("账号仅用于登录门禁，启动任务仍需授权码")
        foot.setAlignment(Qt.AlignCenter)
        foot.setStyleSheet(
            f"color: {self.THEME['text_muted']}; font-size: 11px; "
            f"border: none; background: transparent;"
        )
        layout.addWidget(foot)

        # 错误提示标签（默认隐藏）
        self.err_label = QLabel("")
        self.err_label.setWordWrap(True)
        self.err_label.setAlignment(Qt.AlignCenter)
        self.err_label.setStyleSheet(
            f"color: {self.THEME['danger']}; font-size: 12px; "
            f"background: rgba(239,68,68,0.08); "
            f"border: 1px solid rgba(239,68,68,0.25); border-radius: 6px; "
            f"padding: 8px;"
        )
        self.err_label.hide()
        layout.addWidget(self.err_label)

    def _build_login_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)
        form.setContentsMargins(0, 10, 0, 0)
        form.setSpacing(10)

        self.login_email = QLineEdit()
        self.login_email.setPlaceholderText("请输入注册邮箱")
        self.login_email.setStyleSheet(self._input_style())

        self.login_password = QLineEdit()
        self.login_password.setPlaceholderText("请输入密码")
        self.login_password.setEchoMode(QLineEdit.Password)
        self.login_password.setStyleSheet(self._input_style())

        form.addRow(self._label("邮箱"), self.login_email)
        form.addRow(self._label("密码"), self.login_password)

        self.login_btn = QPushButton("登 录")
        self.login_btn.setStyleSheet(self._btn_style())
        self.login_btn.setCursor(Qt.PointingHandCursor)
        self.login_btn.clicked.connect(self._on_login)
        form.addRow(self.login_btn)

        return tab

    def _build_register_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)
        form.setContentsMargins(0, 10, 0, 0)
        form.setSpacing(10)

        self.reg_email = QLineEdit()
        self.reg_email.setPlaceholderText("请输入邮箱")
        self.reg_email.setStyleSheet(self._input_style())

        self.reg_password = QLineEdit()
        self.reg_password.setPlaceholderText("至少 6 位")
        self.reg_password.setEchoMode(QLineEdit.Password)
        self.reg_password.setStyleSheet(self._input_style())

        self.reg_password2 = QLineEdit()
        self.reg_password2.setPlaceholderText("再次输入密码")
        self.reg_password2.setEchoMode(QLineEdit.Password)
        self.reg_password2.setStyleSheet(self._input_style())

        form.addRow(self._label("邮箱"), self.reg_email)
        form.addRow(self._label("密码"), self.reg_password)
        form.addRow(self._label("确认密码"), self.reg_password2)

        self.reg_btn = QPushButton("注册并登录")
        self.reg_btn.setStyleSheet(self._btn_style())
        self.reg_btn.setCursor(Qt.PointingHandCursor)
        self.reg_btn.clicked.connect(self._on_register)
        form.addRow(self.reg_btn)

        return tab

    # ---------- 样式 ----------
    def _apply_styles(self):
        self.setStyleSheet(f"background-color: {self.THEME['bg']};")

    def _label(self, text: str) -> QLabel:
        lb = QLabel(text)
        lb.setStyleSheet(
            f"color: {self.THEME['text_sub']}; font-size: 12px; "
            f"border: none; background: transparent;"
        )
        return lb

    def _input_style(self) -> str:
        return (
            f"background-color: {self.THEME['input_bg']};"
            f"border: 1px solid {self.THEME['input_border']};"
            f"border-radius: 6px; padding: 8px 10px;"
            f"color: {self.THEME['text']}; font-size: 13px;"
            f"selection-background-color: {self.THEME['accent']};"
        )

    def _btn_style(self) -> str:
        return (
            f"QPushButton {{"
            f"  background-color: {self.THEME['accent']};"
            f"  color: #FFFFFF; border: none; border-radius: 6px;"
            f"  padding: 10px; font-size: 14px; font-weight: bold;"
            f"}}"
            f"QPushButton:hover {{ background-color: {self.THEME['accent_hover']}; }}"
            f"QPushButton:pressed {{ background-color: {self.THEME['accent_pressed']}; }}"
            f"QPushButton:disabled {{ background-color: #4B5563; color: #9CA3AF; }}"
        )

    def _tab_style(self) -> str:
        return (
            f"QTabWidget::pane {{ border: none; background: transparent; }}"
            f"QTabBar::tab {{"
            f"  background: transparent; color: {self.THEME['text_muted']};"
            f"  padding: 8px 16px; font-size: 13px; border: none;"
            f"}}"
            f"QTabBar::tab:selected {{ color: {self.THEME['accent']}; }}"
            f"QTabBar::tab:hover {{ color: {self.THEME['text_sub']}; }}"
        )

    # ---------- 行为 ----------
    def _show_error(self, msg: str):
        self.err_label.setText(msg)
        self.err_label.show()

    def _set_loading(self, loading: bool):
        self.login_btn.setEnabled(not loading)
        self.reg_btn.setEnabled(not loading)
        if loading:
            self.err_label.hide()

    def _on_login(self):
        email = self.login_email.text().strip()
        password = self.login_password.text()
        if not email or not password:
            self._show_error("请填写邮箱和密码")
            return
        self._set_loading(True)
        self._worker = _AuthWorker("POST", "/auth/login", {"email": email, "password": password})
        self._worker.result_ready.connect(self._on_login_done)
        self._worker.start()

    def _on_login_done(self, data: dict):
        self._set_loading(False)
        if data.get("success"):
            self._email = (data.get("data") or {}).get("user", {}).get("email", "")
            self.accept()
        else:
            self._show_error(data.get("message", "登录失败"))

    def _on_register(self):
        email = self.reg_email.text().strip()
        password = self.reg_password.text()
        password2 = self.reg_password2.text()
        if not email or not password:
            self._show_error("请填写邮箱和密码")
            return
        if len(password) < 6:
            self._show_error("密码至少 6 位")
            return
        if password != password2:
            self._show_error("两次输入的密码不一致")
            return
        self._set_loading(True)
        self._worker = _AuthWorker("POST", "/auth/register", {"email": email, "password": password})
        self._worker.result_ready.connect(self._on_register_done)
        self._worker.start()

    def _on_register_done(self, data: dict):
        self._set_loading(False)
        if data.get("success"):
            self._email = (data.get("data") or {}).get("user", {}).get("email", "")
            self.accept()
        else:
            self._show_error(data.get("message", "注册失败"))

    @property
    def email(self) -> str:
        return self._email


# ======================== 登录态校验 ========================
def check_logged_in() -> bool:
    """调后端 /api/auth/check 校验登录态。"""
    try:
        resp = requests.get(f"{API_BASE_URL}/auth/check", timeout=10)
        if resp.status_code == 200:
            return bool(resp.json().get("logged_in"))
    except Exception:
        pass
    return False


def require_login(parent=None) -> tuple[bool, str]:
    """启动时调用。返回 (是否已登录, 邮箱)。
    若本地 auth.json 有效则直接通过；否则弹出登录对话框。
    """
    # QDialog.exec() 必须依赖已存在的 QApplication，否则会 segfault 静默退出
    import sys as _sys
    app = QApplication.instance() or QApplication(_sys.argv)

    # 设置全局默认字体
    try:
        from gui.pages.common import font
        app.setFont(font(9))
    except Exception:
        pass

    if check_logged_in():
        # 取一下邮箱用于显示
        try:
            resp = requests.get(f"{API_BASE_URL}/auth/check", timeout=10)
            data = resp.json().get("data") or {}
            return True, data.get("email", "")
        except Exception:
            return True, ""

    dlg = LoginDialog(parent)
    if dlg.exec() == QDialog.Accepted:
        return True, dlg.email
    return False, ""
