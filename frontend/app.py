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
            --primary: #4F46E5;
            --primary-hover: #4338CA;
            --primary-active: #3730A3;
            --primary-ring: rgba(79, 70, 229, 0.15);
            --success: #059669;
            --warning: #D97706;
            --error: #DC2626;
            --sidebar-bg: #0B0C10;
            --sidebar-hover: #1A1C24;
            --sidebar-active: #4F46E5;
            --sidebar-text: #E5E7EB;
            --sidebar-muted: #6B7280;
            --sidebar-border: rgba(255,255,255,0.06);
            --main-bg: #F8F9FB;
            --card-bg: #FFFFFF;
            --card-border: #E5E7EB;
            --card-shadow: 0 1px 3px rgba(0,0,0,0.04);
            --text-primary: #111827;
            --text-secondary: #6B7280;
            --text-muted: #9CA3AF;
            --input-bg: #FFFFFF;
            --input-border: #D1D5DB;
            --input-focus: #4F46E5;
            --input-ring: rgba(79, 70, 229, 0.15);
            --radius-sm: 6px;
            --radius-md: 8px;
            --radius-lg: 12px;
            --font-mono: 'JetBrains Mono', 'Fira Code', 'Menlo', 'Consolas', monospace;
        }

        /* ============================================ */
        /* 隐藏 Streamlit 默认元素 */
        /* ============================================ */
        header[data-testid="stHeader"] { display: none !important; }
        div[data-testid="stToolbar"] { display: none !important; }
        .stDeployButton { display: none !important; }
        #MainMenu { display: none !important; }
        footer { display: none !important; }
        /* 隐藏侧边栏折叠按钮 */
        button[data-testid="stBaseButton-headerNoPadding"] { display: none !important; }
        div[data-testid="stSidebarCollapseButton"] { display: none !important; }

        /* ============================================ */
        /* 主内容区 - 浅色背景 */
        /* ============================================ */
        .main .block-container,
        section[data-testid="stSidebar"] + section {
            background: var(--main-bg) !important;
            padding: 1.5rem 2rem 2rem 2rem !important;
        }

        /* ============================================ */
        /* 侧边栏 - 深色 */
        /* ============================================ */
        section[data-testid="stSidebar"] {
            background: var(--sidebar-bg) !important;
            border-right: 1px solid var(--sidebar-border) !important;
        }

        section[data-testid="stSidebar"] * {
            color: var(--sidebar-text) !important;
        }

        /* 侧边栏按钮 - 整体 */
        section[data-testid="stSidebar"] div[data-testid="stButton"] > button {
            background: transparent !important;
            border: 1px solid transparent !important;
            border-radius: 8px !important;
            padding: 0 !important;
            height: auto !important;
            min-height: 38px !important;
            width: 100% !important;
            margin-bottom: 4px !important;
            box-shadow: none !important;
            transition: all 0.15s ease !important;
        }

        /* 按钮内层 wrapper */
        section[data-testid="stSidebar"] div[data-testid="stButton"] > button > div {
            width: 100% !important;
            display: flex !important;
            justify-content: flex-start !important;
            padding: 0 !important;
        }

        /* 按钮内层 span */
        section[data-testid="stSidebar"] div[data-testid="stButton"] > button > div > span {
            width: 100% !important;
            display: flex !important;
            justify-content: flex-start !important;
            padding: 0 !important;
        }

        /* 按钮文字容器 */
        section[data-testid="stSidebar"] div[data-testid="stButton"] button [data-testid="stMarkdownContainer"] {
            width: 100% !important;
            padding: 0 !important;
        }

        /* 按钮文字 p 标签 */
        section[data-testid="stSidebar"] div[data-testid="stButton"] button p {
            margin: 0 !important;
            padding: 9px 14px !important;
            font-size: 13px !important;
            font-weight: 500 !important;
            color: #9CA3AF !important;
            letter-spacing: -0.01em !important;
            line-height: 1.4 !important;
            text-align: left !important;
            width: 100% !important;
        }

        section[data-testid="stSidebar"] div[data-testid="stButton"] > button:hover {
            background: rgba(255,255,255,0.04) !important;
            border-color: rgba(255,255,255,0.08) !important;
            transform: none !important;
        }

        section[data-testid="stSidebar"] div[data-testid="stButton"] > button:hover p {
            color: #E5E7EB !important;
        }

        section[data-testid="stSidebar"] div[data-testid="stButton"] > button:focus,
        section[data-testid="stSidebar"] div[data-testid="stButton"] > button:active {
            background: rgba(79,70,229,0.15) !important;
            border-color: rgba(79,70,229,0.4) !important;
            box-shadow: none !important;
        }

        section[data-testid="stSidebar"] div[data-testid="stButton"] > button:focus p,
        section[data-testid="stSidebar"] div[data-testid="stButton"] > button:active p {
            color: #A5B4FC !important;
            font-weight: 600 !important;
        }

        /* ============================================ */
        /* 主内容区按钮 */
        /* ============================================ */
        div[data-testid="stButton"] > button {
            background: var(--primary) !important;
            color: #FFFFFF !important;
            border-radius: 6px !important;
            padding: 8px 16px !important;
            border: none !important;
            height: 36px !important;
            font-weight: 600 !important;
            font-size: 13px !important;
            transition: all 0.12s ease !important;
            box-shadow: 0 1px 2px rgba(79,70,229,0.25) !important;
        }

        div[data-testid="stButton"] > button:hover {
            background: var(--primary-hover) !important;
            box-shadow: 0 2px 6px rgba(79,70,229,0.35) !important;
            transform: translateY(-0.5px) !important;
        }

        div[data-testid="stButton"] > button:active {
            background: var(--primary-active) !important;
            transform: translateY(0) !important;
        }

        div[data-testid="stButton"] > button[class*="secondary"] {
            background: var(--card-bg) !important;
            color: var(--text-primary) !important;
            border: 1px solid var(--card-border) !important;
            box-shadow: 0 1px 2px rgba(0,0,0,0.03) !important;
        }

        div[data-testid="stButton"] > button[class*="secondary"]:hover {
            background: #F9FAFB !important;
            border-color: #D1D5DB !important;
            box-shadow: 0 2px 4px rgba(0,0,0,0.04) !important;
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
            color: #9CA3AF !important;
        }

        div[data-testid="stSelectbox"] > div {
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
            background: var(--card-bg) !important;
        }

        div[data-testid="stCheckbox"] div[role="checkbox"][aria-checked="true"] {
            background: var(--primary) !important;
            border-color: var(--primary) !important;
        }

        div[role="radiogroup"] label { color: var(--text-primary) !important; font-size: 13px !important; }
        div[role="radiogroup"] div[role="radio"] { border-color: var(--input-border) !important; }
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
        .breadcrumb span { color: var(--primary); cursor: pointer; font-weight: 600; }

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
        /* 日志容器 - 终端风格 */
        /* ============================================ */
        .log-container {
            background: #0D1117;
            border: 1px solid #21262D;
            border-radius: 8px;
            padding: 14px 16px;
            font-family: var(--font-mono);
            font-size: 12px;
            color: #C9D1D9;
            max-height: 400px;
            overflow-y: auto;
            white-space: pre-wrap;
            line-height: 1.7;
        }

        /* ============================================ */
        /* 滚动条 */
        /* ============================================ */
        ::-webkit-scrollbar { width: 4px; height: 4px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: rgba(0,0,0,0.12); border-radius: 2px; }
        section[data-testid="stSidebar"] ::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); }

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
        /* 状态栏（侧边栏内） */
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
            font-size: 11px;
            color: #9CA3AF !important;
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
            box-shadow: 0 0 0 2px rgba(5,150,105,0.15);
        }

        .status-dot.offline {
            background: var(--error);
            box-shadow: 0 0 0 2px rgba(220,38,38,0.15);
        }

        /* ============================================ */
        /* Slider */
        /* ============================================ */
        .stSlider > div { background: #E5E7EB !important; }
        .stSlider > div > div { background: var(--primary) !important; }
        .stSlider > div > div > div {
            background: #FFFFFF !important;
            box-shadow: 0 1px 3px rgba(0,0,0,0.12) !important;
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
            background: #F9FAFB !important;
            color: var(--text-muted) !important;
            font-weight: 600 !important;
            font-size: 11px !important;
            text-transform: uppercase !important;
            letter-spacing: 0.05em !important;
            border-bottom: 1px solid var(--card-border) !important;
            padding: 10px 14px !important;
        }

        .stDataFrame td {
            border-bottom: 1px solid #F3F4F6 !important;
            font-size: 13px !important;
            padding: 10px 14px !important;
        }

        .stDataFrame tr:last-child td { border-bottom: none !important; }

        /* ============================================ */
        /* Tabs */
        /* ============================================ */
        div[data-baseweb="tab-list"] {
            background: transparent !important;
            border-bottom: 1.5px solid var(--card-border) !important;
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

        details summary:hover { background: #F9FAFB !important; }

        /* ============================================ */
        /* Alert */
        /* ============================================ */
        div[data-testid="stAlert"] {
            border-radius: 6px !important;
            border: 1px solid var(--card-border) !important;
            font-size: 13px !important;
        }
    </style>
    """, unsafe_allow_html=True)

    if "current_page" not in st.session_state:
        st.session_state.current_page = "设备管理"

    menu_items = [
        {"id": "设备管理", "label": "Ai群控设备管理"},
        {"id": "实时任务监控", "label": "Ai员工工作动向"},
        {"id": "搜索与基础控制", "label": "Ai搜索控制大模型"},
        {"id": "自定义意向关键词", "label": "Ai深度挖掘客户"},
        {"id": "AI截流获客策略", "label": "视频处理设置"},
        {"id": "视频处理设置", "label": "Ai员工工作调整台"},
        {"id": "自定义执行功能选择", "label": "Ai功能自主选项"},
        {"id": "作者私信策略", "label": "Ai员工话术私信调整"},
        {"id": "流程控制", "label": "Ai一键控制开关"},
        {"id": "获客数据看板", "label": "AI获客面板员工走向"},
    ]

    with st.sidebar:
        st.markdown('<p class="sidebar-title">AI运营员工群控台</p>', unsafe_allow_html=True)

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
