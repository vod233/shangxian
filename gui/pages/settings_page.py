"""系统设置页：字体大小、界面外观、窗口行为等通用配置。"""
import os
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QVBoxLayout, QLabel, QSlider, QComboBox,
    QSpinBox, QCheckBox, QButtonGroup, QRadioButton,
)

from .common import (
    BasePage, make_card_frame, make_primary_btn, make_secondary_btn,
    make_field_label, make_section_label, make_spinbox,
    make_checkbox, c, font, ApiWorker,
)


class SettingsPage(BasePage):
    """系统设置页。"""

    def __init__(self, parent=None):
        super().__init__(
            title="系统设置",
            subtitle="自定义界面外观、字体大小、窗口行为等通用配置。修改后点击保存立即生效。",
            parent=parent,
        )
        self._settings = None
        self._build_ui()
        self._load_settings()

    def _build_ui(self):
        # ============ 外观设置 ============
        card_appearance, layout_appearance = make_card_frame("外观设置")

        # 字体大小
        layout_appearance.addWidget(make_field_label("字体大小："))
        font_row = QHBoxLayout()
        self.font_size_slider = QSlider(Qt.Horizontal)
        self.font_size_slider.setMinimum(6)
        self.font_size_slider.setMaximum(16)
        self.font_size_slider.setValue(9)
        self.font_size_slider.setStyleSheet(
            f"QSlider::groove:horizontal {{ background-color: {c('dark_three')};"
            f"  height: 6px; border-radius: 3px; }}"
            f"QSlider::handle:horizontal {{ background-color: {c('context_color')};"
            f"  width: 18px; height: 18px; margin: -7px 0; border-radius: 9px; }}"
            f"QSlider::handle:horizontal:hover {{ background-color: {c('context_hover')}; }}"
            f"QSlider::sub-page:horizontal {{ background-color: {c('context_color')};"
            f"  border-radius: 3px; }}"
        )
        self.font_size_value = QLabel("9 pt")
        self.font_size_value.setFont(font(13, bold=True))
        self.font_size_value.setStyleSheet(
            f"color: {c('text_title')}; background: transparent; min-width: 50px;"
        )
        self.font_size_value.setAlignment(Qt.AlignCenter)
        self.font_size_slider.valueChanged.connect(
            lambda v: self.font_size_value.setText(f"{v} pt")
        )
        font_row.addWidget(self.font_size_slider, 1)
        font_row.addWidget(self.font_size_value)
        layout_appearance.addLayout(font_row)

        # 字体族
        layout_appearance.addWidget(make_field_label("字体族："))
        self.font_family_combo = QComboBox()
        self.font_family_combo.setFont(font(13))
        self.font_family_combo.setStyleSheet(
            f"QComboBox {{ background-color: {c('dark_one')}; color: {c('text_title')};"
            f"  border: 1px solid {c('dark_four')}; border-radius: 6px;"
            f"  padding: 8px 10px; font-size: 13px;"
            f"  selection-background-color: {c('context_color')}; }}"
            f"QComboBox:focus {{ border: 1px solid {c('context_color')}; }}"
            f"QComboBox::drop-down {{ border: none; width: 24px; }}"
            f"QComboBox QAbstractItemView {{ background-color: {c('dark_two')};"
            f"  color: {c('text_title')}; selection-background-color: {c('context_color')};"
            f"  border: 1px solid {c('dark_four')}; }}"
        )
        self.font_family_combo.setMinimumHeight(36)
        self._populate_font_families()
        layout_appearance.addWidget(self.font_family_combo)

        self.content_layout.addWidget(card_appearance)

        # ============ 窗口设置 ============
        card_window, layout_window = make_card_frame("窗口设置")

        # 启动窗口大小
        layout_window.addWidget(make_field_label("启动窗口大小："))
        size_row = QHBoxLayout()
        size_left = QVBoxLayout()
        size_right = QVBoxLayout()

        size_left.addWidget(make_field_label("宽度："))
        self.window_width_spin = make_spinbox(min_val=800, max_val=3840, default=1400, suffix="px")
        size_left.addWidget(self.window_width_spin)

        size_right.addWidget(make_field_label("高度："))
        self.window_height_spin = make_spinbox(min_val=500, max_val=2160, default=720, suffix="px")
        size_right.addWidget(self.window_height_spin)

        size_row.addLayout(size_left)
        size_row.addLayout(size_right)
        layout_window.addLayout(size_row)

        # 动画时长
        layout_window.addWidget(make_field_label("界面动画时长："))
        anim_row = QHBoxLayout()
        self.anim_speed_slider = QSlider(Qt.Horizontal)
        self.anim_speed_slider.setMinimum(100)
        self.anim_speed_slider.setMaximum(1000)
        self.anim_speed_slider.setSingleStep(50)
        self.anim_speed_slider.setValue(500)
        self.anim_speed_slider.setStyleSheet(
            f"QSlider::groove:horizontal {{ background-color: {c('dark_three')};"
            f"  height: 6px; border-radius: 3px; }}"
            f"QSlider::handle:horizontal {{ background-color: {c('context_color')};"
            f"  width: 18px; height: 18px; margin: -7px 0; border-radius: 9px; }}"
            f"QSlider::handle:horizontal:hover {{ background-color: {c('context_hover')}; }}"
            f"QSlider::sub-page:horizontal {{ background-color: {c('context_color')};"
            f"  border-radius: 3px; }}"
        )
        self.anim_speed_value = QLabel("500 ms")
        self.anim_speed_value.setFont(font(13, bold=True))
        self.anim_speed_value.setStyleSheet(
            f"color: {c('text_title')}; background: transparent; min-width: 60px;"
        )
        self.anim_speed_value.setAlignment(Qt.AlignCenter)
        self.anim_speed_slider.valueChanged.connect(
            lambda v: self.anim_speed_value.setText(f"{v} ms")
        )
        anim_row.addWidget(self.anim_speed_slider, 1)
        anim_row.addWidget(self.anim_speed_value)
        layout_window.addLayout(anim_row)

        # 自定义标题栏
        self.custom_titlebar_cb = make_checkbox("启用自定义标题栏（深色无边框窗口）", True)
        layout_window.addWidget(self.custom_titlebar_cb)

        self.content_layout.addWidget(card_window)

        # ============ 侧边栏设置 ============
        card_sidebar, layout_sidebar = make_card_frame("侧边栏设置")

        # 左侧菜单宽度
        layout_sidebar.addWidget(make_field_label("左侧菜单展开宽度："))
        self.left_menu_width_spin = make_spinbox(min_val=150, max_val=400, default=240, suffix="px")
        layout_sidebar.addWidget(self.left_menu_width_spin)

        # 左右栏宽度
        col_row = QHBoxLayout()
        col_left = QVBoxLayout()
        col_right = QVBoxLayout()

        col_left.addWidget(make_field_label("左栏宽度："))
        self.left_col_width_spin = make_spinbox(min_val=150, max_val=400, default=240, suffix="px")
        col_left.addWidget(self.left_col_width_spin)

        col_right.addWidget(make_field_label("右栏宽度："))
        self.right_col_width_spin = make_spinbox(min_val=150, max_val=400, default=240, suffix="px")
        col_right.addWidget(self.right_col_width_spin)

        col_row.addLayout(col_left)
        col_row.addLayout(col_right)
        layout_sidebar.addLayout(col_row)

        self.content_layout.addWidget(card_sidebar)

        # ============ 授权信息 ============
        card_license, layout_license = make_card_frame("授权信息")

        self.license_customer_label = QLabel("客户：--")
        self.license_customer_label.setFont(font(13))
        self.license_customer_label.setStyleSheet(
            f"color: {c('text_foreground')}; background: transparent;"
        )

        self.license_balance_label = QLabel("积分余额：--")
        self.license_balance_label.setFont(font(15, bold=True))

        self.license_masked_label = QLabel("授权码：--")
        self.license_masked_label.setFont(font(12))
        self.license_masked_label.setStyleSheet(
            f"color: {c('text_description')}; background: transparent;"
        )

        license_info_row = QVBoxLayout()
        license_info_row.addWidget(self.license_customer_label)
        license_info_row.addWidget(self.license_balance_label)
        license_info_row.addWidget(self.license_masked_label)
        layout_license.addLayout(license_info_row)

        self.refresh_license_btn = make_secondary_btn("🔄 刷新余额")
        self.refresh_license_btn.clicked.connect(self._on_refresh_license)
        layout_license.addWidget(self.refresh_license_btn)

        self.content_layout.addWidget(card_license)

        # ============ 保存按钮 ============
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.reset_btn = make_secondary_btn("恢复默认")
        self.reset_btn.clicked.connect(self._on_reset)
        btn_row.addWidget(self.reset_btn)
        self.save_btn = make_primary_btn("💾 保存设置")
        self.save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(self.save_btn)
        btn_row.addStretch(1)
        self.content_layout.addLayout(btn_row)

    def _populate_font_families(self):
        """填充可用中文字体列表（优先常见免费商用/系统字体）。"""
        from PySide6.QtGui import QFontDatabase
        try:
            # PySide6 6.4+ 推荐使用静态方法，避免实例化 QFontDatabase
            all_families = QFontDatabase.families()
        except Exception:
            all_families = []

        preferred = [
            "Microsoft YaHei UI", "Microsoft YaHei",
            "SimHei", "SimSun", "KaiTi", "FangSong",
            "Noto Sans CJK SC", "Noto Sans SC",
            "Source Han Sans CN", "PingFang SC",
            "Segoe UI", "Arial",
        ]
        available_preferred = [f for f in preferred if f in all_families]
        self.font_family_combo.addItems(available_preferred)
        if not available_preferred and all_families:
            self.font_family_combo.addItems(all_families[:20])

    def _load_settings(self):
        """从 settings.json 加载当前配置。"""
        try:
            from gui.core.json_settings import Settings
            s = Settings()
            self._settings = s.items

            # 字体设置
            font_cfg = self._settings.get("font", {})
            family = font_cfg.get("family", "Microsoft YaHei UI")
            text_size = font_cfg.get("text_size", 9)

            idx = self.font_family_combo.findText(family)
            if idx >= 0:
                self.font_family_combo.setCurrentIndex(idx)

            self.font_size_slider.setValue(max(6, min(16, text_size)))
            self.font_size_value.setText(f"{text_size} pt")

            # 窗口大小
            startup = self._settings.get("startup_size", [1400, 720])
            self.window_width_spin.setValue(startup[0] if len(startup) > 0 else 1400)
            self.window_height_spin.setValue(startup[1] if len(startup) > 1 else 720)

            # 动画时长
            self.anim_speed_slider.setValue(self._settings.get("time_animation", 500))
            self.anim_speed_value.setText(f"{self._settings.get('time_animation', 500)} ms")

            # 自定义标题栏
            self.custom_titlebar_cb.setChecked(
                self._settings.get("custom_title_bar", True)
            )

            # 左侧菜单宽度
            left_menu = self._settings.get("lef_menu_size", {"maximum": 240})
            self.left_menu_width_spin.setValue(left_menu.get("maximum", 240))

            # 左右栏宽度
            left_col = self._settings.get("left_column_size", {"maximum": 240})
            right_col = self._settings.get("right_column_size", {"maximum": 240})
            self.left_col_width_spin.setValue(left_col.get("maximum", 240))
            self.right_col_width_spin.setValue(right_col.get("maximum", 240))

        except Exception as e:
            self.set_status(f"加载设置失败：{e}", "danger")

    def _on_save(self):
        """保存设置到 settings.json 并立即应用字体大小。"""
        try:
            from gui.core.json_settings import Settings
            s = Settings()

            # 字体大小
            pt_size = self.font_size_slider.value()
            s.items["font"]["family"] = self.font_family_combo.currentText()
            s.items["font"]["text_size"] = pt_size
            s.items["font"]["title_size"] = pt_size + 1

            # 窗口大小
            s.items["startup_size"] = [
                self.window_width_spin.value(),
                self.window_height_spin.value(),
            ]

            # 动画时长
            s.items["time_animation"] = self.anim_speed_slider.value()

            # 自定义标题栏
            s.items["custom_title_bar"] = self.custom_titlebar_cb.isChecked()

            # 左侧菜单宽度
            s.items["lef_menu_size"]["maximum"] = self.left_menu_width_spin.value()

            # 左右栏宽度
            s.items["left_column_size"]["maximum"] = self.left_col_width_spin.value()
            s.items["right_column_size"]["maximum"] = self.right_col_width_spin.value()

            s.serialize()

            # 立即应用字体大小
            self._apply_font_size(pt_size, self.font_family_combo.currentText())

            self.set_status("设置已保存，字体已立即生效。窗口/动画设置重启后生效。", "success")

        except Exception as e:
            self.set_status(f"保存失败：{e}", "danger")

    def _apply_font_size(self, pt_size: int, family: str):
        """立即应用全局字体大小（pt）。"""
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app:
            f = app.font()
            f.setFamily(family)
            f.setPointSize(pt_size)
            app.setFont(f)

    def _on_reset(self):
        """恢复默认设置。"""
        self.font_family_combo.setCurrentText("Microsoft YaHei UI")
        self.font_size_slider.setValue(9)
        self.font_size_value.setText("9 pt")
        self.window_width_spin.setValue(1400)
        self.window_height_spin.setValue(720)
        self.anim_speed_slider.setValue(500)
        self.anim_speed_value.setText("500 ms")
        self.custom_titlebar_cb.setChecked(True)
        self.left_menu_width_spin.setValue(240)
        self.left_col_width_spin.setValue(240)
        self.right_col_width_spin.setValue(240)
        self.set_status("已恢复默认值，点击保存以生效。", "info")

    def showEvent(self, event):
        """页面显示时自动加载授权信息。"""
        super().showEvent(event)
        self._load_license_info()

    def _load_license_info(self):
        """从后端获取当前授权码状态和积分余额。"""
        if hasattr(self, '_worker') and self._worker.is_running():
            return
        self._worker = ApiWorker("GET", "/license/status", params={"platform": "douyin"})
        self._worker.result_ready.connect(self._on_license_loaded)
        self._worker.start()

    def _on_license_loaded(self, data: dict):
        """处理授权信息响应。"""
        # 页面已销毁时不更新 UI（防止 showEvent → worker → 切页 → 回调崩溃）
        try:
            if not self.isVisible():
                return
        except RuntimeError:
            return
        if data.get("success") and data.get("data", {}).get("has_license"):
            info = data["data"]
            self.license_customer_label.setText(f"客户：{info.get('customer_name', '--')}")
            balance = info.get("balance_credits", 0)
            token_per = info.get("token_per_credit", 1000)
            if balance > 0:
                color = c("green")
            elif balance == 0:
                color = c("yellow")
            else:
                color = c("red")
            self.license_balance_label.setText(f"积分余额：{balance} 分（≈ {balance * token_per} tokens）")
            self.license_balance_label.setStyleSheet(
                f"color: {color}; background: transparent;"
            )
            self.license_masked_label.setText(f"授权码：{info.get('license_key_masked', '--')}")
        else:
            self.license_customer_label.setText("客户：未授权")
            self.license_balance_label.setText("积分余额：--")
            self.license_balance_label.setStyleSheet(
                f"color: {c('text_description')}; background: transparent;"
            )
            self.license_masked_label.setText("授权码：未配置")
        # 恢复刷新按钮
        self.refresh_license_btn.setText("🔄 刷新余额")
        self.refresh_license_btn.setEnabled(True)

    def _on_refresh_license(self):
        """手动刷新授权信息。"""
        self.refresh_license_btn.setText("⏳ 刷新中...")
        self.refresh_license_btn.setEnabled(False)
        self._load_license_info()
