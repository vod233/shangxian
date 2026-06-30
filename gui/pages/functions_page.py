"""AI员工功能自主选择页：勾选 AI 员工执行任务时启用的功能。"""
from PySide6.QtWidgets import QHBoxLayout

from .common import (
    BasePage, api_get, ApiWorker,
    make_card_frame, make_primary_btn, make_checkbox, make_radio_group, c,
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

        # 业务模式选择
        mode_card, mode_layout = make_card_frame("业务模式")
        self._mode_group_box, self._mode_btn_group, self._mode_radios = make_radio_group(
            [
                {"value": 1, "label": "模式1：作者私信流（关注 + 私信作者）"},
                {"value": 2, "label": "模式2：评论区截流（发评论 + 识别回复 + 楼中楼私信）"},
            ],
            default=2,
        )
        mode_layout.addWidget(self._mode_group_box)
        self.content_layout.addWidget(mode_card)

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
            # 加载业务模式
            mode_val = self._config.get("business_mode", 2)
            for rb in self._mode_radios:
                if rb.property("value") == mode_val:
                    rb.setChecked(True)
                    break
        else:
            self.set_status(f"加载配置失败：{data.get('message', '')}", "danger")

    def _on_save(self):
        """保存配置：先异步拉取最新配置（避免跨页面缓存覆写），再合并本页字段后 POST。"""
        self.save_btn.setEnabled(False)
        self.set_status("正在拉取最新配置...", "info")
        worker = ApiWorker("GET", "/config", params={"platform": "douyin"})
        worker.result_ready.connect(self._on_latest_config_loaded)
        worker.start()
        self._worker = worker  # 防 GC

    def _on_latest_config_loaded(self, data: dict):
        """最新配置拉取完成：校验后合并本页字段并提交保存。"""
        if not data.get("success"):
            self.save_btn.setEnabled(True)
            self.set_status(f"拉取最新配置失败：{data.get('message', '')}", "danger")
            return
        latest = data.get("config", {}) or {}
        # 校验必填字段存在，避免后端 422
        if not latest.get("search_keywords"):
            self.save_btn.setEnabled(True)
            self.set_status("服务端配置不完整（缺少 search_keywords），无法保存", "danger")
            return
        self._config = latest  # 更新本地缓存为最新值
        # 基于最新配置合并本页字段
        payload = dict(latest)
        for field, cb in self._checkboxes.items():
            payload[field] = cb.isChecked()
        for rb in self._mode_radios:
            if rb.isChecked():
                payload["business_mode"] = rb.property("value")
                break
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
