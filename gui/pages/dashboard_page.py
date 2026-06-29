"""数据看板页：今日自动化执行结果汇总 + 详细操作记录表格。"""
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QMessageBox, QTableWidgetItem,
)

from .common import (
    ApiWorker, BasePage, MultiApiWorker,
    make_card_frame, make_danger_btn, make_metric_card, make_secondary_btn,
    make_table, c, font,
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
        # ====== 卡片1：今日汇总（2x4 网格，8 张 KPI） ======
        summary_card, summary_layout = make_card_frame("今日汇总（4 大功能模块）")
        # 第一行：基础互动指标
        row1 = QHBoxLayout()
        row1.setSpacing(8)
        # 第二行：4 大功能模块指标
        row2 = QHBoxLayout()
        row2.setSpacing(8)
        # 8 个 KPI：(初始值, 描述, 颜色 key, 行号)
        defs = [
            ("0", "今日处理视频", "context_color", 1),
            ("0", "自动点赞", "pink", 1),
            ("0", "自动关注同行", "yellow", 1),
            ("0", "视频主评论", "green", 2),       # 模块③
            ("0", "楼中楼回复", "green", 2),       # 模块④
            ("0", "博主私信", "green", 2),         # 模块①
            ("0", "评论者私信", "green", 2),       # 模块②
            ("0", "潜客线索数", "pink", 1),        # 核心商业价值
        ]
        for value_text, label_text, color_key, row_no in defs:
            card = make_metric_card(value_text, label_text, color=c(color_key))
            self.metric_cards.append(card)
            if row_no == 1:
                row1.addWidget(card)
            else:
                row2.addWidget(card)
        summary_layout.addLayout(row1)
        summary_layout.addLayout(row2)
        self.content_layout.addWidget(summary_card)

        # ====== 卡片2：今日详细操作记录（14 列，覆盖 4 大功能模块） ======
        detail_card, detail_layout = make_card_frame("今日详细操作记录")
        self.detail_table = make_table(
            [
                "时间", "关键词", "视频ID", "博主粉丝", "停留时长",
                "处理状态", "点赞", "关注",
                "视频评论",       # 模块③：AI 对视频本身的评论
                "意向评论",       # 模块④触发原因：识别到的意向评论
                "楼中楼回复",     # 模块④：对意向评论的回复
                "博主私信",       # 模块①：给博主私信
                "评论者私信",     # 模块②：给评论者私信
                "异常",
            ],
            min_height=360,
        )
        detail_layout.addWidget(self.detail_table)
        self.content_layout.addWidget(detail_card)

        # ====== 底部按钮：刷新 + 删除数据 ======
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.refresh_btn = make_secondary_btn("🔄 刷新数据")
        self.refresh_btn.clicked.connect(self._on_refresh)
        btn_row.addWidget(self.refresh_btn)

        # 删除今日数据按钮（危险操作，二次确认）
        self.delete_btn = make_danger_btn("🗑️ 删除今日数据")
        self.delete_btn.clicked.connect(self._on_delete_clicked)
        btn_row.addWidget(self.delete_btn)
        btn_row.addStretch(1)
        self.content_layout.addLayout(btn_row)

        self._delete_worker = None  # 防 GC

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
        worker.result_ready.connect(self._on_load_done)
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
        """刷新 8 个汇总指标卡的 value_label。

        顺序与 _build_ui 中的 defs 一致：
        今日处理视频 / 自动点赞 / 自动关注同行 / 视频主评论 /
        楼中楼回复 / 博主私信 / 评论者私信 / 潜客线索数
        """
        values = [
            str(stats.get("videos", 0) or 0),
            str(stats.get("likes", 0) or 0),
            str(stats.get("follows", 0) or 0),
            str(stats.get("comments", 0) or 0),       # 视频主评论 SUM(commented)
            str(stats.get("lead_replies", 0) or 0),   # 楼中楼回复 SUM(lead_sent)
            str(stats.get("pm_sent", 0) or 0),        # 博主私信 SUM(pm_sent)
            str(stats.get("lead_pm_sent", 0) or 0),   # 评论者私信 SUM(lead_pm_sent)
            str(stats.get("leads", 0) or 0),          # 潜客线索数
        ]
        for card, val in zip(self.metric_cards, values):
            # value_label 是 card 内第一个 QLabel（大字号值标签）
            value_lb = card.findChildren(QLabel)[0]
            value_lb.setText(val)

    def _apply_details(self, rows: list):
        """把详细记录填入表格，每条一行。

        14 列覆盖 4 大功能模块：
        时间/关键词/视频ID/博主粉丝/停留时长/处理状态/点赞/关注/
        视频评论(模块③)/意向评论(模块④触发)/楼中楼回复(模块④)/
        博主私信(模块①)/评论者私信(模块②)/异常
        """
        self.detail_table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            if not isinstance(row, dict):
                # 非 dict 行：把整行当作首列
                self.detail_table.setItem(i, 0, QTableWidgetItem(str(row)))
                continue
            # 长文本截断显示，悬停可看完整（Qt QTableWidgetItem 自带 tooltip）
            def _trunc(s, n=20):
                s = str(s or "")
                return s if len(s) <= n else s[:n] + "…"

            ai_reply = str(row.get("ai_reply") or "")
            intent_comment = str(row.get("intent_comment") or "")
            lead_reply = str(row.get("lead_reply") or "")

            # 列顺序与 _build_ui 表头一致
            cells = [
                str(row.get("created_at") or row.get("time") or row.get("timestamp") or ""),
                str(row.get("keyword") or row.get("kw") or ""),
                str(row.get("video_id") or row.get("aweme_id") or row.get("id") or ""),
                str(row.get("follower_count") or row.get("fans") or row.get("fans_count") or 0),
                str(row.get("stay_duration") or row.get("stay") or row.get("duration") or 0),
                str(row.get("process_status") or row.get("status") or ""),
                "✓" if row.get("liked") else "",
                "✓" if row.get("followed") else "",
                _trunc(ai_reply),                       # 模块③：视频评论内容
                _trunc(intent_comment),                 # 模块④触发：意向评论文本
                _trunc(lead_reply),                     # 模块④：楼中楼回复内容
                "✓" if (row.get("pm_sent") or row.get("private_messaged")) else "",  # 模块①
                "✓" if row.get("lead_pm_sent") else "", # 模块②
                str(row.get("error_message") or row.get("error") or row.get("exception") or ""),
            ]
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                # 长文本字段添加完整内容 tooltip，方便客户查看 AI 实际说了什么
                if col == 8 and ai_reply:        # 视频评论
                    item.setToolTip(ai_reply)
                elif col == 9 and intent_comment: # 意向评论
                    item.setToolTip(intent_comment)
                elif col == 10 and lead_reply:    # 楼中楼回复
                    item.setToolTip(lead_reply)
                self.detail_table.setItem(i, col, item)

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
        worker.result_ready.connect(self._on_load_done)
        worker.start()
        self._worker = worker  # 防 GC

    # ----------------- 删除今日数据 -----------------
    def _on_delete_clicked(self):
        """删除按钮点击：弹出二次确认框，确认后异步调用 DELETE /stats。

        危险操作保护：
        1. QMessageBox 二次确认，默认按钮为"取消"
        2. 删除期间禁用删除/刷新按钮，防止重复点击
        3. 删除成功后立即触发刷新，让客户看到清空效果
        """
        # 重入保护：上一次删除请求仍在进行时忽略
        if self._delete_worker is not None:
            try:
                if self._delete_worker.isRunning():
                    return
            except RuntimeError:
                pass

        # 二次确认弹窗
        reply = QMessageBox.warning(
            self,
            "确认删除今日数据",
            "<p>此操作将<b style='color:#ef4444'>永久清空</b>今日所有操作记录，包括：</p>"
            "<p>· 8 项 KPI 指标计数<br>"
            "· 详细操作记录(视频评论、楼中楼回复、私信记录等)<br>"
            "· AI 对话内容</p>"
            "<p><b>不影响</b>历史日期数据、关键词配置、设备连接。</p>"
            "<p>确定要继续吗？</p>",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,  # 默认聚焦"否"，避免误操作
        )
        if reply != QMessageBox.Yes:
            return

        # 禁用按钮，发起异步删除请求
        self.delete_btn.setEnabled(False)
        self.refresh_btn.setEnabled(False)
        self.set_status("正在删除今日数据...", "info")
        worker = ApiWorker("DELETE", "/stats")
        worker.result_ready.connect(self._on_delete_done)
        worker.start()
        self._delete_worker = worker  # 防 GC

    def _on_delete_done(self, data: dict):
        """删除请求完成回调（GUI 线程执行）。"""
        self._delete_worker = None
        self.delete_btn.setEnabled(True)
        if data.get("success"):
            self.set_status(
                f"删除成功：{data.get('message', '今日数据已清空')}", "success"
            )
            # 立即触发刷新，让 KPI 和详细表归零
            self._on_refresh()
        else:
            self.set_status(
                f"删除失败：{data.get('message', '未知错误')}", "danger"
            )
