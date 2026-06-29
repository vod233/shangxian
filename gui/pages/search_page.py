"""搜索基础控制页：配置搜索行业关键词。"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QLabel

from .common import (
    BasePage, api_get, api_post, ApiWorker,
    make_card_frame, make_primary_btn, make_text_edit,
    make_field_label, make_section_label, c, font,
)


class SearchPage(BasePage):
    """AI搜索基础控制页。"""

    def __init__(self, parent=None):
        super().__init__(
            title="AI搜索基础控制",
            subtitle="配置搜索行业关键词（越精准越细分越好）。",
            parent=parent,
        )
        self._config = {}
        self._build_ui()
        self._load_config()

    def _build_ui(self):
        # 关键词卡片
        card, card_layout = make_card_frame("搜索关键词")
        self.keywords_edit = make_text_edit(
            placeholder="桌子\n椅子\n沙发\n（每行一个关键词）"
        )
        self.keywords_edit.setMinimumHeight(160)
        card_layout.addWidget(make_field_label("关键词列表（每行一个）："))
        card_layout.addWidget(self.keywords_edit)
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
            kws = self._config.get("search_keywords", [])
            if isinstance(kws, list):
                self.keywords_edit.setPlainText("\n".join(kws))
        else:
            self.set_status(f"加载配置失败：{data.get('message', '')}", "danger")

    def _on_save(self):
        keywords = [k.strip() for k in self.keywords_edit.toPlainText().split("\n") if k.strip()]
        if not keywords:
            self.set_status("请至少输入一个关键词", "warning")
            return
        payload = dict(self._config)
        payload["search_keywords"] = keywords
        payload["sort_by"] = "latest"
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
