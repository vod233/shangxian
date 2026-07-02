"""AI深度抓取意向关键词页：配置意向触发词与 AI 人格。"""
from PySide6.QtWidgets import QHBoxLayout

from .common import (
    BasePage, api_get, ApiWorker,
    make_card_frame, make_primary_btn, make_radio_group, make_line_edit,
    make_field_label, c,
)


class IntentPage(BasePage):
    """AI深度抓取意向关键词页。"""

    def __init__(self, parent=None):
        super().__init__(
            title="AI深度抓取意向关键词",
            subtitle="设置评论区出现后AI识别抓取意向客户的触发词。",
            parent=parent,
        )
        self._config = {}
        self._worker = None  # 防 GC
        self._build_ui()
        self._load_config()

    def _build_ui(self):
        # 卡片1：AI 人格选择
        card1, card1_layout = make_card_frame("AI 人格选择")
        self.persona_group, self.persona_btn_group, self.persona_radios = \
            make_radio_group(
                options=[
                    {"value": "a_zhen", "label": "阿珍"},
                    {"value": "a_qiang", "label": "阿强"},
                ],
                default="a_zhen",
            )
        card1_layout.addWidget(self.persona_group)
        self.content_layout.addWidget(card1)

        # 卡片2：意向触发词
        card2, card2_layout = make_card_frame("意向触发词")
        card2_layout.addWidget(make_field_label("触发词（英文逗号分隔）："))
        self.keywords_edit = make_line_edit(
            placeholder="产品,采购,咨询,价格,怎么卖"
        )
        card2_layout.addWidget(self.keywords_edit)
        self.content_layout.addWidget(card2)

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
            # AI 人格
            persona = self._config.get("ai_persona")
            if persona:
                for rb in self.persona_radios:
                    if rb.property("value") == persona:
                        rb.setChecked(True)
                        break
            # 意向触发词（兼容 list 或 str）
            kws = self._config.get("intent_keywords", [])
            if isinstance(kws, list):
                self.keywords_edit.setText(",".join(str(k) for k in kws))
            elif isinstance(kws, str):
                self.keywords_edit.setText(kws)
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
        checked = self.persona_btn_group.checkedButton()
        if checked is not None:
            payload["ai_persona"] = checked.property("value")
        text = self.keywords_edit.text().strip()
        kws = [k.strip() for k in text.split(",") if k.strip()]
        payload["intent_keywords"] = kws
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
