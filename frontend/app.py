import os
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

_np = os.environ.get("NO_PROXY", "")
if "127.0.0.1" not in _np:
    os.environ["NO_PROXY"] = (_np + "," if _np else "") + "127.0.0.1"
    os.environ["no_proxy"] = os.environ["NO_PROXY"]

import streamlit as st
import requests
from douyin.douyin_app import render_douyin_page

st.set_page_config(page_title="抖音自动化群控系统", page_icon="🎵", layout="wide")

API_BASE_URL = "http://127.0.0.1:8000/api"


def get_device_status():
    try:
        resp = requests.get(f"{API_BASE_URL}/devices", timeout=5)
        if resp.status_code == 200:
            devices = resp.json().get("devices", [])
            if devices:
                return {"connected": True, "count": len(devices), "first_device": devices[0]}
        return {"connected": False, "count": 0, "first_device": None}
    except:
        return {"connected": False, "count": 0, "first_device": None}


def get_license_status():
    try:
        resp = requests.get(f"{API_BASE_URL}/config?platform=douyin", timeout=5)
        if resp.status_code == 200:
            config = resp.json().get("config", {})
            ai_enabled = config.get("ai_enabled", False)
            has_license = config.get("has_license_key", False)
            return {"ai_enabled": ai_enabled, "license_valid": has_license}
    except:
        pass
    return {"ai_enabled": False, "license_valid": False}


def main():
    device_status = get_device_status()
    license_info = get_license_status()
    current_device = device_status.get("first_device", "未连接")

    st.markdown("""
    <style>
        :root {
            --primary: #6366F1;
            --primary-hover: #818CF8;
            --primary-active: #4F46E5;
            --primary-ring: rgba(99, 102, 241, 0.2);
            --success: #10B981;
            --warning: #F59E0B;
            --error: #EF4444;
            --sidebar-bg: #0A0B0F;
            --sidebar-hover: #151823;
            --sidebar-active: #6366F1;
            --sidebar-text: #D1D5DB;
            --sidebar-muted: #6B7280;
            --sidebar-border: rgba(255,255,255,0.06);
            --main-bg: #0D1117;
            --card-bg: #161B28;
            --card-border: rgba(255,255,255,0.06);
            --card-shadow: 0 1px 3px rgba(0,0,0,0.3);
            --text-primary: #E5E7EB;
            --text-secondary: #9CA3AF;
            --text-muted: #6B7280;
            --input-bg: #1A1F2E;
            --input-border: #2D3348;
            --input-focus: #6366F1;
            --input-ring: rgba(99, 102, 241, 0.2);
            --radius-sm: 6px;
            --radius-md: 8px;
            --radius-lg: 12px;
            --font-mono: 'JetBrains Mono', 'Fira Code', 'Menlo', 'Consolas', monospace;
        }

        /* ============================================ */
        /* 全局背景 */
        /* ============================================ */
        .stApp {
            background: var(--main-bg) !important;
        }

        /* ============================================ */
        /* 隐藏 Streamlit 默认元素 */
        /* ============================================ */
        header[data-testid="stHeader"] { display: none !important; }
        div[data-testid="stToolbar"] { display: none !important; }
        .stDeployButton { display: none !important; }
        #MainMenu { display: none !important; }
        footer { display: none !important; }
        button[data-testid="stBaseButton-headerNoPadding"] { display: none !important; }
        div[data-testid="stSidebarCollapseButton"] { display: none !important; }

        /* ============================================ */
        /* 主内容区 - 暗色背景 */
        /* ============================================ */
        .main .block-container,
        section[data-testid="stSidebar"] + section {
            background: var(--main-bg) !important;
            padding: 1.5rem 2rem 2rem 2rem !important;
        }

        /* ============================================ */
        /* Streamlit 内部元素暗色适配 */
        /* ============================================ */
        .stMarkdown, .stMarkdown p, .stMarkdown span, .stMarkdown div {
            color: var(--text-primary);
        }

        div[data-testid="stTextInput"] label,
        div[data-testid="stTextArea"] label,
        div[data-testid="stSelectbox"] label,
        div[data-testid="stNumberInput"] label,
        div[data-testid="stSlider"] label,
        div[data-testid="stMultiSelect"] label {
            color: var(--text-secondary) !important;
            font-size: 12px !important;
            font-weight: 600 !important;
        }

        /* ============================================ */
        /* 侧边栏 - 深色 */
        /* ============================================ */
        section[data-testid="stSidebar"] {
            background: var(--sidebar-bg) !important;
            border-right: 1px solid var(--sidebar-border) !important;
        }

        section[data-testid="stSidebar"] * {
            color: #FFFFFF !important;
        }

        section[data-testid="stSidebar"] div[data-testid="stButton"] > button {
            background: transparent !important;
            border: 1px solid transparent !important;
            border-radius: 8px !important;
            padding: 0 !important;
            height: auto !important;
            min-height: 44px !important;
            width: 100% !important;
            margin-bottom: 4px !important;
            box-shadow: none !important;
            transition: all 0.15s ease !important;
        }

        section[data-testid="stSidebar"] div[data-testid="stButton"] > button > div {
            width: 100% !important;
            display: flex !important;
            justify-content: flex-start !important;
            padding: 0 !important;
        }

        section[data-testid="stSidebar"] div[data-testid="stButton"] > button > div > span {
            width: 100% !important;
            display: flex !important;
            justify-content: flex-start !important;
            padding: 0 !important;
        }

        section[data-testid="stSidebar"] div[data-testid="stButton"] button [data-testid="stMarkdownContainer"] {
            width: 100% !important;
            padding: 0 !important;
        }

        section[data-testid="stSidebar"] div[data-testid="stButton"] button p {
            margin: 0 !important;
            padding: 9px 14px !important;
            font-size: 16px !important;
            font-weight: 500 !important;
            color: #FFFFFF !important;
            letter-spacing: -0.01em !important;
            line-height: 1.4 !important;
            text-align: left !important;
            width: 100% !important;
        }

        section[data-testid="stSidebar"] div[data-testid="stButton"] > button:hover {
            background: rgba(99,102,241,0.08) !important;
            border-color: rgba(99,102,241,0.2) !important;
        }

        section[data-testid="stSidebar"] div[data-testid="stButton"] > button:hover p {
            color: #FFFFFF !important;
        }

        section[data-testid="stSidebar"] div[data-testid="stButton"] > button:focus,
        section[data-testid="stSidebar"] div[data-testid="stButton"] > button:active {
            background: rgba(99,102,241,0.15) !important;
            border-color: rgba(99,102,241,0.4) !important;
            box-shadow: none !important;
        }

        section[data-testid="stSidebar"] div[data-testid="stButton"] > button:focus p,
        section[data-testid="stSidebar"] div[data-testid="stButton"] > button:active p {
            color: #FFFFFF !important;
            font-weight: 600 !important;
        }

        /* ============================================ */
        /* 主内容区按钮 - 统一靛蓝紫色 */
        /* ============================================ */
        div[data-testid="stButton"] > button,
        button[data-testid^="stBaseButton"] {
            background: var(--primary) !important;
            color: #FFFFFF !important;
            border-radius: 6px !important;
            padding: 8px 16px !important;
            border: none !important;
            height: 36px !important;
            font-weight: 600 !important;
            font-size: 13px !important;
            transition: all 0.12s ease !important;
            box-shadow: 0 1px 3px rgba(99,102,241,0.3) !important;
        }

        div[data-testid="stButton"] > button:hover,
        button[data-testid^="stBaseButton"]:hover {
            background: var(--primary-hover) !important;
            box-shadow: 0 2px 8px rgba(99,102,241,0.4) !important;
            transform: translateY(-0.5px) !important;
            border-color: transparent !important;
            color: #FFFFFF !important;
        }

        div[data-testid="stButton"] > button:active,
        button[data-testid^="stBaseButton"]:active {
            background: var(--primary-active) !important;
            transform: translateY(0) !important;
            border-color: transparent !important;
            color: #FFFFFF !important;
        }

        div[data-testid="stButton"] > button:focus,
        button[data-testid^="stBaseButton"]:focus {
            background: var(--primary) !important;
            box-shadow: 0 0 0 3px var(--primary-ring) !important;
            border-color: transparent !important;
            color: #FFFFFF !important;
        }

        div[data-testid="stButton"] > button p,
        button[data-testid^="stBaseButton"] p {
            color: #FFFFFF !important;
        }

        /* ============================================ */
        /* 输入框 */
        /* ============================================ */
        div[data-testid="stTextInput"] input,
        div[data-testid="stTextArea"] textarea {
            background: var(--input-bg) !important;
            color: var(--text-primary) !important;
            border: 1px solid var(--input-border) !important;
            border-radius: 6px !important;
            padding: 8px 12px !important;
            font-size: 13px !important;
        }

        div[data-testid="stTextInput"] input:focus,
        div[data-testid="stTextArea"] textarea:focus {
            border-color: var(--input-focus) !important;
            box-shadow: 0 0 0 3px var(--input-ring) !important;
            outline: none !important;
        }

        div[data-testid="stTextInput"] input::placeholder,
        div[data-testid="stTextArea"] textarea::placeholder {
            color: #4B5563 !important;
        }

        div[data-testid="stSelectbox"] > div > div {
            background: var(--input-bg) !important;
            color: var(--text-primary) !important;
            border: 1px solid var(--input-border) !important;
            border-radius: 6px !important;
            font-size: 13px !important;
        }

        div[data-testid="stNumberInput"] input {
            background: var(--input-bg) !important;
            color: var(--text-primary) !important;
            border: 1px solid var(--input-border) !important;
            border-radius: 6px !important;
            padding: 8px 12px !important;
            font-size: 13px !important;
        }

        div[data-testid="stNumberInput"] input:focus {
            border-color: var(--input-focus) !important;
            box-shadow: 0 0 0 3px var(--input-ring) !important;
            outline: none !important;
        }

        /* 下拉菜单暗色 */
        div[data-baseweb="popover"] div[role="listbox"] {
            background: var(--card-bg) !important;
            border: 1px solid var(--card-border) !important;
        }
        div[data-baseweb="popover"] div[role="option"] {
            color: var(--text-primary) !important;
        }
        div[data-baseweb="popover"] div[role="option"]:hover {
            background: rgba(99,102,241,0.15) !important;
        }

        /* ============================================ */
        /* Checkbox / Radio */
        /* ============================================ */
        div[data-testid="stCheckbox"] label {
            color: var(--text-primary) !important;
            font-size: 13px !important;
        }

        div[data-testid="stCheckbox"] div[role="checkbox"] {
            border-radius: 4px !important;
            border-color: var(--input-border) !important;
            background: var(--input-bg) !important;
        }

        div[data-testid="stCheckbox"] div[role="checkbox"][aria-checked="true"] {
            background: var(--primary) !important;
            border-color: var(--primary) !important;
        }

        div[role="radiogroup"] label { color: var(--text-primary) !important; font-size: 13px !important; }
        div[role="radiogroup"] div[role="radio"] { border-color: var(--input-border) !important; background: var(--input-bg) !important; }
        div[role="radiogroup"] div[role="radio"][aria-checked="true"] {
            background: var(--primary) !important;
            border-color: var(--primary) !important;
        }

        /* ============================================ */
        /* Metric */
        /* ============================================ */
        div[data-testid="stMetricValue"] {
            color: var(--text-primary) !important;
            font-size: 32px !important;
            font-weight: 700 !important;
            letter-spacing: -0.02em !important;
        }

        div[data-testid="stMetricLabel"] {
            color: var(--text-muted) !important;
            font-size: 11px !important;
            font-weight: 600 !important;
            text-transform: uppercase !important;
            letter-spacing: 0.05em !important;
        }

        div[data-testid="stMetricDelta"] { display: none !important; }

        /* ============================================ */
        /* 页面标题 */
        /* ============================================ */
        .breadcrumb { font-size: 11px; color: var(--text-muted); margin-bottom: 8px; font-weight: 500; }
        .breadcrumb span { color: var(--text-primary); cursor: pointer; font-weight: 600; }

        .page-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 20px; }
        .page-title { font-size: 22px; font-weight: 700; color: var(--text-primary); letter-spacing: -0.02em; }
        .page-description { font-size: 13px; color: var(--text-secondary); margin-top: 2px; line-height: 1.5; }

        /* ============================================ */
        /* 卡片 */
        /* ============================================ */
        .card {
            background: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: var(--radius-lg);
            padding: 20px 24px;
            margin-bottom: 14px;
            box-shadow: var(--card-shadow);
        }

        .card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; }
        .card-title { font-size: 14px; font-weight: 600; color: var(--text-primary); letter-spacing: -0.01em; }
        .card-description { font-size: 12px; color: var(--text-muted); margin-top: 2px; line-height: 1.5; }

        /* ============================================ */
        /* 表单容器暗色 */
        /* ============================================ */
        div[data-testid="stForm"] {
            background: transparent !important;
            border: none !important;
            padding: 0 !important;
        }

        /* ============================================ */
        /* 日志容器 - 终端风格 */
        /* ============================================ */
        .log-container {
            background: #060910;
            border: 1px solid rgba(255,255,255,0.06);
            border-radius: 8px;
            padding: 14px 16px;
            font-family: var(--font-mono);
            font-size: 12px;
            color: #8B949E;
            max-height: 400px;
            overflow-y: auto;
            white-space: pre-wrap;
            line-height: 1.7;
        }

        /* ============================================ */
        /* 滚动条 */
        /* ============================================ */
        ::-webkit-scrollbar { width: 5px; height: 5px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 3px; }
        ::-webkit-scrollbar-thumb:hover { background: rgba(255,255,255,0.18); }
        section[data-testid="stSidebar"] ::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.08); }

        /* ============================================ */
        /* 侧边栏标题 */
        /* ============================================ */
        .sidebar-title {
            font-size: 18px;
            font-weight: 700;
            color: #FFFFFF !important;
            padding: 20px 8px 8px 8px;
            margin-bottom: 0;
            letter-spacing: -0.01em;
        }

        /* 首页标题按钮（点击跳转首页，样式伪装成标题文字） */
        section[data-testid="stSidebar"] div[data-testid="element-container"]:has(.sb-title-marker) + div[data-testid="element-container"] div[data-testid="stButton"] > button {
            background: transparent !important;
            border: none !important;
            color: #FFFFFF !important;
            font-size: 18px !important;
            font-weight: 700 !important;
            justify-content: flex-start !important;
            padding: 20px 8px 8px 8px !important;
            height: auto !important;
            min-height: unset !important;
            box-shadow: none !important;
            cursor: pointer !important;
            border-radius: 0 !important;
            letter-spacing: -0.01em !important;
            transition: color 0.15s ease !important;
        }
        section[data-testid="stSidebar"] div[data-testid="element-container"]:has(.sb-title-marker) + div[data-testid="element-container"] div[data-testid="stButton"] > button:hover {
            background: transparent !important;
            color: #A5B4FC !important;
            box-shadow: none !important;
        }
        section[data-testid="stSidebar"] div[data-testid="element-container"]:has(.sb-title-marker) + div[data-testid="element-container"] div[data-testid="stButton"] > button:focus,
        section[data-testid="stSidebar"] div[data-testid="element-container"]:has(.sb-title-marker) + div[data-testid="element-container"] div[data-testid="stButton"] > button:active {
            background: transparent !important;
            color: #818CF8 !important;
            box-shadow: none !important;
            border: none !important;
        }
        section[data-testid="stSidebar"] div[data-testid="element-container"]:has(.sb-title-marker) + div[data-testid="element-container"] div[data-testid="stButton"] > button p {
            font-size: 18px !important;
            font-weight: 700 !important;
            color: inherit !important;
            margin: 0 !important;
            padding: 0 !important;
        }
        .sb-title-marker { display: none; }

        .sidebar-subtitle {
            font-size: 10px;
            color: var(--sidebar-muted) !important;
            padding: 0 8px 12px 8px;
            margin-top: 2px;
            margin-bottom: 0;
            letter-spacing: 0.05em;
            text-transform: uppercase;
            font-weight: 600;
        }

        .sidebar-divider {
            height: 1px;
            background: var(--sidebar-border);
            margin: 4px 8px 8px 8px;
        }

        /* ============================================ */
        /* 状态栏 */
        /* ============================================ */
        .sidebar-status {
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
            padding: 8px;
            margin-bottom: 4px;
        }

        .sidebar-status-item {
            display: flex;
            align-items: center;
            gap: 5px;
            font-size: 12px;
            color: #FFFFFF !important;
            font-weight: 500;
        }

        .status-dot {
            width: 6px;
            height: 6px;
            border-radius: 50%;
            flex-shrink: 0;
        }

        .status-dot.online {
            background: var(--success);
            box-shadow: 0 0 0 2px rgba(16,185,129,0.15);
        }

        .status-dot.offline {
            background: var(--error);
            box-shadow: 0 0 0 2px rgba(239,68,68,0.15);
        }

        /* ============================================ */
        /* Slider */
        /* ============================================ */
        div[data-testid="stSlider"] {
            background: transparent !important;
            border: none !important;
            box-shadow: none !important;
        }
        div[data-testid="stSlider"] > div {
            background: transparent !important;
            border: none !important;
            box-shadow: none !important;
        }
        /* 轨道底色 */
        div[data-testid="stSlider"] [class*="st-cp"],
        div[data-testid="stSlider"] [class*="st-cr"] {
            background: #2D3348 !important;
            border: none !important;
            box-shadow: none !important;
            border-radius: 2px !important;
            height: 4px !important;
        }
        /* 滑块圆点 */
        div[data-testid="stSlider"] div[role="slider"] {
            background: var(--primary) !important;
            border: none !important;
            width: 14px !important;
            height: 14px !important;
            border-radius: 50% !important;
            box-shadow: 0 0 0 3px rgba(99,102,241,0.2) !important;
            cursor: grab !important;
        }
        div[data-testid="stSlider"] div[role="slider"]:hover {
            box-shadow: 0 0 0 5px rgba(99,102,241,0.3) !important;
        }
        /* 隐藏滑块上的数值标签 */
        div[data-testid="stSlider"] div[data-testid="stSliderThumbValue"] {
            display: none !important;
        }

        /* ============================================ */
        /* DataFrame */
        /* ============================================ */
        .stDataFrame {
            border-radius: 8px !important;
            overflow: hidden !important;
            border: 1px solid var(--card-border) !important;
        }

        .stDataFrame table {
            background: var(--card-bg) !important;
            color: var(--text-primary) !important;
        }

        .stDataFrame th {
            background: #1A1F2E !important;
            color: var(--text-muted) !important;
            font-weight: 600 !important;
            font-size: 11px !important;
            text-transform: uppercase !important;
            letter-spacing: 0.05em !important;
            border-bottom: 1px solid var(--card-border) !important;
            padding: 10px 14px !important;
        }

        .stDataFrame td {
            border-bottom: 1px solid rgba(255,255,255,0.04) !important;
            font-size: 13px !important;
            padding: 10px 14px !important;
            color: var(--text-primary) !important;
        }

        .stDataFrame tr:hover td { background: rgba(99,102,241,0.06) !important; }
        .stDataFrame tr:last-child td { border-bottom: none !important; }

        /* ============================================ */
        /* Tabs */
        /* ============================================ */
        div[data-baseweb="tab-list"] {
            background: transparent !important;
            border-bottom: 1px solid var(--card-border) !important;
            gap: 0 !important;
        }

        div[data-baseweb="tab"] {
            color: var(--text-muted) !important;
            font-weight: 500 !important;
            font-size: 13px !important;
            padding: 10px 16px !important;
        }

        div[data-baseweb="tab"][aria-selected="true"] {
            color: var(--primary) !important;
            font-weight: 600 !important;
            border-bottom-color: var(--primary) !important;
        }

        div[data-baseweb="tab"]:hover {
            color: var(--text-secondary) !important;
            background: rgba(255,255,255,0.03) !important;
        }

        /* Tab panel */
        div[data-baseweb="tab-panel"] {
            background: transparent !important;
        }

        /* ============================================ */
        /* Expander */
        /* ============================================ */
        details {
            background: var(--card-bg) !important;
            border: 1px solid var(--card-border) !important;
            border-radius: 6px !important;
            overflow: hidden !important;
            margin-bottom: 6px !important;
        }

        details summary {
            color: var(--text-primary) !important;
            font-weight: 600 !important;
            font-size: 13px !important;
            padding: 10px 14px !important;
        }

        details summary:hover { background: rgba(255,255,255,0.03) !important; }

        /* ============================================ */
        /* Alert */
        /* ============================================ */
        div[data-testid="stAlert"] {
            border-radius: 6px !important;
            font-size: 13px !important;
        }

        div[data-testid="stAlertContentSuccess"] {
            background: rgba(16,185,129,0.1) !important;
            border: 1px solid rgba(16,185,129,0.2) !important;
            color: #34D399 !important;
        }
        div[data-testid="stAlertContentInfo"] {
            background: rgba(99,102,241,0.1) !important;
            border: 1px solid rgba(99,102,241,0.2) !important;
            color: #A5B4FC !important;
        }
        div[data-testid="stAlertContentWarning"] {
            background: rgba(245,158,11,0.1) !important;
            border: 1px solid rgba(245,158,11,0.2) !important;
            color: #FBBF24 !important;
        }
        div[data-testid="stAlertContentError"] {
            background: rgba(239,68,68,0.1) !important;
            border: 1px solid rgba(239,68,68,0.2) !important;
            color: #F87171 !important;
        }

        /* ============================================ */
        /* Spinner */
        /* ============================================ */
        div[data-testid="stSpinner"] { color: var(--primary) !important; }

        /* ============================================ */
        /* 分割线 */
        /* ============================================ */
        hr {
            border-color: var(--card-border) !important;
        }
    </style>
    """, unsafe_allow_html=True)

    if "current_page" not in st.session_state:
        st.session_state.current_page = "首页"

    if "nav" in st.query_params:
        if st.query_params["nav"] == "home":
            st.session_state.current_page = "首页"
        st.query_params.pop("nav", None)

    menu_items = [
        {"id": "设备管理", "label": "AI员工群控管理"},
        {"id": "实时任务监控", "label": "AI员工工作动向"},
        {"id": "搜索与基础控制", "label": "AI搜索控制大模型"},
        {"id": "自定义意向关键词", "label": "AI深度挖掘客户"},
        {"id": "AI截流获客策略", "label": "视频处理设置"},
        {"id": "视频处理设置", "label": "AI员工工作调整台"},
        {"id": "自定义执行功能选择", "label": "AI功能自主选项"},
        {"id": "作者私信策略", "label": "AI员工话术私信调整"},
        {"id": "流程控制", "label": "AI一键控制开关"},
        {"id": "获客数据看板", "label": "AI获客面板员工走向"},
    ]

    with st.sidebar:
        st.markdown('<div class="sb-title-marker"></div>', unsafe_allow_html=True)
        if st.button("AI运营员工群控台", key="sb_home_title", use_container_width=True):
            st.session_state.current_page = "首页"
            st.rerun()

        st.markdown(f"""
        <div class="sidebar-status">
            <div class="sidebar-status-item">
                <span class="status-dot {'online' if device_status['connected'] else 'offline'}"></span>
                <span>设备 {'已连接' if device_status['connected'] else '未连接'}</span>
            </div>
            <div class="sidebar-status-item">
                <span class="status-dot {'online' if license_info['ai_enabled'] else 'offline'}"></span>
                <span>AI {'已启用' if license_info['ai_enabled'] else '未启用'}</span>
            </div>
            <div class="sidebar-status-item">
                <span class="status-dot {'online' if license_info['license_valid'] else 'offline'}"></span>
                <span>授权 {'正常' if license_info['license_valid'] else '未配置'}</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

        st.markdown('<div class="sidebar-divider"></div>', unsafe_allow_html=True)

        for item in menu_items:
            if st.button(item["label"], key=f"menu_{item['id']}", use_container_width=True):
                st.session_state.current_page = item["id"]
                st.rerun()

    render_douyin_page(st.session_state.current_page)


if __name__ == "__main__":
    main()
