"""流程控制页：开始/暂停/继续/结束任务。

P1修复：_load() 改为异步（ApiWorker），消除 GUI 线程同步阻塞。
P2修复：_on_action_done 回调中置 None 释放旧 worker 引用。
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel

from .common import (
    BasePage, ApiWorker, app_state,
    make_card_frame, make_primary_btn, make_secondary_btn, make_danger_btn,
    make_metric_card, c,
)


class ProcessPage(BasePage):
    """流程控制页：任务状态展示与控制。"""

    def __init__(self, parent=None):
        super().__init__(
            title="🚀 流程控制",
            subtitle="确保配置保存完毕且已选中AI员工后，可在此开始、暂停、继续或结束任务。",
            parent=parent,
        )
        self._action_worker = None   # 动作请求 worker（POST start/pause/stop）
        self._status_worker = None   # 状态查询 worker（GET tasks/status）
        self._build_ui()
        self._load()  # 异步加载，不阻塞

    def _build_ui(self):
        # ====== 卡片1：当前状态 ======
        status_card, status_layout = make_card_frame("当前状态")
        metric_row = QHBoxLayout()
        metric_row.setSpacing(16)
        # 已选设备数
        self.selected_metric = make_metric_card("0", "已选设备数")
        # 任务状态
        self.status_metric = make_metric_card("未知", "任务状态")
        metric_row.addWidget(self.selected_metric, 1)
        metric_row.addWidget(self.status_metric, 1)
        status_layout.addLayout(metric_row)
        self.content_layout.addWidget(status_card)

        # ====== 卡片2：任务控制 ======
        ctrl_card, ctrl_layout = make_card_frame("任务控制")
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)

        self.start_btn = make_primary_btn("🚀 开始任务")
        self.start_btn.clicked.connect(lambda: self._do_action("/tasks/start"))
        btn_row.addWidget(self.start_btn)

        self.pause_btn = make_secondary_btn("⏸️ 暂停任务")
        self.pause_btn.clicked.connect(lambda: self._do_action("/tasks/pause"))
        btn_row.addWidget(self.pause_btn)

        self.resume_btn = make_secondary_btn("▶️ 继续任务")
        self.resume_btn.clicked.connect(lambda: self._do_action("/tasks/resume"))
        btn_row.addWidget(self.resume_btn)

        self.stop_btn = make_danger_btn("● 结束任务")
        self.stop_btn.clicked.connect(lambda: self._do_action("/tasks/stop"))
        btn_row.addWidget(self.stop_btn)

        ctrl_layout.addLayout(btn_row)
        self.content_layout.addWidget(ctrl_card)

    def _load(self):
        """异步加载任务状态：GET /tasks/status。

        P1修复：原同步 api_get 会阻塞 GUI 线程最长 10 秒，
        改为 ApiWorker 后台请求，回调中更新 UI。
        """
        # 重入保护：上一次状态查询仍在运行时跳过
        if self._status_worker is not None:
            try:
                if self._status_worker.isRunning():
                    return
            except RuntimeError:
                pass
        worker = ApiWorker("GET", "/tasks/status")
        worker.finished.connect(self._on_status_loaded)
        worker.start()
        self._status_worker = worker  # 防 GC

    def _on_status_loaded(self, data: dict):
        """状态查询完成回调（GUI 线程执行）。"""
        self._status_worker = None  # 释放引用
        if data.get("success"):
            status_dict = data.get("status", {}) or {}
            # 已选设备数取自跨页面共享状态 AppState
            selected = app_state().selected_devices
            self._update_metric(self.selected_metric,
                                str(len(selected)), "已选设备数")

            # status 是 dict {serial: {status: "running", ...}}，遍历统计汇总
            if not status_dict:
                self._update_metric(self.status_metric, "空闲", "任务状态",
                                    color=self._status_color("空闲"))
            else:
                # 统计各状态出现次数
                status_counts = {}
                for serial, info in status_dict.items():
                    if not isinstance(info, dict):
                        continue
                    st = str(info.get("status")
                             or info.get("task_status") or "未知")
                    status_counts[st] = status_counts.get(st, 0) + 1
                # 汇总显示，如 "running×2 / pause×1"
                summary_text = " / ".join(
                    f"{st}×{cnt}" for st, cnt in status_counts.items()
                )
                # 主状态取数量最多的，用于决定配色
                main_status = max(status_counts.items(), key=lambda x: x[1])[0]
                self._update_metric(self.status_metric, summary_text, "任务状态",
                                    color=self._status_color(main_status))
        else:
            self._update_metric(self.status_metric, "—", "任务状态",
                                color=c("context_color"))

    def _update_metric(self, frame, value: str, label: str, color: str = None):
        """更新指标卡内容。"""
        layout = frame.layout()
        if layout is None or layout.count() < 2:
            return
        v_item = layout.itemAt(0)
        l_item = layout.itemAt(1)
        if not v_item or not l_item:
            return
        v_widget = v_item.widget()
        l_widget = l_item.widget()
        if not isinstance(v_widget, QLabel) or not isinstance(l_widget, QLabel):
            return
        v_widget.setText(value)
        if color:
            v_widget.setStyleSheet(f"color: {color}; background: transparent;")
        l_widget.setText(label)

    def _status_color(self, status: str) -> str:
        """根据任务状态返回配色。"""
        s = status.lower()
        if "运行" in status or "run" in s or "进行" in status:
            return c("green")
        if "暂停" in status or "pause" in s:
            return c("yellow")
        if "结束" in status or "stop" in s or "完成" in status:
            return c("red")
        return c("context_color")

    def _do_action(self, path: str):
        """触发任务控制：POST {path} body={devices, platform}"""
        selected = app_state().selected_devices
        if not selected:
            self.set_status("请先在AI员工管理页选择控制设备", "warning")
            return
        # 重入保护：上一个动作请求仍在运行时忽略
        if self._action_worker is not None:
            try:
                if self._action_worker.isRunning():
                    return
            except RuntimeError:
                pass
        self._set_buttons_enabled(False)
        action = path.split("/")[-1]
        self.set_status(f"正在执行 {action} ...", "info")
        payload = {"devices": selected, "platform": "douyin"}
        worker = ApiWorker("POST", path, json_body=payload)
        worker.finished.connect(self._on_action_done)
        worker.start()
        self._action_worker = worker  # 防 GC

    def _on_action_done(self, data: dict):
        """动作请求完成回调（GUI 线程执行）。

        P1修复：不再调用同步 _load()，改为异步 _load()。
        P2修复：释放旧 worker 引用。
        """
        self._action_worker = None  # 释放引用
        self._set_buttons_enabled(True)
        if data.get("success"):
            self.set_status(f"操作成功：{data.get('message', '已完成')}", "success")
            self._load()  # 异步刷新状态，不阻塞 GUI
        else:
            self.set_status(f"失败：{data.get('message', '')}", "danger")

    def _set_buttons_enabled(self, enabled: bool):
        self.start_btn.setEnabled(enabled)
        self.pause_btn.setEnabled(enabled)
        self.resume_btn.setEnabled(enabled)
        self.stop_btn.setEnabled(enabled)
