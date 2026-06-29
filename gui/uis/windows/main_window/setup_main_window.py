# ///////////////////////////////////////////////////////////////
#
# 抖音AI群控 - 主窗口装配器
# 11 个业务页菜单按钮 + 11 个业务页 widget 实例化
#
# ///////////////////////////////////////////////////////////////

from . functions_main_window import *
import sys
import os

# IMPORT QT CORE
# ///////////////////////////////////////////////////////////////
from qt_core import *

# IMPORT SETTINGS / THEME
# ///////////////////////////////////////////////////////////////
from gui.core.json_settings import Settings
from gui.core.json_themes import Themes

# IMPORT PY ONE DARK WIDGETS
# ///////////////////////////////////////////////////////////////
from gui.widgets import *

# IMPORT BUSINESS PAGES
# ///////////////////////////////////////////////////////////////
from gui.pages import (
    HomePage, DevicesPage, SearchPage, FunctionsPage, IntentPage,
    MessagePage, ProcessPage, StrategyPage, MonitorPage,
    DashboardPage, VideoPage, SettingsPage,
)

# LOAD UI MAIN
# ///////////////////////////////////////////////////////////////
from . ui_main import *


class SetupMainWindow:
    def __init__(self):
        super().__init__()
        self.ui = UI_MainWindow()
        self.ui.setup_ui(self)

    # 左侧菜单按钮配置（11 个业务页）
    # show_top=True 放顶部区，show_top=False 放底部区（自动加分隔线）
    add_left_menus = [
        {
            "btn_icon": "icon_home.svg",
            "btn_id": "btn_home",
            "btn_text": "首页",
            "btn_tooltip": "AI运营员工群控台",
            "show_top": True,
            "is_active": True
        },
        {
            "btn_icon": "icon_add_user.svg",
            "btn_id": "btn_devices",
            "btn_text": "AI员工群控管理",
            "btn_tooltip": "管理 USB 与无线 ADB 设备",
            "show_top": True,
            "is_active": False
        },
        {
            "btn_icon": "icon_search.svg",
            "btn_id": "btn_search",
            "btn_text": "AI搜索控制大模型",
            "btn_tooltip": "配置搜索行业关键词",
            "show_top": True,
            "is_active": False
        },
        {
            "btn_icon": "icon_widgets.svg",
            "btn_id": "btn_functions",
            "btn_text": "AI功能自主选项",
            "btn_tooltip": "勾选执行功能与策略",
            "show_top": True,
            "is_active": False
        },
        {
            "btn_icon": "icon_emoticons.svg",
            "btn_id": "btn_intent",
            "btn_text": "AI深度挖掘客户",
            "btn_tooltip": "意向关键词与AI人格",
            "show_top": True,
            "is_active": False
        },
        {
            "btn_icon": "icon_send.svg",
            "btn_id": "btn_message",
            "btn_text": "AI员工话术私信调整",
            "btn_tooltip": "作者私信与评论区私信话术",
            "show_top": True,
            "is_active": False
        },
        {
            "btn_icon": "icon_busy.svg",
            "btn_id": "btn_process",
            "btn_text": "AI一键控制开关",
            "btn_tooltip": "开始/暂停/继续/结束任务",
            "show_top": True,
            "is_active": False
        },
        {
            "btn_icon": "icon_more_options.svg",
            "btn_id": "btn_strategy",
            "btn_text": "AI员工工作调整台",
            "btn_tooltip": "AI截流获客策略与模型参数",
            "show_top": True,
            "is_active": False
        },
        {
            "btn_icon": "icon_online.svg",
            "btn_id": "btn_monitor",
            "btn_text": "AI员工工作动向",
            "btn_tooltip": "实时任务监控与终端日志",
            "show_top": True,
            "is_active": False
        },
        {
            "btn_icon": "icon_info.svg",
            "btn_id": "btn_dashboard",
            "btn_text": "AI获客面板员工走向",
            "btn_tooltip": "获客数据看板与详细记录",
            "show_top": True,
            "is_active": False
        },
        {
            "btn_icon": "icon_settings.svg",
            "btn_id": "btn_video",
            "btn_text": "视频处理设置",
            "btn_tooltip": "处理数量与停留时长",
            "show_top": True,
            "is_active": False
        },
        {
            "btn_icon": "icon_settings.svg",
            "btn_id": "btn_settings",
            "btn_text": "系统设置",
            "btn_tooltip": "字体、窗口、界面外观设置",
            "show_top": False,
            "is_active": False
        },
    ]

    # 标题栏额外按钮
    add_title_bar_menus = [
        {
            "btn_icon": "icon_search.svg",
            "btn_id": "btn_search_top",
            "btn_tooltip": "搜索",
            "is_active": False
        },
        {
            "btn_icon": "icon_settings.svg",
            "btn_id": "btn_top_settings",
            "btn_tooltip": "顶部设置",
            "is_active": False
        }
    ]

    # 按钮信号来源判定
    def setup_btns(self):
        if self.ui.title_bar.sender() != None:
            return self.ui.title_bar.sender()
        elif self.ui.left_menu.sender() != None:
            return self.ui.left_menu.sender()
        elif self.ui.left_column.sender() != None:
            return self.ui.left_column.sender()

    # 主窗口装配
    def setup_gui(self):
        # APP TITLE
        self.setWindowTitle(self.settings["app_name"])

        # 无边框 + 透明背景
        if self.settings["custom_title_bar"]:
            self.setWindowFlag(Qt.FramelessWindowHint)
            self.setAttribute(Qt.WA_TranslucentBackground)

        # 8 方向缩放手柄
        if self.settings["custom_title_bar"]:
            self.left_grip = PyGrips(self, "left", self.hide_grips)
            self.right_grip = PyGrips(self, "right", self.hide_grips)
            self.top_grip = PyGrips(self, "top", self.hide_grips)
            self.bottom_grip = PyGrips(self, "bottom", self.hide_grips)
            self.top_left_grip = PyGrips(self, "top_left", self.hide_grips)
            self.top_right_grip = PyGrips(self, "top_right", self.hide_grips)
            self.bottom_left_grip = PyGrips(self, "bottom_left", self.hide_grips)
            self.bottom_right_grip = PyGrips(self, "bottom_right", self.hide_grips)

        # 左侧菜单
        self.ui.left_menu.add_menus(SetupMainWindow.add_left_menus)
        self.ui.left_menu.clicked.connect(self.btn_clicked)
        self.ui.left_menu.released.connect(self.btn_released)

        # 标题栏
        self.ui.title_bar.add_menus(SetupMainWindow.add_title_bar_menus)
        self.ui.title_bar.clicked.connect(self.btn_clicked)
        self.ui.title_bar.released.connect(self.btn_released)
        if self.settings["custom_title_bar"]:
            self.ui.title_bar.set_title(self.settings["app_name"])
        else:
            self.ui.title_bar.set_title("抖音AI群控")

        # 左栏信号
        self.ui.left_column.clicked.connect(self.btn_clicked)
        self.ui.left_column.released.connect(self.btn_released)

        # 初始页面 = 首页
        MainFunctions.set_page(self, self.ui.load_pages.page_1)
        MainFunctions.set_left_column_menu(
            self,
            menu=self.ui.left_column.menus.menu_1,
            title="设置",
            icon_path=Functions.set_svg_icon("icon_settings.svg")
        )
        MainFunctions.set_right_column_menu(self, self.ui.right_column.menu_1)

        # 加载设置与主题
        settings = Settings()
        self.settings = settings.items
        themes = Themes()
        self.themes = themes.items

        # 左栏按钮（保留 PyOneDark 示例，可后续替换）
        self.left_btn_1 = PyPushButton(
            text="Btn 1",
            radius=8,
            color=self.themes["app_color"]["text_foreground"],
            bg_color=self.themes["app_color"]["dark_one"],
            bg_color_hover=self.themes["app_color"]["dark_three"],
            bg_color_pressed=self.themes["app_color"]["dark_four"]
        )
        self.left_btn_1.setMaximumHeight(40)
        self.ui.left_column.menus.btn_1_layout.addWidget(self.left_btn_1)

        self.left_btn_2 = PyPushButton(
            text="Btn With Icon",
            radius=8,
            color=self.themes["app_color"]["text_foreground"],
            bg_color=self.themes["app_color"]["dark_one"],
            bg_color_hover=self.themes["app_color"]["dark_three"],
            bg_color_pressed=self.themes["app_color"]["dark_four"]
        )
        self.icon = QIcon(Functions.set_svg_icon("icon_settings.svg"))
        self.left_btn_2.setIcon(self.icon)
        self.left_btn_2.setMaximumHeight(40)
        self.ui.left_column.menus.btn_2_layout.addWidget(self.left_btn_2)

        self.left_btn_3 = QPushButton("Default QPushButton")
        self.left_btn_3.setMaximumHeight(40)
        self.ui.left_column.menus.btn_3_layout.addWidget(self.left_btn_3)

        # ======================== 11 个业务页实例化 ========================
        # 每个业务页 widget 注入到对应的 page_X_layout
        self.page_home = HomePage()
        self.ui.load_pages.page_1_layout.addWidget(self.page_home)

        self.page_devices = DevicesPage()
        self.ui.load_pages.page_2_layout.addWidget(self.page_devices)

        self.page_search = SearchPage()
        self.ui.load_pages.page_3_layout.addWidget(self.page_search)

        self.page_functions = FunctionsPage()
        self.ui.load_pages.page_4_layout.addWidget(self.page_functions)

        self.page_intent = IntentPage()
        self.ui.load_pages.page_5_layout.addWidget(self.page_intent)

        self.page_message = MessagePage()
        self.ui.load_pages.page_6_layout.addWidget(self.page_message)

        self.page_process = ProcessPage()
        self.ui.load_pages.page_7_layout.addWidget(self.page_process)

        self.page_strategy = StrategyPage()
        self.ui.load_pages.page_8_layout.addWidget(self.page_strategy)

        self.page_monitor = MonitorPage()
        self.ui.load_pages.page_9_layout.addWidget(self.page_monitor)

        self.page_dashboard = DashboardPage()
        self.ui.load_pages.page_10_layout.addWidget(self.page_dashboard)

        self.page_video = VideoPage()
        self.ui.load_pages.page_11_layout.addWidget(self.page_video)

        self.page_settings = SettingsPage()
        self.ui.load_pages.page_12_layout.addWidget(self.page_settings)

        # 右栏按钮（保留示例）
        self.right_btn_1 = PyPushButton(
            text="Show Menu 2",
            radius=8,
            color=self.themes["app_color"]["text_foreground"],
            bg_color=self.themes["app_color"]["dark_one"],
            bg_color_hover=self.themes["app_color"]["dark_three"],
            bg_color_pressed=self.themes["app_color"]["dark_four"]
        )
        self.icon_right = QIcon(Functions.set_svg_icon("icon_arrow_right.svg"))
        self.right_btn_1.setIcon(self.icon_right)
        self.right_btn_1.setMaximumHeight(40)
        self.right_btn_1.clicked.connect(lambda: MainFunctions.set_right_column_menu(
            self, self.ui.right_column.menu_2
        ))
        self.ui.right_column.btn_1_layout.addWidget(self.right_btn_1)

        self.right_btn_2 = PyPushButton(
            text="Show Menu 1",
            radius=8,
            color=self.themes["app_color"]["text_foreground"],
            bg_color=self.themes["app_color"]["dark_one"],
            bg_color_hover=self.themes["app_color"]["dark_three"],
            bg_color_pressed=self.themes["app_color"]["dark_four"]
        )
        self.icon_left = QIcon(Functions.set_svg_icon("icon_arrow_left.svg"))
        self.right_btn_2.setIcon(self.icon_left)
        self.right_btn_2.setMaximumHeight(40)
        self.right_btn_2.clicked.connect(lambda: MainFunctions.set_right_column_menu(
            self, self.ui.right_column.menu_1
        ))
        self.ui.right_column.btn_2_layout.addWidget(self.right_btn_2)

    # 缩放手柄位置更新
    def resize_grips(self):
        if self.settings["custom_title_bar"]:
            self.left_grip.setGeometry(5, 10, 10, self.height())
            self.right_grip.setGeometry(self.width() - 15, 10, 10, self.height())
            self.top_grip.setGeometry(5, 5, self.width() - 10, 10)
            self.bottom_grip.setGeometry(5, self.height() - 15, self.width() - 10, 10)
            self.top_right_grip.setGeometry(self.width() - 20, 5, 15, 15)
            self.bottom_left_grip.setGeometry(5, self.height() - 20, 15, 15)
            self.bottom_right_grip.setGeometry(self.width() - 20, self.height() - 20, 15, 15)
