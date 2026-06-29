"""数据看板页：今日自动化执行结果汇总 + 详细操作记录表格。"""
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QTableWidgetItem

from .common import (
    BasePage, MultiApiWorker,
    make_card_frame, make_metric_card, make_secondary_btn, make_table,
    c, font,
)


class DashboardPage(BasePage):
    """获客数据看板页。"""

    def __init__(self, parent=None):
        super().__init__(
            title="📊 获客数据看板",
            subtitle="实时查看今日自动化执行结果及详细处理记录。",
            parent=parent,
        )
        # 4 个汇总指标卡的 value_label 引用（顺序：videos/likes/follows/comments）
        self.metric_cards = []
        self._worker = None  # 防 GC
        self._build_ui()
        self._load()
        # 问题2修复：增加自动刷新定时器（每 5 秒），与"实时查看"副标题一致
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._load)
        self.timer.start(5000)

    def _build_ui(self):
        # ====== 卡片1：今日汇总（1x4 网格） ======
        summary_card, summary_layout = make_card_frame("今日汇总")
        row = QHBoxLayout()
        row.setSpacing(12)
        # 4 个汇总指标：(初始值, 描述, 颜色 key)
        defs = [
            ("0", "今日处理视频总数", "context_color"),
            ("0", "自动点赞数", "pink"),
            ("0", "自动关注同行", "yellow"),
            ("0", "AI 自动回复", "green"),
        ]
        for value_text, label_text, color_key in defs:
            card = make_metric_card(value_text, label_text, color=c(color_key))
            self.metric_cards.append(card)
            row.addWidget(card)
        summary_layout.addLayout(row)
        self.content_layout.addWidget(summary_card)

        # ====== 卡片2：今日详细操作记录 ======
        detail_card, detail_layout = make_card_frame("今日详细操作记录")
        self.detail_table = make_table(
            [
                "时间", "关键词", "视频ID", "处理状态", "停留时长",
                "粉丝数", "点赞", "评论", "关注", "私信", "异常",
            ],
            min_height=360,
        )
        detail_layout.addWidget(self.detail_table)
        self.content_layout.addWidget(detail_card)

        # ====== 底部刷新按钮 ======
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.refresh_btn = make_secondary_btn("🔄 刷新数据")
        self.refresh_btn.clicked.connect(self._on_refresh)
        btn_row.addWidget(self.refresh_btn)
        btn_row.addStretch(1)
        self.content_layout.addLayout(btn_row)

    def _load(self):
        """异步加载：stats + stats/details?limit=100（不阻塞 UI）。
        问题2/3修复：原同步串行 2 个请求会阻塞 UI，改用 MultiApiWorker 后台并发。
        Review修复2：重入保护，上一个 worker 仍在运行时跳过本次，避免乱序回调。
        """
        # Review修复2：重入保护，避免旧请求结果覆盖新请求
        if self._worker is not None and self._worker.is_running():
            return
        worker = MultiApiWorker([
            ("/stats", None),
            ("/stats/details", {"limit": 100}),
        ])
        worker.finished.connect(self._on_load_done)
        worker.start()
        self._worker = worker  # 防 GC

    def _on_load_done(self, results: list):
        """异步加载完成回调：results = [stats_resp, detail_resp]。"""
        # Review修复1补充：回调开头清理 worker 引用，避免下次定时器访问已 deleteLater 的对象
        self._worker = None
        stats_resp = results[0] if len(results) > 0 else {}
        detail_resp = results[1] if len(results) > 1 else {}

        # 今日汇总
        stats = {}
        if stats_resp.get("success"):
            stats = stats_resp.get("data", {}) or {}
            if isinstance(stats, dict) and "data" in stats:
                stats = stats.get("data", {}) or {}
        else:
            self.set_status(
                f"汇总加载失败：{stats_resp.get('message', '')}", "danger"
            )
        self._apply_stats(stats)

        # 详细记录
        rows = []
        if detail_resp.get("success"):
            rdata = detail_resp.get("data", []) or []
            if isinstance(rdata, dict):
                rdata = rdata.get("details") or rdata.get("rows") or rdata.get("items") or []
            rows = rdata if isinstance(rdata, list) else []
        else:
            self.set_status(
                f"详细记录加载失败：{detail_resp.get('message', '')}", "danger"
            )
        self._apply_details(rows)

        # Review修复3：异步加载完成后恢复刷新按钮状态（替代原 1500ms 硬编码定时器）
        if hasattr(self, "refresh_btn"):
            self.refresh_btn.setEnabled(True)
            self.clear_status()

    def _apply_stats(self, stats: dict):
        """刷新 4 个汇总指标卡的 value_label。"""
        values = [
            str(stats.get("videos", 0) or 0),
            str(stats.get("likes", 0) or 0),
            str(stats.get("follows", 0) or 0),
            str(stats.get("comments", 0) or 0),
        ]
        for card, val in zip(self.metric_cards, values):
            # value_label 是 card 内第一个 QLabel（大字号值标签）
            value_lb = card.findChildren(QLabel)[0]
            value_lb.setText(val)

    def _apply_details(self, rows: list):
        """把详细记录填入表格，每条一行。"""
        self.detail_table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            if not isinstance(row, dict):
                # 非 dict 行：把整行当作首列
                self.detail_table.setItem(i, 0, QTableWidgetItem(str(row)))
                continue
            # 列顺序：时间/关键词/视频ID/处理状态/停留时长/粉丝数/点赞/评论/关注/私信/异常
            # 字段名与后端实际返回对齐：
            #   点赞 liked(bool) / 评论 commented(bool) / 关注 followed(bool)
            #   私信 private_messaged(bool) / 异常 error_message(str)
            cells = [
                str(row.get("created_at") or row.get("time") or row.get("timestamp") or ""),
                str(row.get("keyword") or row.get("kw") or ""),
                str(row.get("video_id") or row.get("aweme_id") or row.get("id") or ""),
                str(row.get("process_status") or row.get("status") or ""),
                str(row.get("stay_duration") or row.get("stay") or row.get("duration") or ""),
                str(row.get("follower_count") or row.get("fans") or row.get("fans_count") or 0),
                "✓" if row.get("liked") else "",
                "✓" if row.get("commented") else "",
                "✓" if row.get("followed") else "",
                "✓" if row.get("private_messaged") else "",
                str(row.get("error_message") or row.get("error") or row.get("exception") or ""),
            ]
            for col, text in enumerate(cells):
                self.detail_table.setItem(i, col, QTableWidgetItem(text))

    def _on_refresh(self):
        """刷新按钮回调：触发异步重新加载汇总与详细记录。
        Review修复3：按钮禁用后由 _on_load_done 在异步完成时恢复，
        不再用 1500ms 硬编码定时器，保证状态与实际加载同步。
        手动刷新绕过 _load() 的重入保护，强制创建新 worker。
        """
        self.set_status("刷新中...", "info")
        self.refresh_btn.setEnabled(False)
        # 手动刷新强制触发，不受重入保护限制
        worker = MultiApiWorker([
            ("/stats", None),
            ("/stats/details", {"limit": 100}),
        ])
        worker.finished.connect(self._on_load_done)
        worker.start()
        self._worker = worker  # 防 GC
