"""搜索基础控制页：配置搜索行业关键词。"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QButtonGroup

from .common import (
    BasePage, api_get, ApiWorker,
    make_card_frame, make_primary_btn, make_text_edit,
    make_field_label, make_section_label, c, font,
)


# 视频排序选项：(配置值, 显示文案)
# 顺序决定按钮从左到右的排列：最新发布 在左，最多点赞 在右
SORT_OPTIONS = [
    ("latest", "最新发布"),
    ("most_liked", "最多点赞"),
]


def _sort_toggle_qss() -> str:
    """排序切换按钮 QSS：未选中 ghost 风格，选中靛蓝反色。"""
    return (
        f"QPushButton {{ background-color: transparent; color: {c('text_primary')};"
        f"  border: 1px solid {c('line_strong')}; border-radius: 6px;"
        f"  padding: 9px 22px; font-size: 13px; }}"
        f"QPushButton:hover {{ background-color: {c('bg_hover')};"
        f"  border-color: {c('context_color')}; }}"
        f"QPushButton:checked {{ background-color: {c('context_color')};"
        f"  color: {c('text_inverse')}; border-color: {c('context_color')};"
        f"  font-weight: 600; }}"
        f"QPushButton:checked:hover {{ background-color: {c('context_hover')}; }}"
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
        self._worker = None  # 防 GC
        self._sort_buttons = {}  # value -> QPushButton
        self._sort_group = QButtonGroup(self)
        self._sort_group.setExclusive(True)
        self._build_ui()
        self._load_config()

    def _build_ui(self):
        # 视频排序卡片
        sort_card, sort_layout = make_card_frame("视频排序")
        sort_layout.addWidget(make_field_label("搜索结果排序方式："))
        sort_btn_row = QHBoxLayout()
        sort_btn_row.setSpacing(10)
        sort_btn_row.addStretch(1)
        toggle_qss = _sort_toggle_qss()
        for value, label in SORT_OPTIONS:
            btn = QPushButton(label)
            btn.setFont(font(13, bold=True))
            btn.setStyleSheet(toggle_qss)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setCheckable(True)
            btn.setProperty("value", value)
            btn.setMinimumHeight(38)
            self._sort_group.addButton(btn)
            self._sort_buttons[value] = btn
            sort_btn_row.addWidget(btn)
        # 默认选中"最新发布"，加载配置时会按实际值校正
        self._sort_buttons["latest"].setChecked(True)
        sort_btn_row.addStretch(1)
        sort_layout.addLayout(sort_btn_row)
        hint = QLabel("选择「最新发布」按时间倒序；选择「最多点赞」按点赞量倒序筛选视频。")
        hint.setFont(font(11))
        hint.setStyleSheet(f"color: {c('text_tertiary')}; background: transparent;")
        hint.setWordWrap(True)
        sort_layout.addWidget(hint)
        self.content_layout.addWidget(sort_card)

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

    def _current_sort_by(self) -> str:
        """返回当前选中的排序值，默认 latest。"""
        for value, btn in self._sort_buttons.items():
            if btn.isChecked():
                return value
        return "latest"

    def _load_config(self):
        data = api_get("/config", params={"platform": "douyin"})
        if data.get("success"):
            self._config = data.get("config", {}) or {}
            kws = self._config.get("search_keywords", [])
            if isinstance(kws, list):
                self.keywords_edit.setPlainText("\n".join(kws))
            # 校正排序按钮选中状态
            sort_val = self._config.get("sort_by", "latest")
            if sort_val not in self._sort_buttons:
                sort_val = "latest"
            self._sort_buttons[sort_val].setChecked(True)
        else:
            self.set_status(f"加载配置失败：{data.get('message', '')}", "danger")

    def _on_save(self):
        keywords = [k.strip() for k in self.keywords_edit.toPlainText().split("\n") if k.strip()]
        if not keywords:
            self.set_status("请至少输入一个关键词", "warning")
            return
        # 先异步拉取最新配置，避免跨页面缓存覆写其他字段
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
        if not latest.get("search_keywords"):
            self.save_btn.setEnabled(True)
            self.set_status("服务端配置不完整（缺少 search_keywords），无法保存", "danger")
            return
        self._config = latest
        keywords = [k.strip() for k in self.keywords_edit.toPlainText().split("\n") if k.strip()]
        payload = dict(latest)
        payload["search_keywords"] = keywords
        payload["sort_by"] = self._current_sort_by()
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
