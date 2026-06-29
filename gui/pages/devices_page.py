"""AI员工管理页：管理 USB 与无线 ADB 连接，并选择本次任务控制的AI员工。"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QWidget, QTableWidgetItem, QPushButton,
)

from .common import (
    BasePage, api_get, ApiWorker, app_state,
    make_card_frame, make_primary_btn, make_secondary_btn,
    make_line_edit, make_table, make_section_label, c, font,
)


class DevicesPage(BasePage):
    """设备管理页：USB 与无线 ADB 设备连接、配对、选择控制。"""

    def __init__(self, parent=None):
        super().__init__(
            title="AI员工管理",
            subtitle="管理 USB 与无线 ADB 连接，并选择本次任务控制的AI员工。",
            parent=parent,
        )
        self._devices = []  # 后端返回的设备列表
        self._selected_devices = set()  # 选中控制的设备序列号集合
        self._worker = None  # 防 GC
        self._build_ui()
        self._load()

    def _build_ui(self):
        # ====== 卡片1：连接操作 ======
        op_card, op_layout = make_card_frame("连接操作")

        # 子区块1：立即连接
        op_layout.addWidget(make_section_label("立即连接", size=13))
        connect_row = QHBoxLayout()
        connect_row.setSpacing(10)
        self.ip_port_edit = make_line_edit(placeholder="192.168.x.x:端口")
        self.connect_btn = make_primary_btn("⚡ 立即连接")
        self.connect_btn.clicked.connect(self._on_connect)
        connect_row.addWidget(self.ip_port_edit, 3)
        connect_row.addWidget(self.connect_btn)
        op_layout.addLayout(connect_row)

        # 子区块2：配对新设备
        op_layout.addWidget(make_section_label("配对新设备", size=13))
        pair_row = QHBoxLayout()
        pair_row.setSpacing(10)
        self.pair_ip_edit = make_line_edit(placeholder="配对 IP:端口（如 192.168.x.x:port）")
        self.pair_code_edit = make_line_edit(placeholder="6位配对码")
        self.pair_code_edit.setMaxLength(6)
        self.pair_code_edit.setMaximumWidth(140)
        self.pair_btn = make_secondary_btn("🔗 立即配对")
        self.pair_btn.clicked.connect(self._on_pair)
        pair_row.addWidget(self.pair_ip_edit, 3)
        pair_row.addWidget(self.pair_code_edit, 1)
        pair_row.addWidget(self.pair_btn)
        op_layout.addLayout(pair_row)

        # USB 检测按钮
        self.usb_btn = make_secondary_btn("🔍 检测 USB 设备")
        self.usb_btn.clicked.connect(self._on_usb_detect)
        op_layout.addWidget(self.usb_btn)

        self.content_layout.addWidget(op_card)

        # ====== 卡片2：已连接设备列表 ======
        list_card, list_layout = make_card_frame("已连接设备列表")
        self.table = make_table(["序号", "序列号", "型号", "状态", "操作"], min_height=260)
        list_layout.addWidget(self.table)
        self.content_layout.addWidget(list_card)

    def _load(self):
        """加载设备列表：GET /devices，响应字段为 devices"""
        data = api_get("/devices")
        if data.get("success"):
            rows = data.get("devices", []) or []
            self._devices = rows if isinstance(rows, list) else []
            self._refresh_table()
            self.set_status(f"已加载 {len(self._devices)} 台设备", "success")
        else:
            self.set_status(f"加载失败：{data.get('message', '')}", "danger")

    def _refresh_table(self):
        """根据 self._devices 刷新表格。

        注意：后端 /api/devices 返回 list[str]（序列号字符串列表），
        不是 list[dict]。所以 dev 是字符串，model 字段无法获取（设为 "-"）。
        """
        self.table.setRowCount(len(self._devices))
        for i, dev in enumerate(self._devices):
            # dev 是字符串（设备序列号）
            if isinstance(dev, dict):
                serial = str(dev.get("serial") or dev.get("serial_no") or dev.get("id") or "")
                model = str(dev.get("model") or dev.get("device_model") or "-")
                status = str(dev.get("status") or dev.get("state") or "在线")
            else:
                serial = str(dev)
                model = "-"
                status = "在线"

            # 序号 / 序列号 / 型号 / 状态
            self.table.setItem(i, 0, QTableWidgetItem(str(i + 1)))
            self.table.setItem(i, 1, QTableWidgetItem(serial))
            self.table.setItem(i, 2, QTableWidgetItem(model))
            self.table.setItem(i, 3, QTableWidgetItem(status))

            # 操作列：选择控制 + 断开 按钮
            op_widget = QWidget()
            op_lay = QHBoxLayout(op_widget)
            op_lay.setContentsMargins(4, 2, 4, 2)
            op_lay.setSpacing(6)

            selected = serial in self._selected_devices
            select_btn = QPushButton("已选中 ✓" if selected else "选择控制")
            select_btn.setFont(font(12))
            select_btn.setCursor(Qt.PointingHandCursor)
            select_btn.setMinimumHeight(28)
            if selected:
                # 选中态：绿色背景
                select_btn.setStyleSheet(
                    f"QPushButton {{ background-color: {c('green')}; color: #FFFFFF;"
                    f"  border: none; border-radius: 4px; padding: 4px 10px; font-size: 12px; }}"
                    f"QPushButton:hover {{ background-color: #059669; }}"
                )
            else:
                # 未选中：紫蓝主色
                select_btn.setStyleSheet(
                    f"QPushButton {{ background-color: {c('context_color')}; color: #FFFFFF;"
                    f"  border: none; border-radius: 4px; padding: 4px 10px; font-size: 12px; }}"
                    f"QPushButton:hover {{ background-color: {c('context_hover')}; }}"
                    f"QPushButton:pressed {{ background-color: {c('context_pressed')}; }}"
                )
            select_btn.clicked.connect(lambda _=False, s=serial: self._on_select(s))

            disconnect_btn = QPushButton("断开")
            disconnect_btn.setFont(font(12))
            disconnect_btn.setCursor(Qt.PointingHandCursor)
            disconnect_btn.setMinimumHeight(28)
            disconnect_btn.setStyleSheet(
                f"QPushButton {{ background-color: {c('dark_three')}; color: {c('text_title')};"
                f"  border: 1px solid {c('dark_four')}; border-radius: 4px;"
                f"  padding: 4px 10px; font-size: 12px; }}"
                f"QPushButton:hover {{ background-color: {c('red')}; color: #FFFFFF; }}"
            )
            disconnect_btn.clicked.connect(lambda _=False, s=serial: self._on_disconnect(s))

            op_lay.addWidget(select_btn)
            op_lay.addWidget(disconnect_btn)
            op_lay.addStretch(1)

            self.table.setCellWidget(i, 4, op_widget)

    def _on_select(self, serial: str):
        """切换设备选中状态，并同步到全局 AppState 供其它页面读取。"""
        if serial in self._selected_devices:
            self._selected_devices.discard(serial)
            app_state().remove_device(serial)
            self.set_status(f"已取消选中：{serial}", "info")
        else:
            self._selected_devices.add(serial)
            app_state().add_device(serial)
            self.set_status(f"已选中控制设备：{serial}", "success")
        self._refresh_table()

    def _on_connect(self):
        """立即连接：POST /devices/connect body={ip_port}"""
        ip_port = self.ip_port_edit.text().strip()
        if not ip_port:
            self.set_status("请输入 IP:端口", "warning")
            return
        self.connect_btn.setEnabled(False)
        self.set_status("正在连接...", "info")
        worker = ApiWorker("POST", "/devices/connect", json_body={"ip_port": ip_port})
        worker.result_ready.connect(self._on_action_done)
        worker.start()
        self._worker = worker  # 防 GC

    def _on_pair(self):
        """配对：POST /devices/pair body={ip_port, code}"""
        pair_ip = self.pair_ip_edit.text().strip()
        pair_code = self.pair_code_edit.text().strip()
        if not pair_ip or not pair_code:
            self.set_status("请输入配对 IP 与 6 位配对码", "warning")
            return
        self.pair_btn.setEnabled(False)
        self.set_status("正在配对...", "info")
        worker = ApiWorker("POST", "/devices/pair",
                          json_body={"ip_port": pair_ip, "code": pair_code})
        worker.result_ready.connect(self._on_action_done)
        worker.start()
        self._worker = worker  # 防 GC

    def _on_usb_detect(self):
        """USB 检测：POST /devices/usb/detect"""
        self.usb_btn.setEnabled(False)
        self.set_status("正在检测 USB 设备...", "info")
        worker = ApiWorker("POST", "/devices/usb/detect")
        worker.result_ready.connect(self._on_action_done)
        worker.start()
        self._worker = worker  # 防 GC

    def _on_disconnect(self, serial: str):
        """断开：POST /devices/disconnect body={ip_port}（值为设备序列号）"""
        self.set_status(f"正在断开 {serial} ...", "info")
        worker = ApiWorker("POST", "/devices/disconnect",
                          json_body={"ip_port": serial})
        worker.result_ready.connect(self._on_action_done)
        worker.start()
        self._worker = worker  # 防 GC

    def _on_action_done(self, data: dict):
        """通用操作完成回调：恢复按钮 + 重新加载设备列表。"""
        self.connect_btn.setEnabled(True)
        self.pair_btn.setEnabled(True)
        self.usb_btn.setEnabled(True)
        if data.get("success"):
            self.set_status(f"操作成功：{data.get('message', '已完成')}", "success")
            self._load()  # 刷新设备列表
        else:
            self.set_status(f"失败：{data.get('message', '')}", "danger")
