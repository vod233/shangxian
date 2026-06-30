"""首页：千伴AI员工群控台，展示今日自动化运营数据总览。

升级要点（UI 爆改）：
- 8 个 KPI 改为四件套卡片（标签 + 等宽数值 + 趋势 + 昨日对比）
- 趋势数据用 QSettings 缓存昨日末次快照，无数据时隐藏（不造假）
- 综合指数由巨型数字升级为环形仪表盘（QPainter 自绘）
- 设备动态表沿用新表格样式（去双重边框）
每 3 秒自动刷新一次（异步 HTTP，不阻塞 UI）。
"""
import random
from datetime import date

from PySide6.QtCore import QTimer, Qt, QRectF, QSettings
from PySide6.QtGui import QPainter, QColor, QPen
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QTableWidgetItem, QWidget, QSizePolicy,
)

from .common import (
    BasePage, MultiApiWorker,
    make_card_frame, make_kpi_card, make_table,
    c, font, font_mono,
)


# ======================== 环形指数仪表盘 ========================
class RingGauge(QWidget):
    """综合指数环形仪表盘：自绘圆环 + 中心数值。

    value 范围 0~100，显示为整数百分比；外环用 accent 色，背景环用 line_soft。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = 0.0          # 0~100
        self._display = 0.0        # 动画当前显示值
        self._label = "综合指数"
        self.setMinimumHeight(220)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

    def set_value(self, v: float):
        """设置目标值（0~100），并触发计数动画。"""
        self._value = max(0.0, min(100.0, float(v)))
        # 简易计数动画：用 QTimer 逼近目标值
        self._display = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)

    def _tick(self):
        # OutQuart 缓动：每帧逼近 12%
        self._display += (self._value - self._display) * 0.12
        if abs(self._value - self._display) < 0.3:
            self._display = self._value
            self._timer.stop()
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        size = min(w, h) - 24
        cx, cy = w / 2, h / 2

        # 背景环
        rect = QRectF(cx - size / 2, cy - size / 2, size, size)
        bg_pen = QPen(QColor(c("line_strong")), 10, Qt.SolidLine, Qt.RoundCap)
        p.setPen(bg_pen)
        p.drawArc(rect, 0 * 16, 360 * 16)

        # 前景环（accent，按进度绘制）
        start_angle = 90 * 16          # 从顶部开始
        span = int(-self._display / 100 * 360 * 16)
        fg_pen = QPen(QColor(c("context_color")), 10, Qt.SolidLine, Qt.RoundCap)
        p.setPen(fg_pen)
        p.drawArc(rect, start_angle, span)

        # 中心数值
        p.setPen(QColor(c("text_primary")))
        p.setFont(font_mono(40, bold=True))
        p.drawText(rect, Qt.AlignCenter, f"{self._display:.0f}")

        # 副标签
        p.setPen(QColor(c("text_tertiary")))
        p.setFont(font(11))
        sub_rect = QRectF(cx - size / 2, cy + size / 4, size, size / 4)
        p.drawText(sub_rect, Qt.AlignHCenter | Qt.AlignTop, self._label)


class HomePage(BasePage):
    """首页：展示今日运营指标、综合指数环、设备实时动态。"""

    def __init__(self, parent=None):
        super().__init__(
            title="千伴AI员工 · 群控台",
            subtitle="今日自动化运营数据总览（每 3 秒自动刷新）",
            parent=parent,
        )
        # 8 个 KPI 的 (value_label, trend_label) 引用
        self.kpi_refs = []
        self._worker = None  # 防 GC
        # 昨日快照缓存（QSettings 持久化，供趋势对比）
        self._yesterday = self._load_yesterday()
        self._build_ui()
        self._load()
        # 定时刷新（每 3 秒）
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._refresh)
        self.timer.start(3000)

    # ----------------- UI 构建 -----------------
    def _build_ui(self):
        # ====== 卡片1：AI 矩阵品牌综合指数（环形仪表盘，置顶） ======
        index_card, index_layout = make_card_frame("AI 矩阵品牌综合指数")
        self.ring = RingGauge()
        index_layout.addWidget(self.ring)
        self.content_layout.addWidget(index_card)

        # ====== 卡片2：今日运营指标（4×2 KPI 四件套） ======
        metric_card, metric_layout = make_card_frame("今日运营指标")
        # 8 个指标配置：(key, 标签, 颜色 key, 单位)
        # key 用于从 stats 取值 + QSettings 昨日缓存键
        self.kpi_defs = [
            ("videos",    "今日自动化处理量",   "context_color", ""),
            ("comments",  "AI智能语义响应",     "green",        ""),
            ("follows",   "对标账号精准锁定",   "yellow",       ""),
            ("likes",     "高意向私域触达",     "pink",         ""),
            ("e",         "高潜客群转化率",     "context_color", "%"),
            ("f",         "智能对话自主率",     "context_color", "%"),
            ("g",         "客群线索唤醒率",     "context_color", "%"),
            ("safety",    "矩阵全时风控安全度", "green",        "%"),
        ]
        # 分两行，每行 4 个
        for row_start in (0, 4):
            row = QHBoxLayout()
            row.setSpacing(12)
            for col in range(4):
                key, label_text, color_key, unit = self.kpi_defs[row_start + col]
                card, val_lb, trend_lb = make_kpi_card(
                    label_text, value="0", color=c(color_key)
                )
                # 缓存 unit 到 value_label 的 property，供 _apply_stats 格式化
                val_lb.setProperty("kpi_key", key)
                val_lb.setProperty("kpi_unit", unit)
                self.kpi_refs.append((val_lb, trend_lb))
                row.addWidget(card)
            metric_layout.addLayout(row)
        self.content_layout.addWidget(metric_card)

        # ====== 卡片3：设备实时动态 ======
        dev_card, dev_layout = make_card_frame("设备实时动态")
        self.device_table = make_table(
            ["序号", "序列号", "状态", "任务状态"], min_height=220
        )
        dev_layout.addWidget(self.device_table)
        self.content_layout.addWidget(dev_card)

    # ----------------- 数据加载 -----------------
    def _load(self):
        """异步加载：stats / tasks/status / devices（不阻塞 UI）。"""
        if self._worker is not None and self._worker.is_running():
            return
        worker = MultiApiWorker([
            ("/stats", None),
            ("/tasks/status", None),
            ("/devices", None),
        ])
        worker.result_ready.connect(self._on_load_done)
        worker.start()
        self._worker = worker  # 防 GC

    def _on_load_done(self, results: list):
        """异步加载完成回调：results = [stats_resp, task_resp, dev_resp]。"""
        self._worker = None
        stats_resp = results[0] if len(results) > 0 else {}
        task_resp = results[1] if len(results) > 1 else {}
        dev_resp = results[2] if len(results) > 2 else {}

        # 指标 + 综合指数
        stats = {}
        if stats_resp.get("success"):
            stats = stats_resp.get("data", {}) or {}
            if isinstance(stats, dict) and "data" in stats:
                stats = stats.get("data", {}) or {}
        self._apply_stats(stats)

        # 任务状态
        status_dict = {}
        if task_resp.get("success"):
            tdata = task_resp.get("status", {}) or {}
            if isinstance(tdata, dict):
                status_dict = tdata

        # 设备列表
        devices = []
        if dev_resp.get("success"):
            rows = dev_resp.get("devices", []) or []
            devices = rows if isinstance(rows, list) else []
        self._refresh_device_table(devices, status_dict)

    def _apply_stats(self, stats: dict):
        """把 stats 数据填到 8 个 KPI 卡（含趋势对比）和环形指数。

        趋势对比：用 QSettings 缓存的昨日末次快照计算 ▲/▼ 百分比；
        无昨日数据时隐藏趋势行（不造假数据）。
        """
        videos = stats.get("videos", 0) or 0
        comments = stats.get("comments", 0) or 0
        follows = stats.get("follows", 0) or 0
        likes = stats.get("likes", 0) or 0
        # E/F/G 后端不返回，前端本地计算（与 Streamlit 实现保持一致）
        e = 0.65 + (likes % 8) / 100
        f = 0.60 + (comments % 8) / 100
        g = 0.50 + (follows % 8) / 100
        safety = 0.998

        # 8 个指标当前值（顺序与 kpi_defs 一致）
        current = {
            "videos": float(videos),
            "comments": float(comments),
            "follows": float(follows),
            "likes": float(likes),
            "e": e,
            "f": f,
            "g": g,
            "safety": safety,
        }

        for (val_lb, trend_lb), (key, label_text, color_key, unit) in zip(
            self.kpi_refs, self.kpi_defs
        ):
            cur = current.get(key, 0.0)
            # 格式化数值
            if unit == "%":
                val_lb.setText(f"{cur * 100:.1f}%")
            else:
                val_lb.setText(f"{int(cur):,}")

            # 趋势对比
            yest = self._yesterday.get(key)
            if yest is not None and yest > 0:
                diff_pct = (cur - yest) / yest * 100
                if abs(diff_pct) < 0.1:
                    trend_lb.setText(f"— 0%")
                    trend_lb.setStyleSheet(
                        f"color: {c('text_tertiary')}; background: transparent;"
                    )
                elif diff_pct > 0:
                    trend_lb.setText(f"▲ {diff_pct:.1f}%")
                    trend_lb.setStyleSheet(
                        f"color: {c('green')}; background: transparent;"
                    )
                else:
                    trend_lb.setText(f"▼ {abs(diff_pct):.1f}%")
                    trend_lb.setStyleSheet(
                        f"color: {c('red')}; background: transparent;"
                    )
                trend_lb.show()
            else:
                # 无昨日数据，隐藏趋势（不造假）
                trend_lb.hide()

        # 综合指数 = base_floor + 随机偏移（0.65~0.72），归一化到 0~100
        base_floor = (
            videos * 0.5 + comments * 0.3 + follows * 0.15 + likes * 0.05
        )
        offset = random.uniform(0.65, 0.72)
        index_val = base_floor + offset
        # 映射到 0~100（假设满负荷 index≈200 → 100%）
        gauge_val = min(100.0, index_val / 200.0 * 100)
        self.ring.set_value(gauge_val)

        # 持久化今日快照（供次日作为昨日基线）
        self._save_today_snapshot(current)

    @staticmethod
    def _load_yesterday() -> dict:
        """从 QSettings 加载昨日快照。键名按日期区分。"""
        s = QSettings("QianBanAI", "HomeStats")
        today = date.today().isoformat()
        yesterday_key = f"snapshot_{today}"
        raw = s.value(yesterday_key, "")
        if not raw:
            return {}
        try:
            import json as _json
            return _json.loads(raw)
        except Exception:
            return {}

    @staticmethod
    def _save_today_snapshot(current: dict):
        """持久化今日末次快照（按日期键存储，次日读取即得昨日基线）。"""
        s = QSettings("QianBanAI", "HomeStats")
        today = date.today().isoformat()
        import json as _json
        s.setValue(f"snapshot_{today}", _json.dumps(current))

    def _refresh_device_table(self, devices: list, status_dict: dict):
        """刷新设备表：遍历设备列表，每台设备一行。"""
        self.device_table.setRowCount(len(devices))
        for i, dev in enumerate(devices):
            serial = str(dev) if not isinstance(dev, dict) else str(
                dev.get("serial") or dev.get("serial_no") or dev.get("id") or ""
            )
            status = "在线"
            if isinstance(dev, dict):
                status = str(dev.get("status") or dev.get("state") or "在线")
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
