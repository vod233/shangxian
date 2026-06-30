"""公共层：主题色访问 + API Worker + BasePage + 公共 widget 工厂。

千伴AI员工 · 现代扁平暗黑设计系统
- 字体：Microsoft YaHei UI（界面） + JetBrains Mono / Consolas（数值）
- 主色：#6366F1（靛蓝，唯一强调色）
- 底色层级：bg_base #0A0E14 / bg_surface #11161F / bg_raise #161C28 / bg_hover #1E2533
- 分隔：line_soft #232A37（发丝）/ line_strong #2F3744（强调）
- 文字：text_primary #F4F6FB / text_secondary #A8B0BD / text_tertiary #6B7280
"""
import os
import sys
import json
import requests
from PySide6.QtCore import Qt, QThread, Signal, QSize
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import (
    QWidget, QScrollArea, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QPushButton, QSpinBox, QDoubleSpinBox, QSlider,
    QCheckBox, QRadioButton, QButtonGroup, QFrame, QSizePolicy,
    QPlainTextEdit, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QComboBox, QGroupBox
)

# 后端 API 地址（由 launcher 启动时设置环境变量）
API_BASE_URL = os.environ.get("APP_API_URL", "http://127.0.0.1:8000/api")


# ======================== 主题色单例 ========================
class _ThemeProxy:
    """单例主题色代理。首次访问时从 gui/themes/default.json 加载。"""
    _instance = None
    _colors = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @property
    def colors(self) -> dict:
        if self._colors is None:
            self._load()
        return self._colors

    def _load(self):
        # cwd 已由 launcher 切到 _internal/，主题文件在 gui/themes/default.json
        path = os.path.join("gui", "themes", "default.json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                self._colors = json.load(f).get("app_color", {})
        except Exception:
            # 兜底硬编码（与 default.json 一致）
            self._colors = {
                "dark_one": "#0A0E14", "dark_two": "#11161F",
                "dark_three": "#161C28", "dark_four": "#232A37",
                "bg_one": "#11161F", "bg_two": "#161C28", "bg_three": "#1E2533",
                "bg_base": "#0A0E14", "bg_surface": "#11161F",
                "bg_raise": "#161C28", "bg_hover": "#1E2533",
                "line_soft": "#232A37", "line_strong": "#2F3744",
                "accent_glow": "rgba(99,102,241,0.16)",
                "icon_color": "#A8B0BD", "icon_hover": "#F4F6FB",
                "icon_pressed": "#6366F1", "icon_active": "#F4F6FB",
                "context_color": "#6366F1", "context_hover": "#818CF8",
                "context_pressed": "#4F46E5",
                "text_title": "#F4F6FB", "text_foreground": "#A8B0BD",
                "text_description": "#6B7280", "text_active": "#F4F6FB",
                "text_primary": "#F4F6FB", "text_secondary": "#A8B0BD",
                "text_tertiary": "#6B7280", "text_inverse": "#0A0E14",
                "white": "#FFFFFF", "pink": "#EC4899", "green": "#10B981",
                "red": "#EF4444", "yellow": "#F59E0B",
            }


def theme() -> _ThemeProxy:
    """获取主题色单例。"""
    return _ThemeProxy()


def c(key: str) -> str:
    """快捷取色：c("context_color") → "#6366F1"。"""
    return theme().colors.get(key, "#FFFFFF")


# ======================== 跨页面共享状态 ========================
class AppState:
    """跨页面共享状态（单例）。

    用于在不同业务页之间共享数据，例如：
    - DevicesPage 选中设备 → ProcessPage 读取并提交任务
    """
    _instance = None
    _selected_devices: set = set()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @property
    def selected_devices(self) -> list:
        return list(self._selected_devices)

    def set_selected_devices(self, serials: list):
        self._selected_devices = set(serials)

    def add_device(self, serial: str):
        self._selected_devices.add(serial)

    def remove_device(self, serial: str):
        self._selected_devices.discard(serial)

    def clear_devices(self):
        self._selected_devices.clear()


def app_state() -> AppState:
    """获取跨页面共享状态单例。"""
    return AppState()


# ======================== 字体工厂 ========================
_FONT_FAMILY = "Microsoft YaHei UI"
_FONT_BASE_PT = 9  # settings.json 中 text_size 的默认值（pt）


def _load_font_config() -> tuple:
    """从 settings.json 加载字体配置（每次调用都重新读取以支持实时调整）。

    返回 (family, text_size_pt)。
    """
    family = _FONT_FAMILY
    text_size_pt = _FONT_BASE_PT
    try:
        import json
        import os
        settings_path = os.path.normpath(
            os.path.join(os.path.abspath(os.getcwd()), "settings.json")
        )
        if os.path.isfile(settings_path):
            with open(settings_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            font_cfg = cfg.get("font", {})
            family = font_cfg.get("family", _FONT_FAMILY)
            text_size_pt = font_cfg.get("text_size", _FONT_BASE_PT)
    except Exception:
        pass
    return family, text_size_pt


def font(size: int = 13, bold: bool = False) -> QFont:
    """统一字体工厂：Microsoft YaHei UI（Windows 系统自带，合法商用）。

    size: 字体大小（pt，磅值）。实际大小会根据 settings 中的基准大小按比例缩放。
    例如：基准 9pt 时 font(13) = 13pt；基准调整为 12pt 时 font(13) ≈ 17.3pt。
    """
    family, base_pt = _load_font_config()
    scale = base_pt / _FONT_BASE_PT
    actual_size = max(6, int(round(size * scale)))
    f = QFont(family, actual_size)
    f.setBold(bold)
    return f


# 数值等宽字体优先级：JetBrains Mono → Consolas → Cascadia Mono → 系统等宽
_MONO_FAMILIES = ("JetBrains Mono", "Consolas", "Cascadia Mono", "DejaVu Sans Mono")


def font_mono(size: int = 22, bold: bool = True) -> QFont:
    """数值等宽字体工厂：用于 KPI 数值/时间戳/序号，让数字更挺拔。

    自动探测系统可用的等宽字体，找不到则回退到界面字体。
    """
    family, base_pt = _load_font_config()
    scale = base_pt / _FONT_BASE_PT
    actual_size = max(6, int(round(size * scale)))
    from PySide6.QtGui import QFontDatabase
    available = set(QFontDatabase.families())
    chosen = next((fam for fam in _MONO_FAMILIES if fam in available), family)
    f = QFont(chosen, actual_size)
    f.setBold(bold)
    # 等宽字体开启 tabular figures 更稳（部分字体支持）
    f.setStyleStrategy(QFont.PreferAntialias)
    return f


# ======================== 通用 HTTP 请求 Worker ========================
class ApiWorker(QThread):
    """通用异步 HTTP 请求 worker，避免阻塞 UI。

    P2修复：与 MultiApiWorker 对齐，添加 deleteLater 自动清理和 is_running 重入保护。
    P7修复：类级别引用池 _alive_workers，防止 worker 在 run() 未结束时
           被调用方覆盖引用导致 Python GC 过早回收 C++ QThread 对象。
           "QThread: Destroyed while thread is still running" 警告即由此引起。
    P9修复（根因）：原代码用 `finished = Signal(dict)` 覆盖了 QThread 内置的
           finished 信号，破坏 Qt 内部线程管理，导致 run() 返回时
           STATUS_STACK_BUFFER_OVERRUN (0xC0000409) 崩溃。
           改用自定义信号 result_ready 传递结果，保留内置 finished 用于清理。

    用法：
        worker = ApiWorker("GET", "/stats")
        worker.result_ready.connect(self._on_done)
        worker.start()
    """
    result_ready = Signal(dict)
    # 类级别引用池：持有所有未完成 worker 的强引用，防止 GC 过早回收
    _alive_workers = set()

    def __init__(self, method: str, path: str, json_body: dict = None,
                 params: dict = None, timeout: int = 15):
        super().__init__()
        self.method = method.upper()
        self.path = path
        self.json_body = json_body
        self.params = params
        self.timeout = timeout
        # 连接到 QThread 内置 finished 信号（run() 返回后自动发射），用于清理
        self.finished.connect(self._on_finished_cleanup)
        # 注册到引用池，防止调用方覆盖引用后 GC 回收
        self._alive_workers.add(self)

    def _on_finished_cleanup(self, *_):
        """run() 完成后从引用池移除并安全删除自身。"""
        self._alive_workers.discard(self)
        self.deleteLater()

    def is_running(self) -> bool:
        """返回线程是否仍在运行，供调用方做重入保护。"""
        try:
            return self.isRunning()
        except RuntimeError:
            return False

    def run(self):
        url = f"{API_BASE_URL.rstrip('/')}{self.path}"
        try:
            if self.method == "GET":
                resp = requests.get(url, params=self.params, timeout=self.timeout)
            elif self.method == "POST":
                resp = requests.post(url, json=self.json_body, params=self.params,
                                     timeout=self.timeout)
            else:
                resp = requests.request(self.method, url, json=self.json_body,
                                         params=self.params, timeout=self.timeout)
            try:
                data = resp.json()
            except Exception:
                data = {"success": False, "message": f"HTTP {resp.status_code} 响应解析失败"}
            data["_status_code"] = resp.status_code
        except requests.RequestException as exc:
            data = {"success": False, "message": f"网络错误：{exc}", "_status_code": 0}
        self.result_ready.emit(data)


class MultiApiWorker(QThread):
    """批量异步 GET 请求 worker，避免阻塞 UI。

    问题3修复：home_page / monitor_page / dashboard_page 的定时器原先用同步
    api_get 串行请求多个 API，导致 UI 卡顿。改用本类在后台线程并发请求，
    全部完成后一次性回传结果列表。

    Review修复：
    - run() 结束后自动调用 deleteLater()，避免 QThread 对象累积泄漏
    - 提供is_running()方法供调用方做重入保护，避免旧请求结果覆盖新请求

    P7修复：类级别引用池，防止 worker 在 run() 未结束时被 GC 过早回收。
    P9修复（根因）：原代码用 `finished = Signal(list)` 覆盖了 QThread 内置的
           finished 信号，破坏 Qt 内部线程管理，导致 run() 返回时
           STATUS_STACK_BUFFER_OVERRUN (0xC0000409) 崩溃。
           改用自定义信号 result_ready 传递结果，保留内置 finished 用于清理。

    用法：
        worker = MultiApiWorker([("/stats", None), ("/tasks/status", None)])
        worker.result_ready.connect(self._on_done)  # _on_done(results: list[dict])
        worker.start()
    """
    result_ready = Signal(list)
    # 类级别引用池：持有所有未完成 worker 的强引用，防止 GC 过早回收
    _alive_workers = set()

    def __init__(self, requests_list: list, timeout: int = 10):
        """requests_list: [(path, params), ...]，params 可为 None。"""
        super().__init__()
        self.requests_list = requests_list
        self.timeout = timeout
        # 连接到 QThread 内置 finished 信号（run() 返回后自动发射），用于清理
        self.finished.connect(self._on_finished_cleanup)
        self._alive_workers.add(self)

    def _on_finished_cleanup(self, *_):
        """run() 完成后从引用池移除并安全删除自身。"""
        self._alive_workers.discard(self)
        self.deleteLater()

    def is_running(self) -> bool:
        """返回线程是否仍在运行，供调用方做重入保护。
        若 C++ 对象已被 deleteLater 删除，返回 False（视作未运行）。
        """
        try:
            return self.isRunning()
        except RuntimeError:
            return False

    def run(self):
        results = []
        for path, params in self.requests_list:
            url = f"{API_BASE_URL.rstrip('/')}{path}"
            try:
                resp = requests.get(url, params=params, timeout=self.timeout)
                results.append(resp.json())
            except Exception as exc:
                results.append({"success": False, "message": str(exc)})
        self.result_ready.emit(results)


# ======================== 同步 HTTP 辅助（启动时加载配置用） ========================
def api_get(path: str, params: dict = None, timeout: int = 10) -> dict:
    """同步 GET。失败返回 {"success": False, "message": ...}。"""
    url = f"{API_BASE_URL.rstrip('/')}{path}"
    try:
        resp = requests.get(url, params=params, timeout=timeout)
        return resp.json()
    except Exception as exc:
        return {"success": False, "message": str(exc)}


def api_post(path: str, json_body: dict = None, params: dict = None,
             timeout: int = 15) -> dict:
    """同步 POST。失败返回 {"success": False, "message": ...}。"""
    url = f"{API_BASE_URL.rstrip('/')}{path}"
    try:
        resp = requests.post(url, json=json_body, params=params, timeout=timeout)
        return resp.json()
    except Exception as exc:
        return {"success": False, "message": str(exc)}


# ======================== 统一样式字符串 ========================
def qss_card() -> str:
    """卡片 QSS：去描边，仅靠 bg_raise 底色 + 圆角分层。"""
    return (
        f"QFrame#card {{ background-color: {c('bg_raise')}; "
        f"border: none; border-radius: 10px; }}"
    )


def qss_input() -> str:
    """输入框 QSS：圆角、深色背景、focus 变靛蓝边框。"""
    return (
        f"QLineEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{"
        f"  background-color: {c('bg_base')}; color: {c('text_primary')};"
        f"  border: 1px solid {c('line_soft')}; border-radius: 6px;"
        f"  padding: 8px 10px; font-size: 13px;"
        f"  selection-background-color: {c('context_color')};"
        f"}}"
        f"QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus,"
        f" QDoubleSpinBox:focus, QComboBox:focus {{"
        f"  border: 1px solid {c('context_color')};"
        f"}}"
        f"QComboBox::drop-down {{ border: none; width: 24px; }}"
        f"QComboBox QAbstractItemView {{ background-color: {c('bg_surface')};"
        f"  color: {c('text_primary')}; selection-background-color: {c('context_color')};"
        f"  border: 1px solid {c('line_strong')}; }}"
    )


def qss_btn_primary() -> str:
    """主按钮 QSS：靛蓝背景 + 反色文字。"""
    return (
        f"QPushButton {{ background-color: {c('context_color')}; color: {c('text_inverse')};"
        f"  border: none; border-radius: 6px; padding: 9px 18px;"
        f"  font-size: 13px; font-weight: 600; }}"
        f"QPushButton:hover {{ background-color: {c('context_hover')}; }}"
        f"QPushButton:pressed {{ background-color: {c('context_pressed')}; }}"
        f"QPushButton:disabled {{ background-color: #3A4252; color: #6B7280; }}"
    )


def qss_btn_secondary() -> str:
    """次按钮 QSS：ghost 风格——透明底 + 发丝描边，悬停抬升底色。"""
    return (
        f"QPushButton {{ background-color: transparent; color: {c('text_primary')};"
        f"  border: 1px solid {c('line_strong')}; border-radius: 6px; padding: 8px 16px;"
        f"  font-size: 13px; }}"
        f"QPushButton:hover {{ background-color: {c('bg_hover')};"
        f"  border-color: {c('context_color')}; }}"
        f"QPushButton:pressed {{ background-color: {c('context_pressed')};"
        f"  color: {c('text_inverse')}; }}"
        f"QPushButton:disabled {{ color: #4B5563; border-color: {c('line_soft')}; }}"
    )


def qss_btn_danger() -> str:
    """危险按钮 QSS：红色背景。"""
    return (
        f"QPushButton {{ background-color: {c('red')}; color: #FFFFFF;"
        f"  border: none; border-radius: 6px; padding: 9px 18px;"
        f"  font-size: 13px; font-weight: 600; }}"
        f"QPushButton:hover {{ background-color: #DC2626; }}"
        f"QPushButton:pressed {{ background-color: #B91C1C; }}"
        f"QPushButton:disabled {{ background-color: #3A4252; color: #6B7280; }}"
    )


def qss_checkbox() -> str:
    """复选框 QSS。"""
    return (
        f"QCheckBox {{ color: {c('text_secondary')}; font-size: 13px; spacing: 8px; }}"
        f"QCheckBox::indicator {{ width: 18px; height: 18px;"
        f"  border: 2px solid {c('line_strong')}; border-radius: 4px;"
        f"  background-color: {c('bg_base')}; }}"
        f"QCheckBox::indicator:hover {{ border-color: {c('context_hover')}; }}"
        f"QCheckBox::indicator:checked {{ background-color: {c('context_color')};"
        f"  border-color: {c('context_color')}; }}"
        f"QRadioButton {{ color: {c('text_secondary')}; font-size: 13px; spacing: 8px; }}"
        f"QRadioButton::indicator {{ width: 16px; height: 16px;"
        f"  border: 2px solid {c('line_strong')}; border-radius: 9px;"
        f"  background-color: {c('bg_base')}; }}"
        f"QRadioButton::indicator:checked {{ border-color: {c('context_color')};"
        f"  background-color: {c('context_color')}; }}"
    )


def qss_table() -> str:
    """表格 QSS：去双重边框，透明背景承接卡片底色，仅水平发丝线。

    内嵌于卡片时卡片提供圆角与底色，表格自身无描边无圆角。
    """
    return (
        f"QTableWidget {{ background-color: transparent; color: {c('text_secondary')};"
        f"  border: none; border-radius: 0px;"
        f"  gridline-color: transparent; outline: none; }}"
        f"QHeaderView::section {{ background-color: {c('bg_raise')};"
        f"  color: {c('text_primary')}; padding: 10px 12px; border: none;"
        f"  border-bottom: 1px solid {c('line_strong')}; font-size: 12px;"
        f"  font-weight: 600; }}"
        f"QTableWidget::item {{ padding: 8px 12px; border-bottom: 1px solid {c('line_soft')}; }}"
        f"QTableWidget::item:hover {{ background-color: {c('bg_hover')}; }}"
        f"QTableWidget::item:selected {{ background-color: {c('accent_glow')};"
        f"  color: {c('text_primary')}; }}"
        f"QScrollBar:vertical {{ background-color: transparent; width: 10px;"
        f"  border: none; }}"
        f"QScrollBar::handle:vertical {{ background-color: {c('line_strong')};"
        f"  border-radius: 5px; min-height: 30px; }}"
        f"QScrollBar::handle:vertical:hover {{ background-color: {c('context_color')}; }}"
        f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}"
        f"QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}"
    )


def qss_scrollarea() -> str:
    """滚动区 QSS：透明背景 + 细滚动条。"""
    return (
        f"QScrollArea {{ background: transparent; border: none; }}"
        f"QScrollBar:vertical {{ background-color: transparent; width: 10px;"
        f"  border: none; }}"
        f"QScrollBar::handle:vertical {{ background-color: {c('line_strong')};"
        f"  border-radius: 5px; min-height: 30px; }}"
        f"QScrollBar::handle:vertical:hover {{ background-color: {c('context_color')}; }}"
        f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}"
        f"QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}"
    )


# ======================== 公共 widget 工厂函数 ========================
def make_title_label(text: str, size: int = 20) -> QLabel:
    """页面主标题。"""
    lb = QLabel(text)
    lb.setFont(font(size, bold=True))
    lb.setStyleSheet(f"color: {c('text_title')}; background: transparent;")
    return lb


def make_subtitle_label(text: str, size: int = 13) -> QLabel:
    """页面副标题/描述。"""
    lb = QLabel(text)
    lb.setFont(font(size))
    lb.setWordWrap(True)
    lb.setStyleSheet(f"color: {c('text_description')}; background: transparent;")
    return lb


def make_section_label(text: str, size: int = 14) -> QLabel:
    """区块小标题。"""
    lb = QLabel(text)
    lb.setFont(font(size, bold=True))
    lb.setStyleSheet(f"color: {c('text_title')}; background: transparent;")
    return lb


def make_field_label(text: str) -> QLabel:
    """表单字段标签。"""
    lb = QLabel(text)
    lb.setFont(font(12))
    lb.setStyleSheet(f"color: {c('text_foreground')}; background: transparent;")
    return lb


def make_card_frame(title: str = "") -> tuple:
    """创建卡片容器。返回 (frame, inner_layout)。

    去描边设计：仅 bg_raise 底色 + 10px 圆角，标题下用发丝线分隔。
    """
    frame = QFrame()
    frame.setObjectName("card")
    frame.setStyleSheet(qss_card())
    frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

    outer = QVBoxLayout(frame)
    outer.setContentsMargins(20, 18, 20, 18)
    outer.setSpacing(12)

    if title:
        title_lb = make_section_label(title, size=14)
        outer.addWidget(title_lb)
        # 标题下发丝线（非粗描边）
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background-color: {c('line_soft')}; border: none;")
        outer.addWidget(line)

    content_layout = QVBoxLayout()
    content_layout.setSpacing(10)
    outer.addLayout(content_layout)

    return frame, content_layout


def make_primary_btn(text: str) -> QPushButton:
    """主按钮（紫蓝）。"""
    btn = QPushButton(text)
    btn.setFont(font(13, bold=True))
    btn.setStyleSheet(qss_btn_primary())
    btn.setCursor(Qt.PointingHandCursor)
    btn.setMinimumHeight(38)
    return btn


def make_secondary_btn(text: str) -> QPushButton:
    """次按钮（深色）。"""
    btn = QPushButton(text)
    btn.setFont(font(13))
    btn.setStyleSheet(qss_btn_secondary())
    btn.setCursor(Qt.PointingHandCursor)
    btn.setMinimumHeight(36)
    return btn


def make_danger_btn(text: str) -> QPushButton:
    """危险按钮（红色）。"""
    btn = QPushButton(text)
    btn.setFont(font(13, bold=True))
    btn.setStyleSheet(qss_btn_danger())
    btn.setCursor(Qt.PointingHandCursor)
    btn.setMinimumHeight(38)
    return btn


def make_line_edit(placeholder: str = "", password: bool = False) -> QLineEdit:
    """输入框。"""
    edit = QLineEdit()
    edit.setFont(font(13))
    edit.setStyleSheet(qss_input())
    edit.setPlaceholderText(placeholder)
    if password:
        edit.setEchoMode(QLineEdit.Password)
    edit.setMinimumHeight(36)
    return edit


def make_text_edit(placeholder: str = "", read_only: bool = False) -> QPlainTextEdit:
    """多行文本框。"""
    edit = QPlainTextEdit()
    edit.setFont(font(13))
    edit.setStyleSheet(qss_input())
    edit.setPlaceholderText(placeholder)
    edit.setReadOnly(read_only)
    edit.setMinimumHeight(80)
    return edit


def make_spinbox(min_val: int = 0, max_val: int = 9999, default: int = 0,
                  suffix: str = "") -> QSpinBox:
    """整数输入框。"""
    sp = QSpinBox()
    sp.setFont(font(13))
    sp.setStyleSheet(qss_input())
    sp.setRange(min_val, max_val)
    sp.setValue(default)
    if suffix:
        sp.setSuffix(f" {suffix}")
    sp.setMinimumHeight(36)
    return sp


def make_doublespinbox(min_val: float = 0.0, max_val: float = 1000.0,
                       default: float = 0.0, step: float = 0.1,
                       suffix: str = "") -> QDoubleSpinBox:
    """浮点输入框。"""
    sp = QDoubleSpinBox()
    sp.setFont(font(13))
    sp.setStyleSheet(qss_input())
    sp.setRange(min_val, max_val)
    sp.setSingleStep(step)
    sp.setValue(default)
    if suffix:
        sp.setSuffix(f" {suffix}")
    sp.setMinimumHeight(36)
    return sp


def make_slider(min_val: int = 0, max_val: int = 100, default: int = 0) -> QSlider:
    """滑块。"""
    sl = QSlider(Qt.Horizontal)
    sl.setStyleSheet(
        f"QSlider::groove:horizontal {{ background-color: {c('dark_three')};"
        f"  height: 6px; border-radius: 3px; }}"
        f"QSlider::handle:horizontal {{ background-color: {c('context_color')};"
        f"  width: 18px; height: 18px; margin: -7px 0; border-radius: 9px; }}"
        f"QSlider::handle:horizontal:hover {{ background-color: {c('context_hover')}; }}"
        f"QSlider::sub-page:horizontal {{ background-color: {c('context_color')};"
        f"  border-radius: 3px; }}"
    )
    sl.setRange(min_val, max_val)
    sl.setValue(default)
    return sl


def make_checkbox(text: str, checked: bool = False) -> QCheckBox:
    """复选框。"""
    cb = QCheckBox(text)
    cb.setFont(font(13))
    cb.setStyleSheet(qss_checkbox())
    cb.setChecked(checked)
    return cb


def make_radio_group(options: list, default: str = "") -> tuple:
    """单选按钮组。返回 (group_box, button_group, radio_widgets)。

    options: [{"value": "a_zhen", "label": "阿珍"}, ...]
    """
    group_box = QGroupBox()
    group_box.setStyleSheet(
        f"QGroupBox {{ border: 1px solid {c('dark_four')}; border-radius: 8px;"
        f"  margin-top: 10px; padding: 10px; background-color: transparent; }}"
        f"QGroupBox::title {{ color: {c('text_foreground')}; subcontrol-origin: margin;"
        f"  left: 10px; padding: 0 5px; font-size: 13px; }}"
    )
    layout = QVBoxLayout(group_box)
    layout.setSpacing(8)
    layout.setContentsMargins(10, 16, 10, 10)

    btn_group = QButtonGroup(group_box)
    radio_widgets = []
    for opt in options:
        rb = QRadioButton(opt["label"])
        rb.setFont(font(13))
        rb.setStyleSheet(qss_checkbox())
        rb.setProperty("value", opt["value"])
        if opt["value"] == default:
            rb.setChecked(True)
        btn_group.addButton(rb)
        layout.addWidget(rb)
        radio_widgets.append(rb)

    return group_box, btn_group, radio_widgets


def make_metric_card(value: str, label: str, color: str = None) -> QFrame:
    """指标卡（大数字 + 描述）——左对齐、等宽数字字体。

    保持向后兼容：返回的 card 内第一个 QLabel 仍是数值标签（供 findChildren 取用）。
    """
    if color is None:
        color = c("text_primary")
    frame = QFrame()
    frame.setObjectName("card")
    frame.setStyleSheet(qss_card())
    frame.setMinimumHeight(96)

    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 14, 16, 14)
    layout.setSpacing(4)

    value_lb = QLabel(value)
    value_lb.setFont(font_mono(28, bold=True))
    value_lb.setStyleSheet(f"color: {color}; background: transparent;")
    value_lb.setAlignment(Qt.AlignLeft)

    label_lb = QLabel(label)
    label_lb.setFont(font(11))
    label_lb.setStyleSheet(f"color: {c('text_tertiary')}; background: transparent;")
    label_lb.setAlignment(Qt.AlignLeft)
    label_lb.setWordWrap(True)

    layout.addWidget(value_lb)
    layout.addWidget(label_lb)
    return frame


def make_kpi_card(label: str, value: str = "0", color: str = None,
                  trend: str = "", trend_dir: str = "") -> tuple:
    """KPI 四件套卡片：标签 + 数值 + 趋势 + 占位进度。

    返回 (frame, value_label, trend_label)。
    - trend_dir: "up" / "down" / ""（控制趋势箭头与颜色）
    - 数值用等宽字体左对齐；无趋势数据时 trend_label 隐藏。

    用法：
        card, val_lb, trend_lb = make_kpi_card("今日处理量", "1284", trend="12%", trend_dir="up")
        val_lb.setText("2000")            # 更新数值
        trend_lb.setText("▲ 12%")         # 更新趋势
    """
    if color is None:
        color = c("text_primary")
    frame = QFrame()
    frame.setObjectName("card")
    frame.setStyleSheet(qss_card())
    frame.setMinimumHeight(108)

    layout = QVBoxLayout(frame)
    layout.setContentsMargins(18, 16, 18, 16)
    layout.setSpacing(6)

    # 标签（tertiary，小号）
    label_lb = QLabel(label)
    label_lb.setFont(font(11))
    label_lb.setStyleSheet(f"color: {c('text_tertiary')}; background: transparent;")
    label_lb.setAlignment(Qt.AlignLeft)

    # 数值（等宽，大号）
    value_lb = QLabel(value)
    value_lb.setFont(font_mono(28, bold=True))
    value_lb.setStyleSheet(f"color: {color}; background: transparent;")
    value_lb.setAlignment(Qt.AlignLeft)

    # 趋势行
    trend_color = c("text_tertiary")
    if trend_dir == "up":
        trend_color = c("green")
        if trend and not trend.startswith(("▲", "▼")):
            trend = f"▲ {trend}"
    elif trend_dir == "down":
        trend_color = c("red")
        if trend and not trend.startswith(("▲", "▼")):
            trend = f"▼ {trend}"
    trend_lb = QLabel(trend)
    trend_lb.setFont(font(11, bold=True))
    trend_lb.setStyleSheet(f"color: {trend_color}; background: transparent;")
    trend_lb.setAlignment(Qt.AlignLeft)
    if not trend:
        trend_lb.hide()

    layout.addWidget(label_lb)
    layout.addWidget(value_lb)
    layout.addWidget(trend_lb)
    return frame, value_lb, trend_lb


def make_status_dot(status: str = "info", text: str = "") -> QLabel:
    """状态圆点 + 文字。status: info/success/warning/danger/idle。

    用于表格状态列，取代 ✓ 字符，更高级。
    """
    colors = {
        "info": c("context_color"),
        "success": c("green"),
        "warning": c("yellow"),
        "danger": c("red"),
        "idle": c("text_tertiary"),
    }
    dot_color = colors.get(status, colors["info"])
    lb = QLabel(f"● {text}" if text else "●")
    lb.setFont(font(11, bold=True))
    lb.setStyleSheet(f"color: {dot_color}; background: transparent;")
    lb.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    return lb


def make_table(columns: list, min_height: int = 200) -> QTableWidget:
    """创建统一样式表格。

    columns: ["列1", "列2", ...]
    """
    table = QTableWidget()
    table.setStyleSheet(qss_table())
    table.setColumnCount(len(columns))
    table.setHorizontalHeaderLabels(columns)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
    table.setSelectionMode(QAbstractItemView.ExtendedSelection)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setMinimumHeight(min_height)
    table.verticalHeader().setVisible(False)
    return table


def make_status_badge(text: str, status: str = "info") -> QLabel:
    """状态徽章。status: info/success/warning/danger。"""
    colors = {
        "info": (c("context_color"), "#FFFFFF"),
        "success": (c("green"), "#FFFFFF"),
        "warning": (c("yellow"), "#0D1117"),
        "danger": (c("red"), "#FFFFFF"),
    }
    bg, fg = colors.get(status, colors["info"])
    lb = QLabel(text)
    lb.setFont(font(11, bold=True))
    lb.setStyleSheet(
        f"background-color: {bg}; color: {fg};"
        f"  border-radius: 10px; padding: 3px 10px;"
    )
    lb.setAlignment(Qt.AlignCenter)
    lb.setFixedHeight(22)
    return lb


# ======================== BasePage 基类 ========================
class BasePage(QWidget):
    """所有业务页的基类。

    页头栏布局（去分隔线，用留白代替）：
        ┌─────────────────────────────────────────────┐
        │  页面标题 20pt              〔操作槽 横向〕 │
        │  副标题 13pt tertiary（含鲜活信息）         │
        │                                             │
        │  （16px 留白）                              │
        │  ── 内容区 content_layout ──                │
        └─────────────────────────────────────────────┘
    """

    def __init__(self, title: str = "", subtitle: str = "", parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background-color: {c('bg_surface')};")

        # 外层布局
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # 滚动区
        scroll = QScrollArea()
        scroll.setStyleSheet(qss_scrollarea())
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        # 内容容器
        container = QWidget()
        container.setStyleSheet("background: transparent;")
        self.main_layout = QVBoxLayout(container)
        self.main_layout.setContentsMargins(28, 22, 28, 22)
        self.main_layout.setSpacing(16)

        # ===== 页头栏：标题左 + 操作槽右 =====
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(12)

        # 左侧标题列
        title_col = QVBoxLayout()
        title_col.setContentsMargins(0, 0, 0, 0)
        title_col.setSpacing(4)
        if title:
            self.title_label = make_title_label(title, size=20)
            title_col.addWidget(self.title_label)
        if subtitle:
            self.subtitle_label = make_subtitle_label(subtitle, size=13)
            title_col.addWidget(self.subtitle_label)
        header_row.addLayout(title_col)
        header_row.addStretch(1)

        # 右侧操作槽（子类可 self.header_actions.addWidget(...) 注入按钮）
        self.header_actions = QHBoxLayout()
        self.header_actions.setContentsMargins(0, 0, 0, 0)
        self.header_actions.setSpacing(8)
        header_row.addLayout(self.header_actions)

        self.main_layout.addLayout(header_row)

        # 内容区（子类通过 self.content_layout.addWidget 添加业务内容）
        self.content_layout = QVBoxLayout()
        self.content_layout.setSpacing(16)
        self.main_layout.addLayout(self.content_layout)

        # 弹性底部
        self.main_layout.addStretch(1)

        scroll.setWidget(container)
        outer.addWidget(scroll)

        # 状态提示标签（子类可调 setStatus 显示）
        self.status_label = QLabel("")
        self.status_label.setFont(font(12))
        self.status_label.setStyleSheet(
            f"color: {c('text_primary')}; background-color: {c('bg_hover')};"
            f"  padding: 10px 14px; border-radius: 6px;"
            f"  border-left: 3px solid {c('context_color')};"
        )
        self.status_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.status_label.hide()
        self.content_layout.addWidget(self.status_label)

    def set_status(self, msg: str, level: str = "info"):
        """显示状态提示。level: info/success/warning/danger。"""
        if not msg:
            self.status_label.hide()
            return
        accent = {
            "info": c("context_color"),
            "success": c("green"),
            "warning": c("yellow"),
            "danger": c("red"),
        }.get(level, c("context_color"))
        self.status_label.setText(msg)
        self.status_label.setStyleSheet(
            f"color: {c('text_primary')}; background-color: {c('bg_hover')};"
            f"  padding: 10px 14px; border-radius: 6px;"
            f"  border-left: 3px solid {accent}; font-size: 13px;"
        )
        self.status_label.show()

    def clear_status(self):
        """隐藏状态提示。"""
        self.status_label.hide()
