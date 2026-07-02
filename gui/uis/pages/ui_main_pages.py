# ///////////////////////////////////////////////////////////////
#
# 抖音AI群控 - PySide6 业务页装载器
# 11 个页面容器（QStackedWidget），具体业务 widget 由
# setup_main_window.py 在 setup_gui() 末尾实例化并 addWidget
#
# ///////////////////////////////////////////////////////////////

from qt_core import *


class Ui_MainPages(object):
    """12 个业务页的 QStackedWidget 容器。

    每个页是一个空的 QWidget，业务 widget 在 setup_main_window.py
    中通过 self.ui.load_pages.page_X_layout.addWidget(...) 注入。
    """

    def setupUi(self, MainPages):
        if not MainPages.objectName():
            MainPages.setObjectName(u"MainPages")
        MainPages.resize(860, 600)

        self.main_pages_layout = QVBoxLayout(MainPages)
        self.main_pages_layout.setSpacing(0)
        self.main_pages_layout.setObjectName(u"main_pages_layout")
        self.main_pages_layout.setContentsMargins(0, 0, 0, 0)

        self.pages = QStackedWidget(MainPages)
        self.pages.setObjectName(u"pages")

        # 12 个页面容器：page_1 ~ page_12
        # 每个页面提供一个 QVBoxLayout 供业务 widget 注入
        self.page_names = [
            "page_home",        # 1. 首页
            "page_devices",     # 2. AI员工群控管理
            "page_search",      # 3. AI搜索控制大模型
            "page_functions",   # 4. AI功能自主选项
            "page_intent",      # 5. AI深度挖掘客户
            "page_message",     # 6. AI员工话术私信调整
            "page_process",     # 7. AI一键控制开关
            "page_strategy",    # 8. AI员工工作调整台
            "page_monitor",     # 9. AI员工工作动向
            "page_dashboard",   # 10. AI获客面板员工走向
            "page_video",       # 11. 视频处理设置
            "page_settings",    # 12. 系统设置
        ]

        # 为每个页面创建 QWidget + QVBoxLayout，存为属性 page_1..page_12
        for idx, name in enumerate(self.page_names, start=1):
            page = QWidget()
            page.setObjectName(name)
            page.setStyleSheet("background: transparent;")
            layout = QVBoxLayout(page)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)
            # 属性名：page_1_layout, page_2_layout, ...
            setattr(self, f"page_{idx}", page)
            setattr(self, f"page_{idx}_layout", layout)
            self.pages.addWidget(page)

        self.main_pages_layout.addWidget(self.pages)
        self.pages.setCurrentIndex(0)

        QMetaObject.connectSlotsByName(MainPages)
