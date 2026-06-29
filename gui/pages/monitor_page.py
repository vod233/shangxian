"""任务监控页：实时查看AI员工执行状态与终端日志输出。

每 2 秒自动刷新一次（同步 HTTP）。
"""
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPlainTextEdit, QTableWidgetItem,
)

from .common import (
    BasePage, api_get,
    make_card_frame, make_metric_card, make_table,
    c, font,
)


class MonitorPage(BasePage):
    """任务监控页：任务状态卡片 + 终端日志（黑底绿字）。"""

    # 任务状态文案映射
    STATUS_TEXT = {
        "queued": "排队中",
        "starting": "启动中",
        "running": "运行中",
        "paused": "已暂停",
        "completed": "已完成",
        "stopped": "已停止",
        "error": "错误",
    }
    # 任务状态 -> 指标卡颜色（对应 common.py 中色 key）
    STATUS_COLOR = {
        "queued": "context_color",
        "starting": "context_color",
        "running": "green",
        "paused": "yellow",
        "completed": "green",
        "stopped": "text_description",
        "error": "red",
    }

    def __init__(self, parent=None):
        super().__init__(
            title="AI员工监控系统",
            subtitle="实时查看AI员工执行状态与终端输出。",
            parent=parent,
        )
        self._worker = None  # 防 GC（保留字段以与统一模式一致）
        self._build_ui()
        self._load()
        # 定时刷新（每 2 秒）
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._refresh)
        self.timer.start(2000)

    def _build_ui(self):
        # ====== 卡片1：任务状态 ======
        status_card, status_layout = make_card_frame("任务状态")
        # 用 make_metric_card 显示状态，颜色后续按状态刷新
        self.status_metric = make_metric_card(
            "—", "当前任务状态", color=c("text_title")
        )
        status_layout.addWidget(self.status_metric)
        # 保留 value_label 引用以便刷新（value_label 是卡内第一个 QLabel）
        self.status_value_lb = self.status_metric.findChildren(QLabel)[0]
        # 多设备状态表：遍历 status_dict，每台设备一行
        self.device_status_table = make_table(
            ["序列号", "任务状态"], min_height=160
        )
        status_layout.addWidget(self.device_status_table)
        self.content_layout.addWidget(status_card)

        # ====== 卡片2：AI 操作终端日志 ======
        log_card, log_layout = make_card_frame("AI 操作终端日志")
        self.log_edit = QPlainTextEdit()
        self.log_edit.setReadOnly(True)
        # 等宽字体 + 黑底绿字（终端风格）
        self.log_edit.setStyleSheet(
            f"QPlainTextEdit {{"
            f"  background-color: #000000; color: {c('green')};"
            f"  border: 1px solid {c('dark_four')}; border-radius: 6px;"
            f"  padding: 10px; font-size: 13px;"
            f"  font-family: 'Fira Code', 'Consolas', 'Courier New', monospace;"
            f"}}"
        )
        self.log_edit.setFont(font(13))
        self.log_edit.setMinimumHeight(360)
        log_layout.addWidget(self.log_edit)
        self.content_layout.addWidget(log_card)

    def _load(self):
        """同步加载：tasks/status + logs。"""
        # 任务状态：后端返回 dict {serial: {status: "running", ...}}
        status_dict = {}
        task_resp = api_get("/tasks/status")
        if task_resp.get("success"):
            tdata = task_resp.get("status", {}) or {}
            if isinstance(tdata, dict):
                status_dict = tdata
        # 总体状态：取第一台设备的状态作为代表（用于顶部指标卡）
        overall_status = ""
        if status_dict:
            first_serial = next(iter(status_dict), None)
            if first_serial is not None:
                entry = status_dict.get(first_serial, {})
                if isinstance(entry, dict):
                    overall_status = str(
                        entry.get("status") or entry.get("state") or ""
                    )
                else:
                    overall_status = str(entry)
        self._apply_task_status(overall_status)
        # 多设备状态表：遍历 status_dict，每台设备一行
        self._apply_device_status(status_dict)

        # 日志：后端返回 {"success": True, "logs": [str, ...]}
        log_resp = api_get("/logs")
        if log_resp.get("success"):
            ldata = log_resp.get("logs", [])
            self._apply_logs(ldata)
        else:
            self.set_status(
                f"日志加载失败：{log_resp.get('message', '')}", "danger"
            )

    def _apply_task_status(self, raw_status: str):
        """根据状态更新指标卡文本与颜色。

        make_metric_card 颜色 baked 进 QSS，无法直接换色，
        故重建卡片并在原位置插入。
        """
        status_key = (raw_status or "").strip().lower()
        text = self.STATUS_TEXT.get(status_key, raw_status or "未知")
        color_key = self.STATUS_COLOR.get(status_key, "text_title")
        new_card = make_metric_card(text, "当前任务状态", color=c(color_key))
        # 替换原卡到原位置
        parent_layout = self.status_metric.parent().layout()
        idx = parent_layout.indexOf(self.status_metric)
        parent_layout.removeWidget(self.status_metric)
        self.status_metric.setParent(None)
        parent_layout.insertWidget(idx, new_card)
        self.status_metric = new_card
        self.status_value_lb = new_card.findChildren(QLabel)[0]

    def _apply_device_status(self, status_dict: dict):
        """遍历 status_dict，为每台设备显示一行状态。

        status_dict 形如 {serial: {status: "running", ...}}。
        """
        if not isinstance(status_dict, dict):
            self.device_status_table.setRowCount(0)
            return
        serials = list(status_dict.keys())
        self.device_status_table.setRowCount(len(serials))
        for i, serial in enumerate(serials):
            entry = status_dict.get(serial, {})
            if isinstance(entry, dict):
                raw = str(entry.get("status") or entry.get("state") or "")
            else:
                raw = str(entry)
            status_key = (raw or "").strip().lower()
            text = self.STATUS_TEXT.get(status_key, raw or "未知")
            self.device_status_table.setItem(
                i, 0, QTableWidgetItem(str(serial))
            )
            self.device_status_table.setItem(
                i, 1, QTableWidgetItem(text)
            )

    def _apply_logs(self, data):
        """把日志数据（list[str] 或 str）拼接成纯文本显示。"""
        if isinstance(data, list):
            text = "\n".join(str(line) for line in data)
        elif isinstance(data, str):
            text = data
        elif isinstance(data, dict):
            # 兼容 {"logs": [...]} 形态
            lines = data.get("logs") or data.get("lines") or []
            text = "\n".join(str(l) for l in lines) if isinstance(lines, list) else str(data)
        else:
            text = str(data)
        self.log_edit.setPlainText(text)

    def _refresh(self):
        """定时刷新入口。"""
        self._load()
