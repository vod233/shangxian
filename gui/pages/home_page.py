"""首页：AI运营员工群控台，展示今日自动化运营数据总览。

每 3 秒自动刷新一次（同步 HTTP，避免阻塞 UI 太久）。
"""
import random

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QTableWidgetItem,
)

from .common import (
    BasePage, api_get,
    make_card_frame, make_metric_card, make_table,
    make_section_label, c, font,
)


class HomePage(BasePage):
    """首页：展示今日运营指标、综合指数、设备实时动态。"""

    def __init__(self, parent=None):
        super().__init__(
            title="AI运营员工群控台",
            subtitle="今日自动化运营数据总览（每 3 秒自动刷新）",
            parent=parent,
        )
        # 8 个指标卡的 value_label 引用，刷新时只更新 label.setText
        self.metric_values = []
        self._build_ui()
        self._load()
        # 定时刷新（每 3 秒）
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._refresh)
        self.timer.start(3000)

    def _build_ui(self):
        # ====== 卡片1：今日运营指标（2x4 网格） ======
        metric_card, metric_layout = make_card_frame("今日运营指标")
        # 8 个指标配置：(值, 描述, 颜色 key)
        metric_defs = [
            ("0", "今日自动化处理量", "context_color"),
            ("0", "AI智能语义响应", "green"),
            ("0", "对标账号精准锁定", "yellow"),
            ("0", "高意向私域触达", "pink"),
            ("0%", "高潜客群转化率", "context_color"),
            ("0%", "智能对话自主率", "context_color"),
            ("0%", "客群线索唤醒率", "context_color"),
            ("0%", "矩阵全时风控安全度", "green"),
        ]
        # 分两行，每行 4 个
        for row_start in (0, 4):
            row = QHBoxLayout()
            row.setSpacing(12)
            for col in range(4):
                value_text, label_text, color_key = metric_defs[row_start + col]
                card = make_metric_card(value_text, label_text, color=c(color_key))
                # value_label 是 card 内第一个 QLabel（大字号值标签）
                value_lb = card.findChildren(QLabel)[0]
                self.metric_values.append(value_lb)
                row.addWidget(card)
            metric_layout.addLayout(row)
        self.content_layout.addWidget(metric_card)

        # ====== 卡片2：AI 矩阵品牌综合指数 ======
        index_card, index_layout = make_card_frame("AI 矩阵品牌综合指数")
        self.index_label = QLabel("--")
        self.index_label.setFont(font(48, bold=True))
        self.index_label.setAlignment(Qt.AlignCenter)
        self.index_label.setStyleSheet(
            f"color: {c('context_color')}; background: transparent;"
            f"  padding: 20px;"
        )
        index_layout.addWidget(self.index_label)
        self.content_layout.addWidget(index_card)

        # ====== 卡片3：设备实时动态 ======
        dev_card, dev_layout = make_card_frame("设备实时动态")
        self.device_table = make_table(
            ["序号", "序列号", "状态", "任务状态"], min_height=220
        )
        dev_layout.addWidget(self.device_table)
        self.content_layout.addWidget(dev_card)

    def _load(self):
        """同步加载：stats / devices / tasks/status。"""
        # 指标 + 综合指数
        stats_resp = api_get("/stats")
        stats = {}
        if stats_resp.get("success"):
            stats = stats_resp.get("data", {}) or {}
            if isinstance(stats, dict) and "data" in stats:
                stats = stats.get("data", {}) or {}
        self._apply_stats(stats)

        # 任务状态：后端返回 dict {serial: {status: "running", ...}}
        status_dict = {}
        task_resp = api_get("/tasks/status")
        if task_resp.get("success"):
            tdata = task_resp.get("status", {}) or {}
            if isinstance(tdata, dict):
                status_dict = tdata

        # 设备列表：后端返回 {"success": True, "devices": [...]}
        dev_resp = api_get("/devices")
        devices = []
        if dev_resp.get("success"):
            rows = dev_resp.get("devices", []) or []
            devices = rows if isinstance(rows, list) else []
        self._refresh_device_table(devices, status_dict)

    def _apply_stats(self, stats: dict):
        """把 stats 数据填到 8 个指标卡和综合指数。"""
        videos = stats.get("videos", 0) or 0
        comments = stats.get("comments", 0) or 0
        follows = stats.get("follows", 0) or 0
        likes = stats.get("likes", 0) or 0
        # E/F/G 后端不返回，前端本地计算（与 Streamlit 实现保持一致）
        # E = 高潜客群转化率 = 0.65 + (likes % 8) / 100（范围 0.65~0.72）
        # F = 智能对话自主率 = 0.60 + (comments % 8) / 100（范围 0.60~0.67）
        # G = 客群线索唤醒率 = 0.50 + (follows % 8) / 100（范围 0.50~0.58）
        e = 0.65 + (likes % 8) / 100
        f = 0.60 + (comments % 8) / 100
        g = 0.50 + (follows % 8) / 100

        # 8 个指标值（顺序与 _build_ui 中 metric_defs 一致）
        values = [
            str(videos),
            str(comments),
            str(follows),
            str(likes),
            self._fmt_pct(e),
            self._fmt_pct(f),
            self._fmt_pct(g),
            self._fmt_pct(0.998),
        ]
        for lb, val in zip(self.metric_values, values):
            lb.setText(val)

        # 综合指数 = base_floor + 随机偏移（0.65~0.72）
        base_floor = (
            videos * 0.5 + comments * 0.3 + follows * 0.15 + likes * 0.05
        )
        offset = random.uniform(0.65, 0.72)
        self.index_label.setText(f"{base_floor + offset:.2f}")

    @staticmethod
    def _fmt_pct(v) -> str:
        """格式化百分比：0.85 -> "85%"，整数 5 -> "500%"。"""
        try:
            fv = float(v)
        except (TypeError, ValueError):
            fv = 0.0
        # 0~1 视为比率；>=1 视为已是百分数值
        if 0 <= fv <= 1:
            return f"{fv * 100:.1f}%"
        return f"{fv:.1f}%"

    def _refresh_device_table(self, devices: list, status_dict: dict):
        """刷新设备表：遍历设备列表，每台设备一行；
        任务状态从 status_dict[serial].status 获取。

        注意：后端 /api/devices 返回 list[str]（序列号字符串列表），
        不是 list[dict]，所以 dev 是字符串。
        """
        self.device_table.setRowCount(len(devices))
        for i, dev in enumerate(devices):
            # dev 是字符串（设备序列号）
            serial = str(dev) if not isinstance(dev, dict) else str(
                dev.get("serial") or dev.get("serial_no") or dev.get("id") or ""
            )
            status = "在线"
            if isinstance(dev, dict):
                status = str(dev.get("status") or dev.get("state") or "在线")
            # 任务状态：从 status_dict 中按 serial 取
            task_status = ""
            if serial and isinstance(status_dict, dict):
                entry = status_dict.get(serial, {})
                if isinstance(entry, dict):
                    task_status = str(
                        entry.get("status") or entry.get("state") or ""
                    )
                else:
                    task_status = str(entry)
            self.device_table.setItem(i, 0, QTableWidgetItem(str(i + 1)))
            self.device_table.setItem(i, 1, QTableWidgetItem(serial))
            self.device_table.setItem(i, 2, QTableWidgetItem(status))
            self.device_table.setItem(i, 3, QTableWidgetItem(task_status or "—"))

    def _refresh(self):
        """定时刷新入口。"""
        self._load()
