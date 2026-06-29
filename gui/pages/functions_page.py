"""AI员工功能自主选择页：勾选 AI 员工执行任务时启用的功能。"""
from PySide6.QtWidgets import QHBoxLayout

from .common import (
    BasePage, api_get, ApiWorker,
    make_card_frame, make_primary_btn, make_checkbox, c,
)


class FunctionsPage(BasePage):
    """AI员工功能自主选择页。"""

    def __init__(self, parent=None):
        super().__init__(
            title="AI员工功能自主选择",
            subtitle="AI员工执行任务时，将严格按照下方从上到下的顺序执行已勾选功能。",
            parent=parent,
        )
        self._config = {}
        self._checkboxes = {}
        self._worker = None  # 防 GC
        self._build_ui()
        self._load_config()

    def _build_ui(self):
        # 功能开关卡片
        card, card_layout = make_card_frame("功能开关")
        # 各功能定义：(配置字段, 显示文案, 默认值, help 文本)
        items = [
            ("enable_like", "点赞", True, ""),
            ("enable_author_follow",
             "进入作者主页，粉丝数判断成功，关注作者，私信作者", True, ""),
            ("enable_video_comment", "AI生成评论，发布评论", True, ""),
            ("enable_comment_lead", "打开评论区，AI 识别自动评论，评论中回复", True, ""),
            ("night_mode_enabled", "🌙 夜间静默策略", True,
             "23:00-07:00 等待到早晨"),
            ("enable_anti_detection_probability", "🎲 概率决策策略（防风控）",
             False, "按概率随机执行"),
            ("turbo_test_mode", "⚡ 极速测试模式（临时调试）", False,
             "跳过人性化等待"),
        ]
        for field, label, default, help_text in items:
            cb = make_checkbox(label, checked=default)
            if help_text:
                # help 文本挂到 tooltip，避免破坏纵向排列
                cb.setToolTip(help_text)
            self._checkboxes[field] = cb
            card_layout.addWidget(cb)
        self.content_layout.addWidget(card)

        # 保存按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.save_btn = make_primary_btn("💾 保存当前配置")
        self.save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(self.save_btn)
        btn_row.addStretch(1)
        self.content_layout.addLayout(btn_row)

    def _load_config(self):
        data = api_get("/config", params={"platform": "douyin"})
        if data.get("success"):
            self._config = data.get("config", {}) or {}
            # 用 config 中的布尔值填充 checkbox
            for field, cb in self._checkboxes.items():
                val = self._config.get(field)
                if isinstance(val, bool):
                    cb.setChecked(val)
        else:
            self.set_status(f"加载配置失败：{data.get('message', '')}", "danger")

    def _on_save(self):
        payload = dict(self._config)
        # 收集 checkbox 状态
        for field, cb in self._checkboxes.items():
            payload[field] = cb.isChecked()
        self.save_btn.setEnabled(False)
        self.set_status("保存中...", "info")
        worker = ApiWorker("POST", "/config", json_body=payload,
                           params={"platform": "douyin"})
        worker.result_ready.connect(self._on_save_done)
        worker.start()
        self._worker = worker  # 防 GC

    def _on_save_done(self, data: dict):
        self.save_btn.setEnabled(True)
        if data.get("success"):
            self.set_status("配置已保存", "success")
        else:
            self.set_status(f"保存失败：{data.get('message', '')}", "danger")
