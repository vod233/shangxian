"""员工操作速度与数量调节页：配置视频处理数量与页面停留时长。"""
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout

from .common import (
    BasePage, api_get, ApiWorker,
    make_card_frame, make_primary_btn, make_spinbox,
    make_field_label, c,
)


class VideoPage(BasePage):
    """员工操作速度与数量调节页。"""

    def __init__(self, parent=None):
        super().__init__(
            title="员工操作速度与数量调节",
            subtitle="控制AI员工处理视频数量与页面停留时长。",
            parent=parent,
        )
        self._config = {}
        self._build_ui()
        self._load_config()

    def _build_ui(self):
        # 速度与数量卡片
        card, card_layout = make_card_frame("速度与数量")
        # 2x2 网格：QHBoxLayout 套两个 QVBoxLayout
        grid_row = QHBoxLayout()
        col_left = QVBoxLayout()
        col_right = QVBoxLayout()

        # 左列：每日上限、每关键词上限
        col_left.addWidget(make_field_label("每日上限（条）："))
        self.max_daily_spin = make_spinbox(min_val=1, max_val=9999, default=100)
        col_left.addWidget(self.max_daily_spin)

        col_left.addWidget(make_field_label("每关键词上限（条）："))
        self.max_per_keyword_spin = make_spinbox(min_val=1, max_val=9999, default=5)
        col_left.addWidget(self.max_per_keyword_spin)

        # 右列：最小停留、最大停留
        col_right.addWidget(make_field_label("最小停留（秒）："))
        self.min_stay_spin = make_spinbox(min_val=1, max_val=9999, default=3)
        col_right.addWidget(self.min_stay_spin)

        col_right.addWidget(make_field_label("最大停留（秒）："))
        self.max_stay_spin = make_spinbox(min_val=1, max_val=9999, default=6)
        col_right.addWidget(self.max_stay_spin)

        grid_row.addLayout(col_left)
        grid_row.addLayout(col_right)
        card_layout.addLayout(grid_row)
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
            # 读取 4 个数值字段
            mdv = self._config.get("max_daily_videos")
            if isinstance(mdv, (int, float)) and not isinstance(mdv, bool):
                self.max_daily_spin.setValue(int(mdv))
            mvk = self._config.get("max_videos_per_keyword")
            if isinstance(mvk, (int, float)) and not isinstance(mvk, bool):
                self.max_per_keyword_spin.setValue(int(mvk))
            mns = self._config.get("min_video_stay")
            if isinstance(mns, (int, float)) and not isinstance(mns, bool):
                self.min_stay_spin.setValue(int(mns))
            mxs = self._config.get("max_video_stay")
            if isinstance(mxs, (int, float)) and not isinstance(mxs, bool):
                self.max_stay_spin.setValue(int(mxs))
        else:
            self.set_status(f"加载配置失败：{data.get('message', '')}", "danger")

    def _on_save(self):
        payload = dict(self._config)
        payload["max_daily_videos"] = self.max_daily_spin.value()
        payload["max_videos_per_keyword"] = self.max_per_keyword_spin.value()
        payload["min_video_stay"] = self.min_stay_spin.value()
        payload["max_video_stay"] = self.max_stay_spin.value()
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
