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
CREDIT_API_BASE = "https://lcjx.yun/social-ai-credit-api"


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


def get_credits_balance() -> float:
    """实时查询当前授权码的积分余额，复用真实 machine_id 避免占用额外绑定名额"""
    key = _load_license_key()
    if not key:
        return 0.0
    try:
        # 复用 social_license 的真实 machine_id，避免用假 ID 占用绑定名额
        import sys
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from social_license import get_machine_id
        machine_id = get_machine_id()
        resp = requests.post(
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
        plans_resp = requests.get(f"{CREDIT_API_BASE}/recharge/plans", timeout=8)
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
            resp = requests.post(
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
        st.markdown(f'<a href="{pay_url}" target="_blank" style="display:inline-block;padding:8px 16px;background:#6366F1;color:#fff;border-radius:6px;text-decoration:none;font-weight:600;">前往支付宝支付</a>', unsafe_allow_html=True)
        col_a, col_b = st.columns([1, 1])
        with col_a:
            if st.button("我已支付，刷新余额", key="rc_refresh_btn", use_container_width=True):
                st.rerun()
        with col_b:
            # 轮询订单状态
            if order_no:
                try:
                    sresp = requests.get(
                        f"{CREDIT_API_BASE}/recharge/status",
                        params={"out_trade_no": order_no},
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
        oresp = requests.get(
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
                        f'<div style="display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid rgba(255,255,255,0.06);font-size:13px;color:#E5E7EB;">'
                        f'<span style="flex:1;">{o["plan_name"]}</span>'
                        f'<span style="color:{status_color};font-weight:600;margin:0 12px;">{"已支付" if o["status"]=="paid" else "待支付"}</span>'
                        f'<span style="color:#9CA3AF;">¥{o["money"]} / +{o["credits"]}积分</span>'
                        f'</div>', unsafe_allow_html=True
                    )
            else:
                st.caption("暂无充值记录")
    except Exception:
        st.caption("无法加载充值记录")


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

        /* ============================================ */
        /* 右上角工具栏 */
        /* ============================================ */
        .top-toolbar {
            position: fixed;
            top: 14px;
            right: 20px;
            z-index: 9999;
            display: flex;
            align-items: center;
            gap: 10px;
            background: rgba(22, 27, 40, 0.85);
            backdrop-filter: blur(12px);
            -webkit-backdrop-filter: blur(12px);
            border: 1px solid var(--card-border);
            border-radius: 10px;
            padding: 6px 8px 6px 14px;
            box-shadow: 0 4px 16px rgba(0,0,0,0.35);
        }

        .toolbar-credit {
            display: flex;
            flex-direction: column;
            align-items: flex-end;
            gap: 1px;
            padding-right: 4px;
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
            color: var(--primary);
            font-variant-numeric: tabular-nums;
            letter-spacing: -0.01em;
            line-height: 1.2;
        }

        .toolbar-divider {
            width: 1px;
            height: 28px;
            background: var(--card-border);
            margin: 0 2px;
        }

        .toolbar-recharge-btn {
            background: var(--primary) !important;
            color: #FFFFFF !important;
            border: none !important;
            border-radius: 6px !important;
            padding: 6px 12px !important;
            font-size: 12px !important;
            font-weight: 600 !important;
            cursor: pointer !important;
            transition: all 0.12s ease !important;
            height: auto !important;
            min-height: unset !important;
            line-height: 1.4 !important;
        }

        .toolbar-recharge-btn:hover {
            background: var(--primary-hover) !important;
            transform: translateY(-0.5px) !important;
            box-shadow: 0 2px 8px rgba(99,102,241,0.4) !important;
        }

        .toolbar-recharge-btn:active {
            background: var(--primary-active) !important;
            transform: translateY(0) !important;
        }

        .toolbar-icon-btn {
            background: transparent !important;
            border: 1px solid transparent !important;
            border-radius: 6px !important;
            width: 32px !important;
            height: 32px !important;
            min-width: unset !important;
            min-height: unset !important;
            padding: 0 !important;
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            cursor: pointer !important;
            transition: all 0.12s ease !important;
            color: var(--text-secondary) !important;
        }

        .toolbar-icon-btn:hover {
            background: rgba(99,102,241,0.1) !important;
            border-color: rgba(99,102,241,0.25) !important;
            color: var(--primary) !important;
        }

        .toolbar-icon-btn:active {
            background: rgba(99,102,241,0.18) !important;
        }

        .toolbar-icon-btn svg {
            width: 16px;
            height: 16px;
            stroke-width: 2;
        }

        /* ============================================ */
        /* 充值按钮 - 移到工具栏中 */
        /* ============================================ */
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
            background: var(--primary) !important;
            color: #FFFFFF !important;
            border: none !important;
            border-radius: 6px !important;
            padding: 0 14px !important;
            font-size: 12px !important;
            font-weight: 600 !important;
            height: 30px !important;
            min-height: 30px !important;
            line-height: 1 !important;
            box-shadow: 0 1px 3px rgba(99,102,241,0.3) !important;
            margin: 0 !important;
            width: auto !important;
            transition: all 0.12s ease !important;
        }

        .top-toolbar .toolbar-recharge-wrap button:hover {
            background: var(--primary-hover) !important;
            box-shadow: 0 2px 8px rgba(99,102,241,0.4) !important;
            color: #FFFFFF !important;
        }

        .top-toolbar .toolbar-recharge-wrap button p {
            color: #FFFFFF !important;
            font-size: 12px !important;
            font-weight: 600 !important;
            margin: 0 !important;
            line-height: 1 !important;
        }

        /* ============================================ */
        /* 充值弹窗暗色主题 */
        /* ============================================ */
        div[role="dialog"] {
            background: var(--card-bg) !important;
            border: 1px solid var(--card-border) !important;
            border-radius: var(--radius-lg) !important;
            box-shadow: 0 20px 60px rgba(0,0,0,0.5) !important;
        }

        div[role="dialog"] h2,
        div[role="dialog"] [data-testid="stDialog"] header {
            color: var(--text-primary) !important;
            border-bottom: 1px solid var(--card-border) !important;
        }

        div[role="dialog"] p,
        div[role="dialog"] span,
        div[role="dialog"] div,
        div[role="dialog"] label,
        div[role="dialog"] small {
            color: var(--text-primary) !important;
        }

        div[role="dialog"] .stMarkdown p,
        div[role="dialog"] .stMarkdown span,
        div[role="dialog"] .stMarkdown div {
            color: var(--text-primary) !important;
        }

        div[role="dialog"] [data-testid="stCaptionContainer"],
        div[role="dialog"] [data-testid="stCaptionContainer"] p,
        div[role="dialog"] [data-testid="stCaptionContainer"] span {
            color: var(--text-muted) !important;
        }

        div[role="dialog"] [data-baseweb="radio"] {
            background: var(--input-bg) !important;
            border-color: var(--input-border) !important;
        }

        div[role="dialog"] [data-baseweb="radio"][aria-checked="true"] {
            background: var(--primary) !important;
            border-color: var(--primary) !important;
        }

        div[role="dialog"] [role="radiogroup"] label {
            color: var(--text-primary) !important;
        }

        div[role="dialog"] hr {
            border-color: var(--card-border) !important;
        }

        div[role="dialog"] [data-testid="stAlertContainer"] p {
            color: inherit !important;
        }

        div[role="dialog"] code {
            background: var(--input-bg) !important;
            color: var(--primary) !important;
            padding: 2px 6px !important;
            border-radius: 4px !important;
            font-size: 12px !important;
        }
    </style>
    """, unsafe_allow_html=True)

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
        {"id": "AI截流获客策略", "label": "AI员工工作调整台"},
        {"id": "视频处理设置", "label": "视频处理设置"},
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

    # 实时查询积分余额
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

    # 充值弹窗（浮动模态窗口）- 按钮定位到工具栏
    st.markdown('<div class="rc-anchor"></div>', unsafe_allow_html=True)
    if st.button("充值", key="recharge_open_btn", help="点击打开充值面板"):
        _render_recharge_dialog()

    render_douyin_page(st.session_state.current_page)


if __name__ == "__main__":
    main()
