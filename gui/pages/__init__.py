"""业务页包：11 个 PySide6 业务页。

每个页面继承 BasePage，统一深色科技风骨架。
"""
from .home_page import HomePage
from .devices_page import DevicesPage
from .search_page import SearchPage
from .functions_page import FunctionsPage
from .intent_page import IntentPage
from .message_page import MessagePage
from .process_page import ProcessPage
from .strategy_page import StrategyPage
from .monitor_page import MonitorPage
from .dashboard_page import DashboardPage
from .video_page import VideoPage

__all__ = [
    "HomePage", "DevicesPage", "SearchPage", "FunctionsPage", "IntentPage",
    "MessagePage", "ProcessPage", "StrategyPage", "MonitorPage",
    "DashboardPage", "VideoPage",
]
