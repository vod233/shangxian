"""AI 截流获客策略页：设置评论识别范围、AI 自动回复、授权与模型参数。"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QFormLayout, QWidget

from .common import (
    BasePage, ApiWorker,
    make_card_frame, make_primary_btn, make_secondary_btn,
    make_line_edit, make_spinbox, make_slider, make_checkbox,
    make_field_label, c, font,
)


class StrategyPage(BasePage):
    """AI 截流获客策略页。"""

    def __init__(self, parent=None):
        super().__init__(
            title="AI 截流获客策略",
            subtitle="设置评论识别范围、AI 自动回复、授权与模型生成参数。",
            parent=parent,
        )
        self._config = {}
        self._worker = None  # 防 GC
        self._build_ui()
        self._load()

    def _build_ui(self):
        # 左右两卡片并排
        row = QHBoxLayout()
        row.setSpacing(16)

        # ====== 卡片1：评论截流范围 ======
        c1, l1 = make_card_frame("评论截流范围")
        form1 = QFormLayout()
        form1.setSpacing(12)
        form1.setLabelAlignment(Qt.AlignRight)

        # 每个视频最多 AI 识别评论数
        self.max_ai_comment_reviews = make_spinbox(min_val=1, max_val=200, default=20)
        form1.addRow(make_field_label("每个视频最多 AI 识别评论数："),
                     self.max_ai_comment_reviews)

        # 评论区最大向下滑动次数
        self.max_comment_swipes = make_spinbox(min_val=1, max_val=30, default=2)
        form1.addRow(make_field_label("评论区最大向下滑动次数："),
                     self.max_comment_swipes)

        # 启用 AI 自动回复与截流
        self.ai_enabled = make_checkbox("启用 AI 自动回复与截流", checked=True)
        form1.addRow(self.ai_enabled)

        l1.addLayout(form1)
        row.addWidget(c1, 1)

        # ====== 卡片2：授权与模型参数 ======
        c2, l2 = make_card_frame("授权与模型参数")
        form2 = QFormLayout()
        form2.setSpacing(10)
        form2.setLabelAlignment(Qt.AlignRight)

        # 客户授权码（password 模式）
        self.license_key_edit = make_line_edit(placeholder="请输入授权码", password=True)
        form2.addRow(make_field_label("客户授权码："), self.license_key_edit)

        # 授权服务器
        self.license_server_url_edit = make_line_edit(placeholder="授权服务器 URL")
        self.license_server_url_edit.setText("https://lcjx.yun/social-ai-credit-api")
        form2.addRow(make_field_label("授权服务器："), self.license_server_url_edit)

        # 模型名称（只读）
        self.ai_model_edit = make_line_edit()
        self.ai_model_edit.setText("deepseek-v4-flash")
        self.ai_model_edit.setReadOnly(True)
        form2.addRow(make_field_label("模型名称："), self.ai_model_edit)

        # 温度 slider（0-15，显示时 /10）
        temp_widget = QWidget()
        temp_lay = QHBoxLayout(temp_widget)
        temp_lay.setContentsMargins(0, 0, 0, 0)
        temp_lay.setSpacing(10)
        self.ai_temperature_slider = make_slider(min_val=0, max_val=15, default=7)
        self.ai_temperature_value_label = QLabel("0.7")
        self.ai_temperature_value_label.setFont(font(12, bold=True))
        self.ai_temperature_value_label.setStyleSheet(
            f"color: {c('context_color')}; background: transparent;"
            f"  padding: 2px 10px; min-width: 36px;"
        )
        self.ai_temperature_value_label.setAlignment(Qt.AlignCenter)
        self.ai_temperature_slider.valueChanged.connect(self._on_temp_changed)
        temp_lay.addWidget(self.ai_temperature_slider, 1)
        temp_lay.addWidget(self.ai_temperature_value_label)
        form2.addRow(make_field_label("AI 温度："), temp_widget)

        # 最大输出 Token（step 8）
        self.ai_max_tokens = make_spinbox(min_val=32, max_val=512, default=120)
        self.ai_max_tokens.setSingleStep(8)
        form2.addRow(make_field_label("最大输出 Token："), self.ai_max_tokens)

        l2.addLayout(form2)

        # 验证授权按钮
        btn_row2 = QHBoxLayout()
        btn_row2.addStretch(1)
        # 问题1修复：文案由"验证授权"改为"验证并保存授权"，明确告知用户该操作会持久化保存授权码
        self.verify_btn = make_secondary_btn("🔎 验证并保存授权")
        self.verify_btn.clicked.connect(self._on_verify_license)
        btn_row2.addWidget(self.verify_btn)
        l2.addLayout(btn_row2)

        row.addWidget(c2, 1)
        self.content_layout.addLayout(row)

        # 底部保存按钮
        save_row = QHBoxLayout()
        save_row.addStretch(1)
        self.save_btn = make_primary_btn("💾 保存当前配置")
        self.save_btn.clicked.connect(self._on_save)
        save_row.addWidget(self.save_btn)
        save_row.addStretch(1)
        self.content_layout.addLayout(save_row)

    def _on_temp_changed(self, val: int):
        """温度 slider 变化时更新显示值（slider 0-15 → 显示 0.0-1.5）。"""
        self.ai_temperature_value_label.setText(f"{val / 10:.1f}")

    def _load(self):
        """异步加载配置：GET /config?platform=douyin。

        参照 process_page._load 模式，原同步 api_get 会阻塞 GUI 线程最长 10 秒，
        改为 ApiWorker 后台请求，回调中更新 UI。
        """
        # 重入保护：上一次加载仍在运行时跳过
        if self._worker is not None:
            try:
                if self._worker.isRunning():
                    return
            except RuntimeError:
                pass
        worker = ApiWorker("GET", "/config", params={"platform": "douyin"})
        worker.result_ready.connect(self._on_load_done)
        worker.start()
        self._worker = worker  # 防 GC

    def _on_load_done(self, data: dict):
        """配置加载完成回调（GUI 线程执行）。"""
        self._worker = None  # 释放引用
        if not data.get("success"):
            self.set_status(f"加载配置失败：{data.get('message', '')}", "danger")
            return
        cfg = data.get("config", {}) or {}
        self._config = cfg

        # 评论截流范围
        if "max_ai_comment_reviews" in cfg:
            try:
                self.max_ai_comment_reviews.setValue(int(cfg["max_ai_comment_reviews"]))
            except (TypeError, ValueError):
                pass
        if "max_comment_swipes" in cfg:
            try:
                self.max_comment_swipes.setValue(int(cfg["max_comment_swipes"]))
            except (TypeError, ValueError):
                pass
        if "ai_enabled" in cfg:
            self.ai_enabled.setChecked(bool(cfg["ai_enabled"]))

        # 授权与模型参数
        if cfg.get("license_key"):
            self.license_key_edit.setText(str(cfg["license_key"]))
        if cfg.get("license_server_url"):
            self.license_server_url_edit.setText(str(cfg["license_server_url"]))
        if cfg.get("ai_model"):
            self.ai_model_edit.setText(str(cfg["ai_model"]))
        if "ai_temperature" in cfg:
            try:
                t = float(cfg["ai_temperature"])
                # 浮点转 slider 整数 0-15
                self.ai_temperature_slider.setValue(int(round(t * 10)))
                self.ai_temperature_value_label.setText(f"{t:.1f}")
            except (TypeError, ValueError):
                pass
        if "ai_max_tokens" in cfg:
            try:
                self.ai_max_tokens.setValue(int(cfg["ai_max_tokens"]))
            except (TypeError, ValueError):
                pass

        self.set_status("配置已加载", "success")

    def _collect_payload(self, base: dict = None) -> dict:
        """从控件收集配置 payload。base 为最新拉取的配置，避免跨页面缓存覆写。"""
        payload = dict(base if base is not None else self._config)
        payload["max_ai_comment_reviews"] = self.max_ai_comment_reviews.value()
        payload["max_comment_swipes"] = self.max_comment_swipes.value()
        payload["ai_enabled"] = self.ai_enabled.isChecked()
        payload["license_key"] = self.license_key_edit.text().strip()
        payload["license_server_url"] = self.license_server_url_edit.text().strip()
        payload["ai_model"] = self.ai_model_edit.text().strip()
        # 温度 slider 为整数 0-15，保存时 /10 转浮点
        payload["ai_temperature"] = self.ai_temperature_slider.value() / 10.0
        payload["ai_max_tokens"] = self.ai_max_tokens.value()
        return payload

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
        payload = self._collect_payload(base=latest)
        self.set_status("保存中...", "info")
        worker = ApiWorker("POST", "/config",
                           json_body=payload,
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

    def _on_verify_license(self):
        """验证并保存授权：POST /license/save?platform=douyin
        问题1修复：仅传授权相关字段，与后端 LicenseVerifyRequest 模型契约对齐，
        不再误传全量配置（避免数据契约不严谨）。
        """
        license_key = self.license_key_edit.text().strip()
        if not license_key:
            self.set_status("请先输入授权码", "warning")
            return
        self.verify_btn.setEnabled(False)
        self.set_status("正在验证并保存授权...", "info")
        # 仅传授权相关字段，匹配后端 LicenseVerifyRequest 模型
        license_payload = {
            "license_key": license_key,
            "license_server_url": self.license_server_url_edit.text().strip(),
        }
        worker = ApiWorker("POST", "/license/save",
                          json_body=license_payload,
                          params={"platform": "douyin"})
        worker.result_ready.connect(self._on_verify_done)
        worker.start()
        self._worker = worker  # 防 GC

    def _on_verify_done(self, data: dict):
        self.verify_btn.setEnabled(True)
        if data.get("success"):
            self.set_status(f"授权验证成功：{data.get('message', '已生效')}", "success")
        else:
            self.set_status(f"验证失败：{data.get('message', '')}", "danger")
