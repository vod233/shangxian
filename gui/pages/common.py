"""公共层：主题色访问 + API Worker + BasePage + 公共 widget 工厂。

统一深色科技风（GitHub Dark 色板），保证整体美学与专业感。
- 字体：Microsoft YaHei UI
- 主色：#6366F1（紫蓝）
- 背景：#0D1117 / #161B28 / #21262D
- 文字：#FFFFFF（主） / #D1D5DB（次） / #6B7280（弱）
"""
import os
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
                "dark_one": "#0D1117", "dark_two": "#161B28",
                "dark_three": "#21262D", "dark_four": "#30363D",
                "bg_one": "#161B28", "bg_two": "#1C2333", "bg_three": "#21262D",
                "icon_color": "#D1D5DB", "icon_hover": "#FFFFFF",
                "context_color": "#6366F1", "context_hover": "#818CF8",
                "context_pressed": "#4F46E5",
                "text_title": "#FFFFFF", "text_foreground": "#D1D5DB",
                "text_description": "#6B7280", "text_active": "#FFFFFF",
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
def font(size: int = 13, bold: bool = False) -> QFont:
    """统一字体工厂：Microsoft YaHei UI。"""
    f = QFont("Microsoft YaHei UI", size)
    f.setBold(bold)
    return f


# ======================== 通用 HTTP 请求 Worker ========================
class ApiWorker(QThread):
    """通用异步 HTTP 请求 worker，避免阻塞 UI。

    用法：
        worker = ApiWorker("GET", "/stats")
        worker.finished.connect(self._on_done)
        worker.start()
    """
    finished = Signal(dict)

    def __init__(self, method: str, path: str, json_body: dict = None,
                 params: dict = None, timeout: int = 15):
        super().__init__()
        self.method = method.upper()
        self.path = path
        self.json_body = json_body
        self.params = params
        self.timeout = timeout

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
        self.finished.emit(data)


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
    """卡片 QSS：圆角深色背景。"""
    return (
        f"QFrame#card {{ background-color: {c('bg_two')}; "
        f"border: 1px solid {c('dark_four')}; border-radius: 10px; }}"
    )


def qss_input() -> str:
    """输入框 QSS：圆角、深色背景、focus 变紫边框。"""
    return (
        f"QLineEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{"
        f"  background-color: {c('dark_one')}; color: {c('text_title')};"
        f"  border: 1px solid {c('dark_four')}; border-radius: 6px;"
        f"  padding: 8px 10px; font-size: 13px;"
        f"  selection-background-color: {c('context_color')};"
        f"}}"
        f"QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus,"
        f" QDoubleSpinBox:focus, QComboBox:focus {{"
        f"  border: 1px solid {c('context_color')};"
        f"}}"
        f"QComboBox::drop-down {{ border: none; width: 24px; }}"
        f"QComboBox QAbstractItemView {{ background-color: {c('dark_two')};"
        f"  color: {c('text_title')}; selection-background-color: {c('context_color')};"
        f"  border: 1px solid {c('dark_four')}; }}"
    )


def qss_btn_primary() -> str:
    """主按钮 QSS：紫蓝背景 + 白字。"""
    return (
        f"QPushButton {{ background-color: {c('context_color')}; color: #FFFFFF;"
        f"  border: none; border-radius: 6px; padding: 9px 18px;"
        f"  font-size: 13px; font-weight: bold; }}"
        f"QPushButton:hover {{ background-color: {c('context_hover')}; }}"
        f"QPushButton:pressed {{ background-color: {c('context_pressed')}; }}"
        f"QPushButton:disabled {{ background-color: #4B5563; color: #9CA3AF; }}"
    )


def qss_btn_secondary() -> str:
    """次按钮 QSS：深色背景。"""
    return (
        f"QPushButton {{ background-color: {c('dark_three')}; color: {c('text_title')};"
        f"  border: 1px solid {c('dark_four')}; border-radius: 6px; padding: 8px 16px;"
        f"  font-size: 13px; }}"
        f"QPushButton:hover {{ background-color: {c('dark_four')}; }}"
        f"QPushButton:pressed {{ background-color: {c('context_pressed')}; }}"
        f"QPushButton:disabled {{ background-color: #2D333B; color: #6B7280; }}"
    )


def qss_btn_danger() -> str:
    """危险按钮 QSS：红色背景。"""
    return (
        f"QPushButton {{ background-color: {c('red')}; color: #FFFFFF;"
        f"  border: none; border-radius: 6px; padding: 9px 18px;"
        f"  font-size: 13px; font-weight: bold; }}"
        f"QPushButton:hover {{ background-color: #DC2626; }}"
        f"QPushButton:pressed {{ background-color: #B91C1C; }}"
        f"QPushButton:disabled {{ background-color: #4B5563; color: #9CA3AF; }}"
    )


def qss_checkbox() -> str:
    """复选框 QSS。"""
    return (
        f"QCheckBox {{ color: {c('text_foreground')}; font-size: 13px; spacing: 8px; }}"
        f"QCheckBox::indicator {{ width: 18px; height: 18px;"
        f"  border: 2px solid {c('dark_four')}; border-radius: 4px;"
        f"  background-color: {c('dark_one')}; }}"
        f"QCheckBox::indicator:hover {{ border-color: {c('context_hover')}; }}"
        f"QCheckBox::indicator:checked {{ background-color: {c('context_color')};"
        f"  border-color: {c('context_color')}; }}"
        f"QRadioButton {{ color: {c('text_foreground')}; font-size: 13px; spacing: 8px; }}"
        f"QRadioButton::indicator {{ width: 16px; height: 16px;"
        f"  border: 2px solid {c('dark_four')}; border-radius: 9px;"
        f"  background-color: {c('dark_one')}; }}"
        f"QRadioButton::indicator:checked {{ border-color: {c('context_color')};"
        f"  background-color: {c('context_color')}; }}"
    )


def qss_table() -> str:
    """表格 QSS。"""
    return (
        f"QTableWidget {{ background-color: {c('bg_two')}; color: {c('text_foreground')};"
        f"  border: 1px solid {c('dark_four')}; border-radius: 8px;"
        f"  gridline-color: {c('dark_four')}; outline: none; }}"
        f"QHeaderView::section {{ background-color: {c('dark_two')};"
        f"  color: {c('text_title')}; padding: 8px; border: none;"
        f"  border-bottom: 1px solid {c('dark_four')}; font-size: 12px;"
        f"  font-weight: bold; }}"
        f"QTableWidget::item {{ padding: 6px; border-bottom: 1px solid {c('dark_three')}; }}"
        f"QTableWidget::item:selected {{ background-color: {c('context_color')};"
        f"  color: #FFFFFF; }}"
        f"QScrollBar:vertical {{ background-color: {c('dark_one')}; width: 10px;"
        f"  border: none; }}"
        f"QScrollBar::handle:vertical {{ background-color: {c('dark_four')};"
        f"  border-radius: 5px; min-height: 30px; }}"
        f"QScrollBar::handle:vertical:hover {{ background-color: {c('context_color')}; }}"
        f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}"
    )


def qss_scrollarea() -> str:
    """滚动区 QSS：透明背景 + 细滚动条。"""
    return (
        f"QScrollArea {{ background: transparent; border: none; }}"
        f"QScrollBar:vertical {{ background-color: {c('dark_one')}; width: 10px;"
        f"  border: none; }}"
        f"QScrollBar::handle:vertical {{ background-color: {c('dark_four')};"
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

    内部结构：
        frame（圆角深色背景）
          └─ 主布局（VBoxLayout, margin 20）
               ├─ 标题 label（如有 title）
               └─ 内容 layout（QVBoxLayout，供外部 addWidget）
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
        # 标题下分隔线
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background-color: {c('dark_four')}; border: none;")
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
    """指标卡（大数字 + 描述）。"""
    if color is None:
        color = c("text_title")
    frame = QFrame()
    frame.setObjectName("card")
    frame.setStyleSheet(qss_card())
    frame.setMinimumHeight(90)

    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 14, 16, 14)
    layout.setSpacing(4)

    value_lb = QLabel(value)
    value_lb.setFont(font(22, bold=True))
    value_lb.setStyleSheet(f"color: {color}; background: transparent;")
    value_lb.setAlignment(Qt.AlignCenter)

    label_lb = QLabel(label)
    label_lb.setFont(font(11))
    label_lb.setStyleSheet(f"color: {c('text_description')}; background: transparent;")
    label_lb.setAlignment(Qt.AlignCenter)
    label_lb.setWordWrap(True)

    layout.addWidget(value_lb)
    layout.addWidget(label_lb)
    return frame


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

    统一布局：
        ┌───────────────────────────────────┐
        │  QScrollArea（透明背景 + 细滚动条）  │
        │   ┌─────────────────────────────┐ │
        │   │  QVBoxLayout（margin 24）     │ │
        │   │   ├─ 页面主标题（22pt bold）   │ │
        │   │   ├─ 页面副标题（13pt 灰）     │ │
        │   │   ├─ 分隔线                  │ │
        │   │   └─ 内容区（content_layout） │ │
        │   │       （子类在此 addLayout）  │ │
        │   └─────────────────────────────┘ │
        └───────────────────────────────────┘
    """

    def __init__(self, title: str = "", subtitle: str = "", parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background-color: {c('dark_one')};")

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
        self.main_layout.setContentsMargins(24, 20, 24, 20)
        self.main_layout.setSpacing(14)

        # 页面标题
        if title:
            self.title_label = make_title_label(title, size=22)
            self.main_layout.addWidget(self.title_label)
        if subtitle:
            self.subtitle_label = make_subtitle_label(subtitle, size=13)
            self.main_layout.addWidget(self.subtitle_label)

        # 分隔线
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background-color: {c('dark_four')}; border: none;")
        self.main_layout.addWidget(line)

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
            f"color: {c('text_description')}; background: transparent;"
            f"  padding: 8px; border-radius: 6px;"
        )
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.hide()
        self.content_layout.addWidget(self.status_label)

    def set_status(self, msg: str, level: str = "info"):
        """显示状态提示。level: info/success/warning/danger。"""
        if not msg:
            self.status_label.hide()
            return
        colors = {
            "info": (c("context_color"), "#FFFFFF"),
            "success": (c("green"), "#FFFFFF"),
            "warning": (c("yellow"), "#0D1117"),
            "danger": (c("red"), "#FFFFFF"),
        }
        bg, fg = colors.get(level, colors["info"])
        self.status_label.setText(msg)
        self.status_label.setStyleSheet(
            f"background-color: {bg}; color: {fg};"
            f"  padding: 10px; border-radius: 6px; font-size: 13px;"
        )
        self.status_label.show()

    def clear_status(self):
        """隐藏状态提示。"""
        self.status_label.hide()
