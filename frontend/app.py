import os
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

_np = os.environ.get("NO_PROXY", "")
if "127.0.0.1" not in _np:
    os.environ["NO_PROXY"] = (_np + "," if _np else "") + "127.0.0.1"
    os.environ["no_proxy"] = os.environ["NO_PROXY"]

import streamlit as st
import requests
import html as _html
from douyin.douyin_app import render_douyin_page

st.set_page_config(page_title="抖音自动化群控系统", page_icon="🎵", layout="wide")

# 后端端口由 launcher 启动时动态分配并注入 APP_API_PORT，兼容固定 8000
API_PORT = os.environ.get("APP_API_PORT", "8000")
API_BASE_URL = f"http://127.0.0.1:{API_PORT}/api"
CREDIT_API_BASE = os.environ.get("APP_CREDIT_API_BASE", "https://lcjx.yun/social-ai-credit-api")

# 本地后端共享密钥：与 backend/main.py 读取同一文件 config/.local_backend_token
_LOCAL_TOKEN_FILE = os.path.join(
    os.environ.get("APP_CONFIG_DIR") or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config"),
    ".local_backend_token",
)
_session = requests.Session()
try:
    with open(_LOCAL_TOKEN_FILE, "r", encoding="utf-8") as _f:
        _tok = _f.read().strip()
        if _tok:
            _session.headers["X-Local-Token"] = _tok
except Exception:
    pass


# ============================================================
# 高级感 CSS（一次性注入，避免 rerun 重复）
# 四层 surface + 微光描边 + 强调色配额 + Type Scale + 间距 token + 动效统一
# ============================================================
_PREMIUM_CSS = """
<style>
:root {
    /* 表面层（四层亮度递进，禁用可见 border 分区） */
    --app-bg:        #0B0D12;
    --surface-1:     #11141B;
    --surface-2:     #161A24;
    --surface-3:     #1C2130;
    --overlay:       rgba(0,0,0,0.5);

    /* 文字（五级 Type Scale） */
    --text-primary:    #FFFFFF;
    --text-secondary:  #D1D5DB;
    --text-muted:      #9CA3AF;
    --text-subtle:    #6B7280;

    /* 强调色（配额制：仅按钮/active/focus 使用） */
    --accent:          #6366F1;
    --accent-hover:    #818CF8;
    --accent-active:   #4F46E5;
    --accent-subtle:   rgba(99,102,241,0.10);

    /* 状态色（仅状态圆点用，不填充大块） */
    --success: #10B981;
    --warning: #F59E0B;
    --danger:  #EF4444;

    /* 描边（几乎不可见）+ 高光 */
    --border-subtle:   rgba(255,255,255,0.04);
    --border-default:  rgba(255,255,255,0.06);
    --highlight:       rgba(255,255,255,0.04);

    /* 圆角 */
    --radius-sm: 6px;
    --radius-md: 8px;
    --radius-lg: 12px;

    /* 间距 token */
    --space-1: 4px;
    --space-2: 8px;
    --space-3: 12px;
    --space-4: 16px;
    --space-5: 24px;
    --space-6: 32px;

    /* 动效统一曲线 */
    --ease: cubic-bezier(0.4, 0, 0.2, 1);
    --dur-fast: 120ms;
    --dur-base: 180ms;

    --font-mono: 'JetBrains Mono', 'Fira Code', 'Menlo', 'Consolas', monospace;

    /* 兼容旧变量名 */
    --primary: var(--accent);
    --primary-hover: var(--accent-hover);
    --primary-active: var(--accent-active);
    --primary-ring: var(--accent-subtle);
    --main-bg: var(--app-bg);
    --card-bg: var(--surface-2);
    --card-border: var(--border-default);
    --card-shadow: 0 1px 3px rgba(0,0,0,0.3);
    --sidebar-bg: var(--surface-1);
    --sidebar-hover: var(--surface-3);
    --sidebar-active: var(--accent);
    --sidebar-text: var(--text-primary);
    --sidebar-muted: var(--text-muted);
    --sidebar-border: var(--border-subtle);
    --input-bg: var(--surface-2);
    --input-border: var(--border-default);
    --input-focus: var(--accent);
    --input-ring: var(--accent-subtle);
}

/* 全局背景 */
.stApp { background: var(--app-bg) !important; }

/* 隐藏 Streamlit 默认元素 */
header[data-testid="stHeader"] { display: none !important; }
div[data-testid="stToolbar"] { display: none !important; }
.stDeployButton { display: none !important; }
#MainMenu { display: none !important; }
footer { display: none !important; }
button[data-testid="stBaseButton-headerNoPadding"] { display: none !important; }
div[data-testid="stSidebarCollapseButton"] { display: none !important; }

/* 主内容区 */
.main .block-container,
section[data-testid="stSidebar"] + section {
    background: var(--app-bg) !important;
    padding: var(--space-5) var(--space-5) var(--space-6) var(--space-5) !important;
}

/* Markdown 文字层级 */
.stMarkdown, .stMarkdown p, .stMarkdown span, .stMarkdown div {
    color: var(--text-primary);
    font-variant-numeric: tabular-nums;
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
    letter-spacing: -0.005em;
}

/* ============================================ */
/* 侧边栏 - surface-1 + 毛玻璃 */
/* ============================================ */
section[data-testid="stSidebar"] {
    background: var(--surface-1) !important;
    border-right: 1px solid var(--border-subtle) !important;
    backdrop-filter: blur(20px) saturate(180%);
    -webkit-backdrop-filter: blur(20px) saturate(180%);
}

section[data-testid="stSidebar"] * { color: var(--text-primary) !important; }

section[data-testid="stSidebar"] div[data-testid="stButton"] > button {
    background: transparent !important;
    border: 1px solid transparent !important;
    border-radius: var(--radius-md) !important;
    padding: 0 !important;
    height: auto !important;
    min-height: 40px !important;
    width: 100% !important;
    margin-bottom: var(--space-1) !important;
    box-shadow: none !important;
    transition: all var(--dur-fast) var(--ease) !important;
}

section[data-testid="stSidebar"] div[data-testid="stButton"] > button > div,
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
    font-size: 14px !important;
    font-weight: 500 !important;
    color: var(--text-secondary) !important;
    letter-spacing: -0.005em !important;
    line-height: 1.4 !important;
    text-align: left !important;
    width: 100% !important;
    font-variant-numeric: tabular-nums;
}

section[data-testid="stSidebar"] div[data-testid="stButton"] > button:hover {
    background: var(--accent-subtle) !important;
    border-color: var(--border-subtle) !important;
}

section[data-testid="stSidebar"] div[data-testid="stButton"] > button:hover p {
    color: var(--text-primary) !important;
}

section[data-testid="stSidebar"] div[data-testid="stButton"] > button:focus,
section[data-testid="stSidebar"] div[data-testid="stButton"] > button:active {
    background: var(--accent-subtle) !important;
    border-color: rgba(99,102,241,0.25) !important;
    box-shadow: none !important;
}

section[data-testid="stSidebar"] div[data-testid="stButton"] > button:focus p,
section[data-testid="stSidebar"] div[data-testid="stButton"] > button:active p {
    color: var(--text-primary) !important;
    font-weight: 600 !important;
}

/* ============================================ */
/* 主内容按钮 - 微光描边取代发光阴影 */
/* ============================================ */
div[data-testid="stButton"] > button,
button[data-testid^="stBaseButton"] {
    background: var(--accent) !important;
    color: #FFFFFF !important;
    border-radius: var(--radius-sm) !important;
    padding: 8px 16px !important;
    border: none !important;
    height: 36px !important;
    font-weight: 600 !important;
    font-size: 13px !important;
    transition: all var(--dur-fast) var(--ease) !important;
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.10), inset 0 0 0 1px rgba(255,255,255,0.04) !important;
}

div[data-testid="stButton"] > button:hover,
button[data-testid^="stBaseButton"]:hover {
    background: var(--accent-hover) !important;
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.12), inset 0 0 0 1px rgba(255,255,255,0.06) !important;
    transform: translateY(-1px) !important;
    border-color: transparent !important;
    color: #FFFFFF !important;
}

div[data-testid="stButton"] > button:active,
button[data-testid^="stBaseButton"]:active {
    background: var(--accent-active) !important;
    transform: translateY(0) !important;
    border-color: transparent !important;
    color: #FFFFFF !important;
}

div[data-testid="stButton"] > button:focus,
button[data-testid^="stBaseButton"]:focus {
    background: var(--accent) !important;
    box-shadow: 0 0 0 1px var(--accent), inset 0 1px 0 rgba(255,255,255,0.10) !important;
    border-color: transparent !important;
    color: #FFFFFF !important;
}

div[data-testid="stButton"] > button p,
button[data-testid^="stBaseButton"] p { color: #FFFFFF !important; }

/* ============================================ */
/* 输入框 - surface-2 底色 + 1px 描边 */
/* ============================================ */
div[data-testid="stTextInput"] input,
div[data-testid="stTextArea"] textarea {
    background: var(--surface-2) !important;
    color: var(--text-primary) !important;
    border: 1px solid var(--border-default) !important;
    border-radius: var(--radius-sm) !important;
    padding: 8px 12px !important;
    font-size: 13px !important;
    box-shadow: inset 0 1px 0 var(--highlight) !important;
    transition: all var(--dur-fast) var(--ease) !important;
}

div[data-testid="stTextInput"] input:focus,
div[data-testid="stTextArea"] textarea:focus {
    border-color: var(--accent) !important;
    box-shadow: 0 0 0 1px var(--accent), inset 0 1px 0 var(--highlight) !important;
    outline: none !important;
}

div[data-testid="stTextInput"] input::placeholder,
div[data-testid="stTextArea"] textarea::placeholder {
    color: var(--text-subtle) !important;
}

div[data-testid="stSelectbox"] > div > div {
    background: var(--surface-2) !important;
    color: var(--text-primary) !important;
    border: 1px solid var(--border-default) !important;
    border-radius: var(--radius-sm) !important;
    font-size: 13px !important;
    box-shadow: inset 0 1px 0 var(--highlight) !important;
}

div[data-testid="stNumberInput"] input {
    background: var(--surface-2) !important;
    color: var(--text-primary) !important;
    border: 1px solid var(--border-default) !important;
    border-radius: var(--radius-sm) !important;
    padding: 8px 12px !important;
    font-size: 13px !important;
    box-shadow: inset 0 1px 0 var(--highlight) !important;
}

div[data-testid="stNumberInput"] input:focus {
    border-color: var(--accent) !important;
    box-shadow: 0 0 0 1px var(--accent), inset 0 1px 0 var(--highlight) !important;
    outline: none !important;
}

/* 下拉菜单暗色 */
div[data-baseweb="popover"] div[role="listbox"] {
    background: var(--surface-3) !important;
    border: 1px solid var(--border-default) !important;
    box-shadow: 0 8px 24px rgba(0,0,0,0.4), inset 0 1px 0 var(--highlight) !important;
}
div[data-baseweb="popover"] div[role="option"] { color: var(--text-primary) !important; }
div[data-baseweb="popover"] div[role="option"]:hover { background: var(--accent-subtle) !important; }

/* ============================================ */
/* Checkbox / Radio */
/* ============================================ */
div[data-testid="stCheckbox"] label {
    color: var(--text-primary) !important;
    font-size: 13px !important;
}

div[data-testid="stCheckbox"] div[role="checkbox"] {
    border-radius: 4px !important;
    border-color: var(--border-default) !important;
    background: var(--surface-2) !important;
}

div[data-testid="stCheckbox"] div[role="checkbox"][aria-checked="true"] {
    background: var(--accent) !important;
    border-color: var(--accent) !important;
}

div[role="radiogroup"] label { color: var(--text-primary) !important; font-size: 13px !important; }
div[role="radiogroup"] div[role="radio"] { border-color: var(--border-default) !important; background: var(--surface-2) !important; }
div[role="radiogroup"] div[role="radio"][aria-checked="true"] {
    background: var(--accent) !important;
    border-color: var(--accent) !important;
}

/* ============================================ */
/* Metric */
/* ============================================ */
div[data-testid="stMetricValue"] {
    color: var(--text-primary) !important;
    font-size: 28px !important;
    font-weight: 700 !important;
    letter-spacing: -0.02em !important;
    font-variant-numeric: tabular-nums;
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
/* 页面标题 - Type Scale 落地 */
/* ============================================ */
.breadcrumb { font-size: 11px; color: var(--text-subtle); margin-bottom: var(--space-2); font-weight: 500; }
.breadcrumb span { color: var(--text-secondary); cursor: pointer; font-weight: 600; }

.page-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: var(--space-5); }
.page-title { font-size: 20px; font-weight: 700; color: var(--text-primary); letter-spacing: -0.02em; }
.page-description { font-size: 12px; color: var(--text-muted); margin-top: var(--space-1); line-height: 1.5; }

/* ============================================ */
/* 卡片 - surface-2 + 微光描边（无发光阴影） */
/* ============================================ */
.card {
    background: var(--surface-2);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-lg);
    padding: var(--space-4) var(--space-5);
    margin-bottom: var(--space-3);
    box-shadow: inset 0 1px 0 var(--highlight), 0 1px 2px rgba(0,0,0,0.2);
}

.card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: var(--space-3); }
.card-title { font-size: 15px; font-weight: 600; color: var(--text-primary); letter-spacing: -0.01em; }
.card-description { font-size: 12px; color: var(--text-muted); margin-top: var(--space-1); line-height: 1.5; }

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
    background: var(--app-bg);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-md);
    padding: var(--space-3) var(--space-4);
    font-family: var(--font-mono);
    font-size: 12px;
    color: var(--text-secondary);
    max-height: 400px;
    overflow-y: auto;
    white-space: pre-wrap;
    line-height: 1.7;
    font-variant-numeric: tabular-nums;
}

/* ============================================ */
/* 滚动条 */
/* ============================================ */
::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.08); border-radius: 4px; }
::-webkit-scrollbar-thumb:hover { background: rgba(255,255,255,0.15); }
section[data-testid="stSidebar"] ::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.06); }

/* ============================================ */
/* 侧边栏标题 */
/* ============================================ */
.sidebar-title {
    font-size: 16px;
    font-weight: 700;
    color: var(--text-primary) !important;
    padding: var(--space-5) var(--space-2) var(--space-2) var(--space-2);
    margin-bottom: 0;
    letter-spacing: -0.01em;
}

/* 首页标题按钮 */
section[data-testid="stSidebar"] div[data-testid="element-container"]:has(.sb-title-marker) + div[data-testid="element-container"] div[data-testid="stButton"] > button {
    background: transparent !important;
    border: none !important;
    color: var(--text-primary) !important;
    font-size: 16px !important;
    font-weight: 700 !important;
    justify-content: flex-start !important;
    padding: var(--space-5) var(--space-2) var(--space-2) var(--space-2) !important;
    height: auto !important;
    min-height: unset !important;
    box-shadow: none !important;
    cursor: pointer !important;
    border-radius: 0 !important;
    letter-spacing: -0.01em !important;
    transition: color var(--dur-fast) var(--ease) !important;
}
section[data-testid="stSidebar"] div[data-testid="element-container"]:has(.sb-title-marker) + div[data-testid="element-container"] div[data-testid="stButton"] > button:hover {
    background: transparent !important;
    color: var(--accent-hover) !important;
    box-shadow: none !important;
}
section[data-testid="stSidebar"] div[data-testid="element-container"]:has(.sb-title-marker) + div[data-testid="element-container"] div[data-testid="stButton"] > button:focus,
section[data-testid="stSidebar"] div[data-testid="element-container"]:has(.sb-title-marker) + div[data-testid="element-container"] div[data-testid="stButton"] > button:active {
    background: transparent !important;
    color: var(--accent-hover) !important;
    box-shadow: none !important;
    border: none !important;
}
section[data-testid="stSidebar"] div[data-testid="element-container"]:has(.sb-title-marker) + div[data-testid="element-container"] div[data-testid="stButton"] > button p {
    font-size: 16px !important;
    font-weight: 700 !important;
    color: inherit !important;
    margin: 0 !important;
    padding: 0 !important;
}
.sb-title-marker { display: none; }

.sidebar-subtitle {
    font-size: 10px;
    color: var(--text-muted) !important;
    padding: 0 var(--space-2) var(--space-3) var(--space-2);
    margin-top: 2px;
    margin-bottom: 0;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    font-weight: 600;
}

.sidebar-divider {
    height: 1px;
    background: var(--border-subtle);
    margin: var(--space-1) var(--space-2) var(--space-2) var(--space-2);
}

/* ============================================ */
/* 状态栏 */
/* ============================================ */
.sidebar-status {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
    padding: var(--space-2);
    margin-bottom: var(--space-1);
}

.sidebar-status-item {
    display: flex;
    align-items: center;
    gap: 5px;
    font-size: 12px;
    color: var(--text-secondary) !important;
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
    background: var(--danger);
    box-shadow: 0 0 0 2px rgba(239,68,68,0.15);
}

/* ============================================ */
/* Slider */
/* ============================================ */
div[data-testid="stSlider"] { background: transparent !important; border: none !important; box-shadow: none !important; }
div[data-testid="stSlider"] > div { background: transparent !important; border: none !important; box-shadow: none !important; }
div[data-testid="stSlider"] [class*="st-cp"],
div[data-testid="stSlider"] [class*="st-cr"] {
    background: var(--surface-3) !important;
    border: none !important;
    box-shadow: none !important;
    border-radius: 2px !important;
    height: 4px !important;
}
div[data-testid="stSlider"] div[role="slider"] {
    background: var(--accent) !important;
    border: none !important;
    width: 14px !important;
    height: 14px !important;
    border-radius: 50% !important;
    box-shadow: 0 0 0 3px var(--accent-subtle) !important;
    cursor: grab !important;
}
div[data-testid="stSlider"] div[role="slider"]:hover {
    box-shadow: 0 0 0 5px rgba(99,102,241,0.18) !important;
}
div[data-testid="stSlider"] div[data-testid="stSliderThumbValue"] { display: none !important; }

/* ============================================ */
/* DataFrame */
/* ============================================ */
.stDataFrame {
    border-radius: var(--radius-md) !important;
    overflow: hidden !important;
    border: 1px solid var(--border-subtle) !important;
    box-shadow: inset 0 1px 0 var(--highlight) !important;
}

.stDataFrame table {
    background: var(--surface-2) !important;
    color: var(--text-primary) !important;
}

.stDataFrame th {
    background: var(--surface-3) !important;
    color: var(--text-muted) !important;
    font-weight: 600 !important;
    font-size: 11px !important;
    text-transform: uppercase !important;
    letter-spacing: 0.05em !important;
    border-bottom: 1px solid var(--border-subtle) !important;
    padding: 10px 14px !important;
}

.stDataFrame td {
    border-bottom: 1px solid var(--border-subtle) !important;
    font-size: 13px !important;
    padding: 10px 14px !important;
    color: var(--text-primary) !important;
    font-variant-numeric: tabular-nums;
}

.stDataFrame tr:hover td { background: var(--accent-subtle) !important; }
.stDataFrame tr:last-child td { border-bottom: none !important; }

/* ============================================ */
/* Tabs - active 用细线指示器而非填充 */
/* ============================================ */
div[data-baseweb="tab-list"] {
    background: transparent !important;
    border-bottom: 1px solid var(--border-subtle) !important;
    gap: 0 !important;
}

div[data-baseweb="tab"] {
    color: var(--text-muted) !important;
    font-weight: 500 !important;
    font-size: 13px !important;
    padding: 10px 16px !important;
    transition: color var(--dur-fast) var(--ease) !important;
}

div[data-baseweb="tab"][aria-selected="true"] {
    color: var(--text-primary) !important;
    font-weight: 600 !important;
    border-bottom-color: var(--accent) !important;
}

div[data-baseweb="tab"]:hover {
    color: var(--text-secondary) !important;
    background: var(--highlight) !important;
}

div[data-baseweb="tab-panel"] { background: transparent !important; }

/* ============================================ */
/* Expander */
/* ============================================ */
details {
    background: var(--surface-2) !important;
    border: 1px solid var(--border-subtle) !important;
    border-radius: var(--radius-sm) !important;
    overflow: hidden !important;
    margin-bottom: var(--space-2) !important;
    box-shadow: inset 0 1px 0 var(--highlight) !important;
}

details summary {
    color: var(--text-primary) !important;
    font-weight: 600 !important;
    font-size: 13px !important;
    padding: 10px 14px !important;
}

details summary:hover { background: var(--highlight) !important; }

/* ============================================ */
/* Alert */
/* ============================================ */
div[data-testid="stAlert"] {
    border-radius: var(--radius-sm) !important;
    font-size: 13px !important;
}

div[data-testid="stAlertContentSuccess"] {
    background: rgba(16,185,129,0.08) !important;
    border: 1px solid rgba(16,185,129,0.18) !important;
    color: #34D399 !important;
}
div[data-testid="stAlertContentInfo"] {
    background: var(--accent-subtle) !important;
    border: 1px solid rgba(99,102,241,0.18) !important;
    color: var(--accent-hover) !important;
}
div[data-testid="stAlertContentWarning"] {
    background: rgba(245,158,11,0.08) !important;
    border: 1px solid rgba(245,158,11,0.18) !important;
    color: #FBBF24 !important;
}
div[data-testid="stAlertContentError"] {
    background: rgba(239,68,68,0.08) !important;
    border: 1px solid rgba(239,68,68,0.18) !important;
    color: #F87171 !important;
}

/* Spinner */
div[data-testid="stSpinner"] { color: var(--accent) !important; }

/* 分割线 */
hr { border-color: var(--border-subtle) !important; }

/* ============================================ */
/* 右上角工具栏 - surface-3 + 毛玻璃 */
/* ============================================ */
.top-toolbar {
    position: fixed;
    top: var(--space-3);
    right: var(--space-5);
    z-index: 9999;
    display: flex;
    align-items: center;
    gap: var(--space-2);
    background: rgba(28, 33, 48, 0.85);
    backdrop-filter: blur(16px) saturate(180%);
    -webkit-backdrop-filter: blur(16px) saturate(180%);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-md);
    padding: var(--space-2) var(--space-2) var(--space-2) var(--space-3);
    box-shadow: inset 0 1px 0 var(--highlight), 0 4px 16px rgba(0,0,0,0.35);
}

.toolbar-credit {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 1px;
    padding-right: var(--space-1);
}

.toolbar-credit-label {
    font-size: 9px;
    color: var(--text-muted);
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
}

.toolbar-credit-value {
    font-size: 15px;
    font-weight: 700;
    color: var(--text-primary);
    font-variant-numeric: tabular-nums;
    letter-spacing: -0.01em;
    line-height: 1.2;
}

.toolbar-divider {
    width: 1px;
    height: 28px;
    background: var(--border-subtle);
    margin: 0 2px;
}

.toolbar-recharge-btn {
    background: var(--accent) !important;
    color: #FFFFFF !important;
    border: none !important;
    border-radius: var(--radius-sm) !important;
    padding: 6px 12px !important;
    font-size: 12px !important;
    font-weight: 600 !important;
    cursor: pointer !important;
    transition: all var(--dur-fast) var(--ease) !important;
    height: auto !important;
    min-height: unset !important;
    line-height: 1.4 !important;
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.10) !important;
}

.toolbar-recharge-btn:hover {
    background: var(--accent-hover) !important;
    transform: translateY(-1px) !important;
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.12) !important;
}

.toolbar-recharge-btn:active {
    background: var(--accent-active) !important;
    transform: translateY(0) !important;
}

.toolbar-icon-btn {
    background: transparent !important;
    border: 1px solid transparent !important;
    border-radius: var(--radius-sm) !important;
    width: 32px !important;
    height: 32px !important;
    min-width: unset !important;
    min-height: unset !important;
    padding: 0 !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    cursor: pointer !important;
    transition: all var(--dur-fast) var(--ease) !important;
    color: var(--text-muted) !important;
}

.toolbar-icon-btn:hover {
    background: var(--accent-subtle) !important;
    border-color: var(--border-subtle) !important;
    color: var(--accent-hover) !important;
}

.toolbar-icon-btn:active { background: var(--accent-subtle) !important; }
.toolbar-icon-btn svg { width: 16px; height: 16px; stroke-width: 2; }

/* 充值按钮 - 移到工具栏 */
.rc-anchor { display: none; }

.top-toolbar .toolbar-recharge-wrap {
    display: flex;
    align-items: center;
    margin-right: 2px;
}

.top-toolbar .toolbar-recharge-wrap div[data-testid="stButton"] {
    width: auto !important;
    height: auto !important;
}

.top-toolbar .toolbar-recharge-wrap button {
    background: var(--accent) !important;
    color: #FFFFFF !important;
    border: none !important;
    border-radius: var(--radius-sm) !important;
    padding: 0 14px !important;
    font-size: 12px !important;
    font-weight: 600 !important;
    height: 30px !important;
    min-height: 30px !important;
    line-height: 1 !important;
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.10) !important;
    margin: 0 !important;
    width: auto !important;
    transition: all var(--dur-fast) var(--ease) !important;
}

.top-toolbar .toolbar-recharge-wrap button:hover {
    background: var(--accent-hover) !important;
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.12) !important;
    color: #FFFFFF !important;
}

.top-toolbar .toolbar-recharge-wrap button p {
    color: #FFFFFF !important;
    font-size: 12px !important;
    font-weight: 600 !important;
    margin: 0 !important;
    line-height: 1 !important;
}

/* 充值弹窗暗色主题 */
div[role="dialog"] {
    background: var(--surface-2) !important;
    border: 1px solid var(--border-default) !important;
    border-radius: var(--radius-lg) !important;
    box-shadow: 0 20px 60px rgba(0,0,0,0.5), inset 0 1px 0 var(--highlight) !important;
}

div[role="dialog"] h2,
div[role="dialog"] [data-testid="stDialog"] header {
    color: var(--text-primary) !important;
    border-bottom: 1px solid var(--border-subtle) !important;
}

div[role="dialog"] p,
div[role="dialog"] span,
div[role="dialog"] div,
div[role="dialog"] label,
div[role="dialog"] small { color: var(--text-primary) !important; }

div[role="dialog"] .stMarkdown p,
div[role="dialog"] .stMarkdown span,
div[role="dialog"] .stMarkdown div { color: var(--text-primary) !important; }

div[role="dialog"] [data-testid="stCaptionContainer"],
div[role="dialog"] [data-testid="stCaptionContainer"] p,
div[role="dialog"] [data-testid="stCaptionContainer"] span { color: var(--text-muted) !important; }

div[role="dialog"] [data-baseweb="radio"] {
    background: var(--surface-2) !important;
    border-color: var(--border-default) !important;
}

div[role="dialog"] [data-baseweb="radio"][aria-checked="true"] {
    background: var(--accent) !important;
    border-color: var(--accent) !important;
}

div[role="dialog"] [role="radiogroup"] label { color: var(--text-primary) !important; }
div[role="dialog"] hr { border-color: var(--border-subtle) !important; }
div[role="dialog"] [data-testid="stAlertContainer"] p { color: inherit !important; }
div[role="dialog"] code {
    background: var(--surface-3) !important;
    color: var(--accent-hover) !important;
    padding: 2px 6px !important;
    border-radius: 4px !important;
    font-size: 12px !important;
}

/* 页面切换淡入过渡（fragment 局部刷新配合） */
section[data-testid="stSidebar"] + section .stMarkdown,
section[data-testid="stSidebar"] + section .stButton,
section[data-testid="stSidebar"] + section div[data-testid] {
    animation: fadeIn var(--dur-base) var(--ease);
}

@keyframes fadeIn {
    from { opacity: 0; transform: translateY(2px); }
    to { opacity: 1; transform: translateY(0); }
}
</style>
"""

# CSS 一次性注入（只在首次运行注入，fragment rerun 不重复）
st.html(_PREMIUM_CSS)


def _load_license_key() -> str:
    """从 dy/config/api_settings.yaml 读取授权码"""
    try:
        import yaml
        cfg_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dy", "config", "api_settings.yaml")
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        return (cfg.get("ai_reply", {}).get("license", {}).get("key", "") or "").strip()
    except Exception:
        return ""


# ============================================================
# 方案 A：数据缓存分级
# ============================================================
@st.cache_data(ttl=10, show_spinner=False)
def get_credits_balance() -> float:
    """实时查询当前授权码的积分余额（10s 缓存）"""
    key = _load_license_key()
    if not key:
        return 0.0
    try:
        import sys
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from social_license import get_machine_id
        machine_id = get_machine_id()
        resp = _session.post(
            f"{CREDIT_API_BASE}/auth/verify",
            json={"machine_id": machine_id, "device_id": ""},
            headers={"Authorization": f"Bearer {key}"},
            timeout=8,
        )
        if resp.status_code == 200:
            data = resp.json()
            return float(data.get("balance_credits", 0))
    except Exception:
        pass
    return 0.0


@st.cache_data(ttl=10, show_spinner=False)
def get_device_status():
    """设备状态（10s 缓存，避免每次切换页面都请求）"""
    try:
        resp = _session.get(f"{API_BASE_URL}/devices", timeout=5)
        if resp.status_code == 200:
            devices = resp.json().get("devices", [])
            if devices:
                return {"connected": True, "count": len(devices), "first_device": devices[0]}
        return {"connected": False, "count": 0, "first_device": None}
    except:
        return {"connected": False, "count": 0, "first_device": None}


@st.cache_data(ttl=10, show_spinner=False)
def get_license_status():
    """授权状态（10s 缓存）"""
    try:
        resp = _session.get(f"{API_BASE_URL}/config?platform=douyin", timeout=5)
        if resp.status_code == 200:
            config = resp.json().get("config", {})
            ai_enabled = config.get("ai_enabled", False)
            has_license = config.get("has_license_key", False)
            return {"ai_enabled": ai_enabled, "license_valid": has_license}
    except:
        pass
    return {"ai_enabled": False, "license_valid": False}


@st.dialog("充值积分")
def _render_recharge_dialog():
    """充值弹窗：套餐选择 + 创建订单 + 跳转支付 + 轮询状态"""
    license_key = _load_license_key()
    if not license_key:
        st.error("未检测到授权码，请先在配置中填写")
        return

    st.caption(f"授权码：{license_key[:7]}...{license_key[-4:]}")

    # 拉取套餐
    try:
        plans_resp = _session.get(f"{CREDIT_API_BASE}/recharge/plans", timeout=8)
        plans = plans_resp.json().get("plans", []) if plans_resp.status_code == 200 else []
    except Exception:
        plans = []
    if not plans:
        st.warning("无法获取套餐列表，请检查网络")
        plans = [
            {"id": "starter", "name": "基础包 100 积分", "money": "10.00", "credits": 100},
            {"id": "standard", "name": "标准包 300 积分", "money": "30.00", "credits": 300},
            {"id": "pro", "name": "进阶包 1000 积分", "money": "100.00", "credits": 1000},
        ]

    plan_options = {f"{p['name']} - ¥{p['money']}": p for p in plans}
    selected_label = st.radio("选择套餐", list(plan_options.keys()), key="rc_plan_select", horizontal=False)
    selected_plan = plan_options[selected_label]

    if st.button("立即充值", key="rc_pay_btn", use_container_width=True, type="primary"):
        try:
            resp = _session.post(
                f"{CREDIT_API_BASE}/recharge/create",
                json={"plan_id": selected_plan["id"]},
                headers={"Authorization": f"Bearer {license_key}"},
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json()
                st.session_state.rc_pay_url = data.get("pay_url", "")
                st.session_state.rc_order_no = data.get("out_trade_no", "")
                st.rerun()
            else:
                try:
                    msg = resp.json().get("detail", resp.text)
                except Exception:
                    msg = resp.text
                st.error(f"创建订单失败：{msg}")
        except Exception as exc:
            st.error(f"请求失败：{exc}")

    # 显示支付链接
    pay_url = st.session_state.get("rc_pay_url")
    order_no = st.session_state.get("rc_order_no")
    if pay_url:
        st.markdown("---")
        st.success("订单已创建，请点击下方按钮在新窗口完成支付")
        st.markdown(f"**订单号**：`{order_no}`")
        st.markdown(f'<a href="{_html.escape(pay_url)}" target="_blank" style="display:inline-block;padding:8px 16px;background:#6366F1;color:#fff;border-radius:6px;text-decoration:none;font-weight:600;">前往支付宝支付</a>', unsafe_allow_html=True)
        col_a, col_b = st.columns([1, 1])
        with col_a:
            if st.button("我已支付，刷新余额", key="rc_refresh_btn", use_container_width=True):
                get_credits_balance.clear()
                st.rerun()
        with col_b:
            # 轮询订单状态
            if order_no:
                try:
                    sresp = _session.get(
                        f"{CREDIT_API_BASE}/recharge/orders/{order_no}",
                        headers={"Authorization": f"Bearer {license_key}"},
                        timeout=8,
                    )
                    if sresp.status_code == 200:
                        sdata = sresp.json()
                        if sdata.get("status") == "paid":
                            st.success(f"支付成功！积分 +{sdata.get('credits', 0)}")
                        else:
                            st.info(f"订单状态：{sdata.get('status', 'pending')}")
                except Exception:
                    pass

    # 充值记录
    st.markdown("---")
    st.markdown("**最近充值记录**")
    try:
        oresp = _session.get(
            f"{CREDIT_API_BASE}/recharge/orders",
            headers={"Authorization": f"Bearer {license_key}"},
            timeout=8,
        )
        if oresp.status_code == 200:
            orders = oresp.json().get("orders", [])
            if orders:
                for o in orders[:5]:
                    status_color = "#34D399" if o["status"] == "paid" else "#FBBF24"
                    st.markdown(
                        f'<div style="display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid rgba(255,255,255,0.04);font-size:13px;color:#FFFFFF;">'
                        f'<span style="flex:1;">{_html.escape(str(o["plan_name"]))}</span>'
                        f'<span style="color:{status_color};font-weight:600;margin:0 12px;">{"已支付" if o["status"]=="paid" else "待支付"}</span>'
                        f'<span style="color:#D1D5DB;font-variant-numeric:tabular-nums;">¥{_html.escape(str(o["money"]))} / +{_html.escape(str(o["credits"]))}积分</span>'
                        f'</div>', unsafe_allow_html=True
                    )
            else:
                st.caption("暂无充值记录")
    except Exception:
        st.caption("无法加载充值记录")


# 菜单定义（模块级常量，避免 rerun 重复构造）
MENU_ITEMS = [
    {"id": "设备管理", "label": "AI员工群控管理"},
    {"id": "搜索与基础控制", "label": "AI搜索控制大模型"},
    {"id": "自定义执行功能选择", "label": "AI功能自主选项"},
    {"id": "自定义意向关键词", "label": "AI深度挖掘客户"},
    {"id": "作者私信策略", "label": "AI员工话术私信调整"},
    {"id": "流程控制", "label": "AI一键控制开关"},
    {"id": "AI截流获客策略", "label": "AI员工工作调整台"},
    {"id": "实时任务监控", "label": "AI员工工作动向"},
    {"id": "获客数据看板", "label": "AI获客面板员工走向"},
    {"id": "视频处理设置", "label": "视频处理设置"},
]


def _render_sidebar(device_status, license_info):
    """渲染侧边栏（在 fragment 外，仅顶层 rerun 时执行）"""
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

        for item in MENU_ITEMS:
            if st.button(item["label"], key=f"menu_{item['id']}", use_container_width=True):
                st.session_state.current_page = item["id"]
                st.rerun(scope="fragment")

        # 侧边栏底部：当前登录账号 + 退出登录
        st.markdown('<div class="sidebar-divider"></div>', unsafe_allow_html=True)
        _account_email = st.session_state.get("account_email", "")
        if _account_email:
            st.markdown(
                f'<div style="padding:6px 12px;color:var(--text-muted);font-size:12px;'
                f'margin-bottom:8px;text-align:center;">当前账号：<br/>{_account_email}</div>',
                unsafe_allow_html=True,
            )
        if st.button("退出登录", key="sb_logout", use_container_width=True):
            try:
                _session.post(f"{API_BASE_URL}/auth/logout", timeout=10)
            except Exception:
                pass
            st.session_state["account_logged_in"] = False
            st.session_state.pop("account_email", None)
            st.rerun()


@st.fragment
def _render_main_content():
    """主内容区 fragment - 仅局部 rerun，不重跑 CSS 和侧边栏（方案 B）"""
    render_douyin_page(st.session_state.current_page)


# ======================== 账号登录拦截 ========================
_AUTH_PAGE_CSS = """
<style>
/* 登录页容器：居中卡片 */
.auth-wrap {
    max-width: 440px;
    margin: 64px auto 0;
    background: var(--surface-2);
    border: 1px solid var(--border-default);
    border-radius: var(--radius-lg);
    padding: 40px 36px;
    box-shadow: 0 8px 32px rgba(0,0,0,0.4);
}
.auth-brand {
    text-align: center;
    margin-bottom: 28px;
}
.auth-brand-title {
    color: var(--text-primary);
    font-size: 26px;
    font-weight: 700;
    letter-spacing: 1px;
    margin: 0 0 6px;
}
.auth-brand-sub {
    color: var(--text-muted);
    font-size: 13px;
    margin: 0;
}
.auth-error {
    color: #FCA5A5;
    background: rgba(239,68,68,0.08);
    border: 1px solid rgba(239,68,68,0.25);
    border-radius: var(--radius-sm);
    padding: 10px 14px;
    margin: 10px 0 4px;
    font-size: 13px;
    line-height: 1.5;
}
.auth-foot {
    text-align: center;
    color: var(--text-subtle);
    font-size: 12px;
    margin-top: 24px;
}
/* tab 选中态用主色 */
div[data-baseweb="tab-list"] {
    gap: 8px;
}
div[data-baseweb="tab"] {
    color: var(--text-muted);
    font-size: 14px;
}
div[data-baseweb="tab"][aria-selected="true"] {
    color: var(--accent);
}
/* 让登录页的输入框/按钮宽度一致 */
.auth-wrap .stVerticalBlock { gap: 4px; }
</style>
"""


def _ensure_logged_in() -> bool:
    """检查登录态。已登录返回 True，结果缓存在 session_state 避免每次 rerun 都请求。"""
    if st.session_state.get("account_logged_in") is True:
        return True
    try:
        resp = _session.get(f"{API_BASE_URL}/auth/check", timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("logged_in"):
                st.session_state["account_logged_in"] = True
                st.session_state["account_email"] = (data.get("data") or {}).get("email", "")
                return True
    except Exception:
        pass
    st.session_state["account_logged_in"] = False
    return False


def _render_auth_page():
    """渲染登录/注册页（未登录时显示）。"""
    st.markdown(_AUTH_PAGE_CSS, unsafe_allow_html=True)
    st.markdown('<div class="auth-wrap">', unsafe_allow_html=True)
    st.markdown(
        '<div class="auth-brand">'
        '<h1 class="auth-brand-title">抖音AI群控</h1>'
        '<p class="auth-brand-sub">请登录账号后进入管理面板</p>'
        '</div>',
        unsafe_allow_html=True,
    )

    tab_login, tab_register = st.tabs(["登录", "注册"])

    # -------------------- 登录 --------------------
    with tab_login:
        with st.form("auth_login_form", clear_on_submit=False):
            login_email = st.text_input("邮箱", key="login_email", placeholder="请输入注册邮箱")
            login_password = st.text_input("密码", type="password", key="login_password", placeholder="请输入密码")
            login_submit = st.form_submit_button("登录", use_container_width=True, type="primary")

        if login_submit:
            if not login_email.strip() or not login_password:
                st.markdown('<div class="auth-error">请填写邮箱和密码</div>', unsafe_allow_html=True)
            else:
                try:
                    resp = _session.post(f"{API_BASE_URL}/auth/login", json={
                        "email": login_email.strip(),
                        "password": login_password,
                    }, timeout=20)
                    data = resp.json()
                    if data.get("success"):
                        st.session_state["account_logged_in"] = True
                        st.session_state["account_email"] = (data.get("data") or {}).get("user", {}).get("email", "")
                        st.rerun()
                    else:
                        st.markdown(f'<div class="auth-error">{_html.escape(str(data.get("message", "登录失败")))}</div>',
                                    unsafe_allow_html=True)
                except Exception as e:
                    st.markdown(f'<div class="auth-error">网络错误：{_html.escape(str(e))}</div>', unsafe_allow_html=True)

    # -------------------- 注册 --------------------
    with tab_register:
        with st.form("auth_register_form", clear_on_submit=False):
            reg_email = st.text_input("邮箱", key="reg_email", placeholder="请输入邮箱")
            reg_password = st.text_input("密码", type="password", key="reg_password", placeholder="至少 6 位")
            reg_password2 = st.text_input("确认密码", type="password", key="reg_password2", placeholder="再次输入密码")
            reg_submit = st.form_submit_button("注册并登录", use_container_width=True, type="primary")

        if reg_submit:
            if not reg_email.strip() or not reg_password:
                st.markdown('<div class="auth-error">请填写邮箱和密码</div>', unsafe_allow_html=True)
            elif len(reg_password) < 6:
                st.markdown('<div class="auth-error">密码至少 6 位</div>', unsafe_allow_html=True)
            elif reg_password != reg_password2:
                st.markdown('<div class="auth-error">两次输入的密码不一致</div>', unsafe_allow_html=True)
            else:
                try:
                    resp = _session.post(f"{API_BASE_URL}/auth/register", json={
                        "email": reg_email.strip(),
                        "password": reg_password,
                    }, timeout=20)
                    data = resp.json()
                    if data.get("success"):
                        st.session_state["account_logged_in"] = True
                        st.session_state["account_email"] = (data.get("data") or {}).get("user", {}).get("email", "")
                        st.rerun()
                    else:
                        st.markdown(f'<div class="auth-error">{_html.escape(str(data.get("message", "注册失败")))}</div>',
                                    unsafe_allow_html=True)
                except Exception as e:
                    st.markdown(f'<div class="auth-error">网络错误：{_html.escape(str(e))}</div>', unsafe_allow_html=True)

    st.markdown(
        '<p class="auth-foot">注册即代表同意：账号仅用于本系统登录门禁，授权码需单独配置</p>',
        unsafe_allow_html=True,
    )
    st.markdown('</div>', unsafe_allow_html=True)


def main():
    # 登录拦截：未登录则只渲染登录/注册页，不进入面板
    if not _ensure_logged_in():
        _render_auth_page()
        return

    if "current_page" not in st.session_state:
        st.session_state.current_page = "首页"

    if "nav" in st.query_params:
        if st.query_params["nav"] == "home":
            st.session_state.current_page = "首页"
        st.query_params.pop("nav", None)

    # 数据获取（命中缓存时 < 1ms，方案 A）
    device_status = get_device_status()
    license_info = get_license_status()

    # 侧边栏
    _render_sidebar(device_status, license_info)

    # 实时查询积分余额（10s 缓存）
    balance = get_credits_balance()
    balance_str = f"{balance:,.2f}" if balance >= 100 else f"{balance:.3f}"

    st.markdown(f"""
    <div class="top-toolbar">
        <div class="toolbar-credit">
            <span class="toolbar-credit-label">我的积分</span>
            <span class="toolbar-credit-value">{balance_str}</span>
        </div>
        <div class="toolbar-divider"></div>
        <button class="toolbar-icon-btn" onclick="return false;" title="设置">
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"></path>
                <circle cx="12" cy="12" r="3"></circle>
            </svg>
        </button>
    </div>
    """, unsafe_allow_html=True)

    # 充值弹窗
    st.markdown('<div class="rc-anchor"></div>', unsafe_allow_html=True)
    if st.button("充值", key="recharge_open_btn", help="点击打开充值面板"):
        _render_recharge_dialog()

    # 移动充值按钮到工具栏（JavaScript DOM 操作）
    import streamlit.components.v1 as components
    components.html("""
    <script>
    (function() {
        function moveBtn() {
            var anchor = parent.document.querySelector('.rc-anchor');
            var toolbar = parent.document.querySelector('.top-toolbar');
            var divider = toolbar ? toolbar.querySelector('.toolbar-divider') : null;
            if (!anchor || !toolbar || !divider) return false;
            var container = anchor.closest('[data-testid="stElementContainer"]');
            if (!container) return false;
            var btnContainer = container.nextElementSibling;
            if (!btnContainer || !btnContainer.querySelector('[data-testid="stButton"]')) return false;
            var wrap = toolbar.querySelector('.toolbar-recharge-wrap');
            if (!wrap) {
                wrap = parent.document.createElement('div');
                wrap.className = 'toolbar-recharge-wrap';
                divider.after(wrap);
            }
            if (wrap.children.length === 0) {
                wrap.appendChild(btnContainer);
                var btn = btnContainer.querySelector('button');
                if (btn) {
                    btn.style.height = '30px';
                    btn.style.minHeight = '30px';
                    btn.style.padding = '0 14px';
                    btn.style.fontSize = '12px';
                    btn.style.fontWeight = '600';
                    btn.style.lineHeight = '1';
                    var innerDiv = btn.querySelector('div');
                    if (innerDiv) innerDiv.style.height = 'auto';
                }
            }
            var origContainer = anchor.closest('[data-testid="stElementContainer"]');
            if (origContainer) origContainer.style.display = 'none';
            return true;
        }
        var tries = 0;
        var timer = setInterval(function() {
            tries++;
            if (moveBtn() || tries > 80) clearInterval(timer);
        }, 150);
    })();
    </script>
    """, height=0, width=0)

    # 主内容区 - fragment 局部刷新（方案 B）
    _render_main_content()


if __name__ == "__main__":
    main()
