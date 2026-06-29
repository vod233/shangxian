# ///////////////////////////////////////////////////////////////
#
# BY: WANDERSON M.PIMENTA
# PROJECT MADE WITH: Qt Designer and PySide6
# V: 1.0.0
#
# This project can be used freely for all uses, as long as they maintain the
# respective credits only in the Python scripts, any information in the visual
# interface (GUI) can be modified without any implication.
#
# There are limitations on Qt licenses if you want to use your products
# commercially, I recommend reading them on the official website:
# https://doc.qt.io/qtforpython/licenses.html
#
# ///////////////////////////////////////////////////////////////

# IMPORT PACKAGES AND MODULES
# ///////////////////////////////////////////////////////////////
from gui.uis.windows.main_window.functions_main_window import *
import sys
import os

# IMPORT QT CORE
# ///////////////////////////////////////////////////////////////
from qt_core import *

# IMPORT SETTINGS
# ///////////////////////////////////////////////////////////////
from gui.core.json_settings import Settings

# IMPORT PY ONE DARK WINDOWS
# ///////////////////////////////////////////////////////////////
# MAIN WINDOW
from gui.uis.windows.main_window import *

# IMPORT PY ONE DARK WIDGETS
# ///////////////////////////////////////////////////////////////
from gui.widgets import *

# IMPORT ACCOUNT LOGIN
# ///////////////////////////////////////////////////////////////
from gui.auth_dialog import require_login

# ADJUST QT FONT DPI FOR HIGHT SCALE AN 4K MONITOR
# ///////////////////////////////////////////////////////////////
os.environ["QT_FONT_DPI"] = "96"
# IF IS 4K MONITOR ENABLE 'os.environ["QT_SCALE_FACTOR"] = "2"'

# MAIN WINDOW
# ///////////////////////////////////////////////////////////////
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        # SETUP MAIN WINDOw
        # Load widgets from "gui\uis\main_window\ui_main.py"
        # ///////////////////////////////////////////////////////////////
        self.ui = UI_MainWindow()
        self.ui.setup_ui(self)

        # LOAD SETTINGS
        # ///////////////////////////////////////////////////////////////
        settings = Settings()
        self.settings = settings.items

        # SETUP MAIN WINDOW
        # ///////////////////////////////////////////////////////////////
        self.hide_grips = True # Show/Hide resize grips
        SetupMainWindow.setup_gui(self)

        # SHOW MAIN WINDOW
        # ///////////////////////////////////////////////////////////////
        self.show()

    # LEFT MENU BTN IS CLICKED
    # 11 个业务页路由：根据 btn_id 切换 QStackedWidget 页面
    # ///////////////////////////////////////////////////////////////
    def btn_clicked(self):
        btn = SetupMainWindow.setup_btns(self)

        # 非设置类按钮：取消左栏选中态
        if btn.objectName() != "btn_settings":
            self.ui.left_menu.deselect_all_tab()

        # 取消标题栏设置按钮 active
        top_settings = MainFunctions.get_title_bar_btn(self, "btn_top_settings")
        top_settings.set_active(False)

        # 11 个业务页路由映射：btn_id → page_N
        page_map = {
            "btn_home": self.ui.load_pages.page_1,
            "btn_devices": self.ui.load_pages.page_2,
            "btn_search": self.ui.load_pages.page_3,
            "btn_functions": self.ui.load_pages.page_4,
            "btn_intent": self.ui.load_pages.page_5,
            "btn_message": self.ui.load_pages.page_6,
            "btn_process": self.ui.load_pages.page_7,
            "btn_strategy": self.ui.load_pages.page_8,
            "btn_monitor": self.ui.load_pages.page_9,
            "btn_dashboard": self.ui.load_pages.page_10,
            "btn_video": self.ui.load_pages.page_11,
        }

        if btn.objectName() in page_map:
            # 高亮当前菜单
            self.ui.left_menu.select_only_one(btn.objectName())
            # 切换页面
            MainFunctions.set_page(self, page_map[btn.objectName()])
            print(f"切换到页面：{btn.objectName()}")
            return

        # 设置按钮（左栏切换）
        if btn.objectName() == "btn_settings" or btn.objectName() == "btn_close_left_column":
            if not MainFunctions.left_column_is_visible(self):
                MainFunctions.toggle_left_column(self)
                self.ui.left_menu.select_only_one_tab(btn.objectName())
            else:
                if btn.objectName() == "btn_close_left_column":
                    self.ui.left_menu.deselect_all_tab()
                    MainFunctions.toggle_left_column(self)
                self.ui.left_menu.select_only_one_tab(btn.objectName())

            if btn.objectName() != "btn_close_left_column":
                MainFunctions.set_left_column_menu(
                    self,
                    menu=self.ui.left_column.menus.menu_1,
                    title="设置",
                    icon_path=Functions.set_svg_icon("icon_settings.svg")
                )

        # 标题栏顶部设置按钮（右栏切换）
        if btn.objectName() == "btn_top_settings":
            if not MainFunctions.right_column_is_visible(self):
                btn.set_active(True)
                MainFunctions.toggle_right_column(self)
            else:
                btn.set_active(False)
                MainFunctions.toggle_right_column(self)

            top_settings = MainFunctions.get_left_menu_btn(self, "btn_settings")
            top_settings.set_active_tab(False)

    # LEFT MENU BTN IS RELEASED
    # Run function when btn is released
    # Check funtion by object name / btn_id
    # ///////////////////////////////////////////////////////////////
    def btn_released(self):
        # GET BT CLICKED
        btn = SetupMainWindow.setup_btns(self)

        # DEBUG
        print(f"Button {btn.objectName()}, released!")

    # RESIZE EVENT
    # ///////////////////////////////////////////////////////////////
    def resizeEvent(self, event):
        SetupMainWindow.resize_grips(self)

    # MOUSE CLICK EVENTS
    # ///////////////////////////////////////////////////////////////
    def mousePressEvent(self, event):
        # SET DRAG POS WINDOW
        self.dragPos = event.globalPos()


# SETTINGS WHEN TO START
# Set the initial class and also additional parameters of the "QApplication" class
# ///////////////////////////////////////////////////////////////
def run_main_window(account_email: str = ""):
    """启动 PySide6 主窗口（阻塞直到窗口关闭）。
    供 launcher 调用，account_email 用于侧边栏显示。
    """
    app = QApplication.instance() or QApplication(sys.argv)
    if os.path.exists("icon.ico"):
        app.setWindowIcon(QIcon("icon.ico"))

    window = MainWindow()
    window.account_email = account_email  # 供侧边栏显示

    # 标题栏深色模式
    try:
        import ctypes
        from ctypes import c_int, byref, sizeof
        dwmapi = ctypes.windll.dwmapi
        value = c_int(1)
        hwnd = int(window.winId())
        for attr in (20, 19):
            if dwmapi.DwmSetWindowAttribute(hwnd, attr, byref(value), sizeof(value)) == 0:
                break
    except Exception:
        pass

    return app.exec()


if __name__ == "__main__":
    # 登录拦截：未登录则不显示主窗口
    logged_in, account_email = require_login()
    if not logged_in:
        sys.exit(0)
    sys.exit(run_main_window(account_email))