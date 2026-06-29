"""AI员工私信话术调整页：配置作者私信话术与评论区私信话术。"""
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout

from .common import (
    BasePage, api_get, ApiWorker,
    make_card_frame, make_primary_btn, make_checkbox, make_doublespinbox,
    make_text_edit, make_field_label, c,
)


class MessagePage(BasePage):
    """AI员工私信话术调整页。"""

    def __init__(self, parent=None):
        super().__init__(
            title="AI员工私信话术调整",
            subtitle="设置作者私信话术《话术要合规矩》。",
            parent=parent,
        )
        self._config = {}
        self._build_ui()
        self._load_config()

    def _build_ui(self):
        # 左右两卡片并排
        cards_row = QHBoxLayout()

        # 卡片1：作者私信话术
        card1, card1_layout = make_card_frame("作者私信话术")
        card1_layout.addWidget(make_field_label("话术列表（每行一条）："))
        self.pm_message_edit = make_text_edit(
            placeholder="话术1\n话术2\n（每行一条话术）"
        )
        self.pm_message_edit.setMinimumHeight(160)
        card1_layout.addWidget(self.pm_message_edit)
        card1_layout.addWidget(make_field_label("最小关注量阈值（万）："))
        self.min_followers_spin = make_doublespinbox(
            min_val=0.0, max_val=1000.0, default=0.0, step=0.1
        )
        card1_layout.addWidget(self.min_followers_spin)
        self.enable_pm_cb = make_checkbox("启用作者私信", checked=True)
        card1_layout.addWidget(self.enable_pm_cb)
        card1_layout.addWidget(make_field_label("私信粉丝阈值（万）："))
        self.pm_followers_spin = make_doublespinbox(
            min_val=0.0, max_val=1000.0, default=1.0, step=0.1
        )
        card1_layout.addWidget(self.pm_followers_spin)
        cards_row.addWidget(card1)

        # 卡片2：评论区私信话术
        card2, card2_layout = make_card_frame("评论区私信话术")
        card2_layout.addWidget(make_field_label("话术列表（每行一条）："))
        self.lead_pm_message_edit = make_text_edit(
            placeholder="话术1\n话术2\n（每行一条话术）"
        )
        self.lead_pm_message_edit.setMinimumHeight(160)
        card2_layout.addWidget(self.lead_pm_message_edit)
        self.enable_lead_pm_cb = make_checkbox("启用评论区私信", checked=False)
        card2_layout.addWidget(self.enable_lead_pm_cb)
        cards_row.addWidget(card2)

        self.content_layout.addLayout(cards_row)

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
            # 作者私信话术
            pm_list = self._config.get("pm_message_list", [])
            if isinstance(pm_list, list):
                self.pm_message_edit.setPlainText(
                    "\n".join(str(s) for s in pm_list)
                )
            # 最小关注量阈值
            val = self._config.get("min_followers_threshold")
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                self.min_followers_spin.setValue(float(val))
            # 启用作者私信
            epm = self._config.get("enable_private_message")
            if isinstance(epm, bool):
                self.enable_pm_cb.setChecked(epm)
            # 私信粉丝阈值
            pft = self._config.get("pm_followers_threshold")
            if isinstance(pft, (int, float)) and not isinstance(pft, bool):
                self.pm_followers_spin.setValue(float(pft))
            # 评论区私信话术
            lead_list = self._config.get("lead_pm_message_list", [])
            if isinstance(lead_list, list):
                self.lead_pm_message_edit.setPlainText(
                    "\n".join(str(s) for s in lead_list)
                )
            # 启用评论区私信
            elpm = self._config.get("enable_comment_lead_pm")
            if isinstance(elpm, bool):
                self.enable_lead_pm_cb.setChecked(elpm)
        else:
            self.set_status(f"加载配置失败：{data.get('message', '')}", "danger")

    def _on_save(self):
        payload = dict(self._config)
        # 作者私信话术（多行 → list）
        pm_lines = [l.strip() for l in self.pm_message_edit.toPlainText().split("\n")
                    if l.strip()]
        payload["pm_message_list"] = pm_lines
        payload["min_followers_threshold"] = self.min_followers_spin.value()
        payload["enable_private_message"] = self.enable_pm_cb.isChecked()
        payload["pm_followers_threshold"] = self.pm_followers_spin.value()
        # 评论区私信话术
        lead_lines = [l.strip() for l in self.lead_pm_message_edit.toPlainText().split("\n")
                      if l.strip()]
        payload["lead_pm_message_list"] = lead_lines
        payload["enable_comment_lead_pm"] = self.enable_lead_pm_cb.isChecked()
        self.save_btn.setEnabled(False)
        self.set_status("保存中...", "info")
        worker = ApiWorker("POST", "/config", json_body=payload,
                           params={"platform": "douyin"})
        worker.finished.connect(self._on_save_done)
        worker.start()
        self._worker = worker  # 防 GC

    def _on_save_done(self, data: dict):
        self.save_btn.setEnabled(True)
        if data.get("success"):
            self.set_status("配置已保存", "success")
        else:
            self.set_status(f"保存失败：{data.get('message', '')}", "danger")
