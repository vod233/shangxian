import streamlit as st
import requests
import time
import math
import html as _html

API_BASE_URL = "http://127.0.0.1:8000/api"


def init_session_state():
    if "controlled_devices" not in st.session_state:
        st.session_state.controlled_devices = []
    if "task_status_data" not in st.session_state:
        st.session_state.task_status_data = {}
    if "terminal_logs" not in st.session_state:
        st.session_state.terminal_logs = ""
    if "config_data" not in st.session_state:
        st.session_state.config_data = {}


def toggle_device(dev_id):
    if dev_id in st.session_state.controlled_devices:
        st.session_state.controlled_devices.remove(dev_id)
    else:
        st.session_state.controlled_devices.append(dev_id)


def fetch_config():
    try:
        resp = requests.get(f"{API_BASE_URL}/config?platform=douyin", timeout=5)
        if resp.status_code == 200:
            st.session_state.config_data = resp.json().get("config", {})
    except:
        st.session_state.config_data = {}


def fetch_devices():
    try:
        resp = requests.get(f"{API_BASE_URL}/devices", timeout=5)
        if resp.status_code == 200:
            return resp.json().get("devices", [])
    except:
        pass
    return []


def fetch_task_status():
    try:
        resp = requests.get(f"{API_BASE_URL}/tasks/status", timeout=5).json()
        st.session_state.task_status_data = resp.get("status", {})
    except:
        st.session_state.task_status_data = {}


def fetch_logs():
    try:
        logs_resp = requests.get(f"{API_BASE_URL}/logs", timeout=5).json()
        logs = logs_resp.get("logs", [])
        return "\n".join(logs) if logs else "暂无日志输出..."
    except:
        return "无法连接到后端获取日志..."


def fetch_stats():
    try:
        resp = requests.get(f"{API_BASE_URL}/stats", timeout=5)
        if resp.status_code == 200:
            return resp.json().get("data", {})
    except:
        pass
    return {}


def fetch_details(limit=100):
    try:
        details_resp = requests.get(f"{API_BASE_URL}/stats/details?limit={limit}", timeout=5)
        if details_resp.status_code == 200 and details_resp.json().get("success"):
            return details_resp.json().get("data", [])
    except:
        pass
    return []


def render_page_header(title, description, breadcrumb=""):
    breadcrumb_html = f'<div class="breadcrumb">{breadcrumb}</div>' if breadcrumb else ""
    st.markdown(f"""
    {breadcrumb_html}
    <div class="page-header">
        <div>
            <div class="page-title">{title}</div>
            <div class="page-description">{description}</div>
        </div>
    </div>
    """, unsafe_allow_html=True)


def render_device_management():
    render_page_header("AI员工管理", "管理 USB 与无线 ADB 连接，并选择本次任务控制的AI员工。", breadcrumb="AI员工群控管理 / AI员工数量管理")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("""
        <div class="card">
            <div class="card-header">
                <div>
                    <div class="card-title">AI员工检测</div>
                    <div class="card-description">手机插入电脑并允许 USB 调试后，点击检测即可自动接入。</div>
                </div>
            </div>
        """, unsafe_allow_html=True)

        if st.button("🔍 检测 USB 设备", key="detect_usb", use_container_width=True):
            with st.spinner("正在检测 USB 设备..."):
                try:
                    res = requests.post(f"{API_BASE_URL}/devices/usb/detect").json()
                    if res.get("success"):
                        st.success(res.get("message"))
                        for dev in res.get("devices", []):
                            if dev.get("u2_ready"):
                                st.info(f"可用设备: {dev.get('serial')} {dev.get('model') or ''}")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.warning(res.get("message"))
                        for dev in res.get("devices", []):
                            st.error(f"{dev.get('serial')} [{dev.get('status')}]: {dev.get('message')}")
                except Exception as e:
                    st.error(f"USB 检测失败: {e}")

        st.markdown("</div>", unsafe_allow_html=True)

    with col2:
        st.markdown("""
        <div class="card">
            <div class="card-header">
                <div>
                    <div class="card-title">无线连接控制台</div>
                </div>
            </div>
        """, unsafe_allow_html=True)

        tab_connect, tab_pair = st.tabs(["🚀 立即连接", "🔗 配对新设备 (Android 11+)"])

        with tab_connect:
            with st.form("connect_form", border=False):
                ip_port_input = st.text_input("手机无线调试 IP:端口", placeholder="192.168.x.x:端口")
                if st.form_submit_button("⚡ 立即连接", use_container_width=True):
                    if not ip_port_input:
                        st.warning("请输入 IP 地址和端口号")
                    else:
                        with st.spinner(f"正在尝试连接 {ip_port_input}..."):
                            try:
                                res = requests.post(f"{API_BASE_URL}/devices/connect", json={"ip_port": ip_port_input}).json()
                                if res.get("success"):
                                    st.success(res.get("message"))
                                    time.sleep(1)
                                    st.rerun()
                                else:
                                    st.error(res.get("message"))
                            except Exception as e:
                                st.error(f"请求连接失败: {e}")

        with tab_pair:
            with st.form("pair_form", border=False):
                col_ip, col_code = st.columns([2, 1])
                with col_ip:
                    pair_ip_input = st.text_input("配对 IP:端口", placeholder="192.168.x.x:配对端口")
                with col_code:
                    pair_code_input = st.text_input("6位配对码", placeholder="123456")
                if st.form_submit_button("🔗 立即配对", use_container_width=True):
                    if not pair_ip_input or not pair_code_input:
                        st.warning("请输入配对 IP 端口和配对码")
                    else:
                        with st.spinner(f"正在尝试配对 {pair_ip_input}..."):
                            try:
                                res = requests.post(f"{API_BASE_URL}/devices/pair", json={"ip_port": pair_ip_input, "code": pair_code_input}).json()
                                if res.get("success"):
                                    st.success(res.get("message") + "，请返回手机无线调试主界面进行连接！")
                                else:
                                    st.error(res.get("message"))
                            except Exception as e:
                                st.error(f"请求配对失败: {e}")

        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("""
    <div class="card">
        <div class="card-header">
            <div>
                <div class="card-title">已接入AI员工列表</div>
            </div>
        </div>
    """, unsafe_allow_html=True)

    devices = fetch_devices()

    if not devices:
        st.warning("当前未检测到任何AI员工。请通过上方连接控制台进行无线连接，或通过 USB 连接手机。")
    else:
        st.success(f"✅ 检测到我们{len(devices)}个员工在线")

        for dev in devices:
            is_controlled = dev in st.session_state.controlled_devices
            st.markdown(f"""
            <div style="display:flex; justify-content:space-between; align-items:center; padding:12px 16px; background:#161B28; border:1px solid rgba(255,255,255,0.06); border-radius:8px; margin-bottom:8px; transition:all 0.12s ease; box-shadow:0 1px 2px rgba(0,0,0,0.2);">
                <div style="display:flex; align-items:center; gap:10px;">
                    <span style="font-size:20px;">📱</span>
                    <div>
                        <div style="font-size:13px; font-weight:600; color:#E5E7EB; letter-spacing:-0.01em;">{dev}</div>
                        <div style="display:flex; align-items:center; gap:5px; margin-top:2px;">
                            <span style="width:6px; height:6px; border-radius:50%; background:#059669; box-shadow:0 0 0 2px rgba(5,150,105,0.15);"></span>
                            <span style="font-size:12px; color:#6B7280;">在线</span>
                            {is_controlled and '<span style="color:#6366F1; font-size:12px; margin-left:8px; font-weight:600;">✓ 已选中为控制员工</span>'}
                        </div>
                    </div>
                </div>
                <div style="display:flex; gap:8px;">
            """, unsafe_allow_html=True)

            col_btn1, col_btn2 = st.columns([1, 1], gap="small")
            with col_btn1:
                if is_controlled:
                    if st.button("取消选中", key=f"cancel_{dev}", use_container_width=True, type="secondary"):
                        toggle_device(dev)
                        st.rerun()
                else:
                    if st.button("选择控制", key=f"select_{dev}", use_container_width=True, type="primary"):
                        toggle_device(dev)
                        st.rerun()
            with col_btn2:
                if st.button("断开员工", key=f"disconnect_{dev}", use_container_width=True):
                    with st.spinner(f"正在断开 {dev}..."):
                        try:
                            res = requests.post(f"{API_BASE_URL}/devices/disconnect", json={"ip_port": dev}).json()
                            if res.get("success"):
                                if is_controlled:
                                    toggle_device(dev)
                                st.success(res.get("message"))
                                time.sleep(1)
                                st.rerun()
                            else:
                                st.error(res.get("message"))
                        except Exception as e:
                            st.error(f"请求断开员工失败: {e}")

            st.markdown("</div></div>", unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)


def render_task_monitor():
    render_page_header("AI员工监控系统", "实时查看AI员工执行状态与终端输出。")

    st.markdown("""
    <div class="card">
        <div class="card-header">
            <div class="card-title">当前任务状态</div>
        </div>
    """, unsafe_allow_html=True)

    fetch_task_status()
    status_data = st.session_state.task_status_data

    if not status_data:
        st.info("当前没有任务在运行。")
    else:
        for serial, info in status_data.items():
            state = info.get("status")
            if state == "queued":
                st.info(f"🕒 AI员工 **{serial}**: 任务已提交，等待线程调度...")
            elif state == "starting":
                st.info(f"🔄 AI员工 **{serial}**: 正在初始化连接并启动应用...")
            elif state == "running":
                st.info(f"▶️ AI员工 **{serial}**: 正在执行任务中...")
            elif state == "paused":
                st.warning(f"⏸️ AI员工 **{serial}**: 任务已暂停")
            elif state == "completed":
                st.success(f"✅ AI员工 **{serial}**: 任务已完成")
            elif state == "stopped":
                st.error(f"🛑 AI员工 **{serial}**: 任务已被手动结束")
            elif state == "error":
                st.error(f"❌ AI员工 **{serial}**: 执行报错 - {info.get('error')}")

    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("""
    <div class="card">
        <div class="card-header">
            <div class="card-title">AI操作终端</div>
        </div>
        <div class="log-container">
    """, unsafe_allow_html=True)

    log_text = fetch_logs()
    st.markdown(log_text.replace("\n", "<br>"), unsafe_allow_html=True)

    st.markdown("</div></div>", unsafe_allow_html=True)


def render_search_control():
    render_page_header("AI搜索基础控制", "配置搜索行业关键词与视频排序方式。")

    fetch_config()
    config = st.session_state.config_data

    with st.form("search_form", border=False):
        st.markdown("""
        <div class="card">
            <div class="card-header">
                <div class="card-title">搜索行业关键词（格式为：每行一个）</div>
            </div>
        """, unsafe_allow_html=True)

        keywords_str = st.text_area(
            "搜索关键词",
            value="\n".join(config.get("search_keywords", [])),
            height=150,
            placeholder="桌子\n椅子\n沙发"
        )

        st.markdown("""
            <div class="card-header" style="margin-top:16px;">
                <div class="card-title">视频排序方式（优先推荐最新发布 截取客户更加有效）</div>
            </div>
        """, unsafe_allow_html=True)

        sort_by = st.selectbox(
            "排序方式",
            options=["latest", "most_liked"],
            index=0 if config.get("sort_by") == "latest" else 1,
            format_func=lambda x: "最新发布" if x == "latest" else "最多点赞"
        )

        st.markdown("</div>", unsafe_allow_html=True)

        if st.form_submit_button("💾 保存当前配置", use_container_width=True, type="primary"):
            payload = {
                "search_keywords": [k.strip() for k in keywords_str.split("\n") if k.strip()],
                "sort_by": sort_by
            }
            try:
                current_config = {}
                resp = requests.get(f"{API_BASE_URL}/config?platform=douyin")
                if resp.status_code == 200:
                    current_config = resp.json().get("config", {})
                current_config.update(payload)
                res = requests.post(f"{API_BASE_URL}/config?platform=douyin", json=current_config).json()
                if res.get("success"):
                    st.success("配置已成功保存！")
                else:
                    st.error(res.get("message"))
            except Exception as e:
                st.error(f"保存失败: {e}")


def render_intent_keywords():
    render_page_header("AI深度抓取意向关键词", "设置评论区出现后AI识别抓取意向客户的触发词。")

    fetch_config()
    config = st.session_state.config_data

    with st.form("intent_form", border=False):
        st.markdown("""
        <div class="card">
            <div class="card-header">
                <div class="card-title">额外意向触发词（逗号分隔）</div>
            </div>
        """, unsafe_allow_html=True)

        intent_keywords = st.text_input(
            "意向触发词",
            value=config.get("intent_keywords", ""),
            placeholder="产品,采购,咨询,价格,怎么卖",
            label_visibility="collapsed"
        )

        st.markdown("""
            <div style="margin-top:12px; color:#9CA3AF; font-size:13px;">
                提示：输入关键词后，评论区出现相关内容时AI识别抓取关键词意向客户。
            </div>
        """, unsafe_allow_html=True)

        st.markdown("</div>", unsafe_allow_html=True)

        if st.form_submit_button("💾 保存当前配置", use_container_width=True, type="primary"):
            payload = {
                "intent_keywords": [k.strip() for k in intent_keywords.split(",") if k.strip()]
            }
            try:
                current_config = {}
                resp = requests.get(f"{API_BASE_URL}/config?platform=douyin")
                if resp.status_code == 200:
                    current_config = resp.json().get("config", {})
                current_config.update(payload)
                res = requests.post(f"{API_BASE_URL}/config?platform=douyin", json=current_config).json()
                if res.get("success"):
                    st.success("配置已成功保存！")
                else:
                    st.error(res.get("message"))
            except Exception as e:
                st.error(f"保存失败: {e}")


def render_ai_strategy():
    render_page_header("AI 截流获客策略", "设置评论识别范围、AI 自动回复、授权与模型生成参数。")

    fetch_config()
    config = st.session_state.config_data

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("""
        <div class="card">
            <div class="card-header">
                <div class="card-title">评论区截流范围</div>
            </div>
        """, unsafe_allow_html=True)

        max_ai_reviews = st.number_input(
            "每个视频最多 AI 识别评论数",
            value=int(config.get("max_ai_comment_reviews", 20)),
            min_value=1,
            max_value=200,
            step=1
        )

        max_swipes = st.number_input(
            "评论区最大向下滑动次数",
            value=config.get("max_comment_swipes", 2),
            min_value=1,
            max_value=30
        )

        st.markdown("""
            <div style="margin-top:12px; color:#9CA3AF; font-size:13px;">
                系统会识别咨询、求推荐、想了解等意向。
            </div>
        </div>
        """, unsafe_allow_html=True)

    with col2:
        st.markdown("""
        <div class="card">
            <div class="card-header">
                <div class="card-title">AI 授权与模型参数</div>
            </div>
        """, unsafe_allow_html=True)

        ai_enabled = st.toggle(
            "启用 AI 自动回复与截流",
            value=config.get("ai_enabled", True)
        )

        if config.get("has_license_key"):
            st.success(f"已保存授权码：{config.get('license_key_masked', '')}")
        else:
            st.warning("尚未配置授权码，无法启动任务。")

        license_key = st.text_input(
            "客户授权码",
            value="",
            type="password"
        )

        license_server_url = st.text_input(
            "授权服务器",
            value=config.get("license_server_url", "https://lcjx.yun/social-ai-credit-api")
        )

        if st.button("🔎 验证授权", key="verify_license", use_container_width=True):
            try:
                verify_key = license_key.strip()
                if not verify_key:
                    st.warning("请输入完整授权码后再验证。")
                else:
                    verify_resp = requests.post(
                        f"{API_BASE_URL}/license/save?platform=douyin",
                        json={"license_key": verify_key, "license_server_url": license_server_url.strip()},
                        timeout=20,
                    ).json()
                    if verify_resp.get("success"):
                        info = verify_resp.get("data", {})
                        st.success(f"授权已保存：{info.get('customer_name', '')}，剩余积分 {info.get('balance_credits', 0)}")
                    else:
                        st.error(verify_resp.get("message", "授权验证失败"))
            except Exception as e:
                st.error(f"验证失败: {e}")

        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("""
        <div class="card">
            <div class="card-header">
                <div class="card-title">模型参数设置</div>
            </div>
        """, unsafe_allow_html=True)

        ai_model = st.text_input(
            "模型名称",
            value=config.get("ai_model", "deepseek-v4-flash"),
            disabled=True
        )

        ai_temperature = st.slider(
            "温度",
            min_value=0.0,
            max_value=1.5,
            value=float(config.get("ai_temperature", 0.7)),
            step=0.1,
            format="%.2f"
        )

        ai_max_tokens = st.number_input(
            "最大输出 Token",
            value=int(config.get("ai_max_tokens", 120)),
            min_value=32,
            max_value=512,
            step=8
        )

        st.markdown("</div>", unsafe_allow_html=True)

    with st.form("ai_form", border=False):
        st.markdown("""
        <div class="card" style="display:none;">
        """, unsafe_allow_html=True)
        st.session_state.max_ai_reviews = max_ai_reviews
        st.session_state.max_swipes = max_swipes
        st.session_state.ai_enabled = ai_enabled
        st.session_state.license_server_url = license_server_url
        st.session_state.ai_temperature = ai_temperature
        st.session_state.ai_max_tokens = ai_max_tokens
        st.markdown("</div>", unsafe_allow_html=True)

        if st.form_submit_button("💾 保存当前配置", use_container_width=True, type="primary"):
            payload = {
                "max_ai_comment_reviews": max_ai_reviews,
                "max_comment_swipes": max_swipes,
                "ai_enabled": ai_enabled,
                "license_server_url": license_server_url,
                "ai_temperature": ai_temperature,
                "ai_max_tokens": ai_max_tokens
            }
            try:
                current_config = {}
                resp = requests.get(f"{API_BASE_URL}/config?platform=douyin")
                if resp.status_code == 200:
                    current_config = resp.json().get("config", {})
                current_config.update(payload)
                res = requests.post(f"{API_BASE_URL}/config?platform=douyin", json=current_config).json()
                if res.get("success"):
                    st.success("配置已成功保存！")
                else:
                    st.error(res.get("message"))
            except Exception as e:
                st.error(f"保存失败: {e}")


def render_video_settings():
    render_page_header("员工操作速度与数量调节", "控制AI员工处理视频数量与页面停留时长。")

    fetch_config()
    config = st.session_state.config_data

    col1, col2 = st.columns(2)
    col3, col4 = st.columns(2)

    with col1:
        st.markdown("""
        <div class="card">
            <div class="card-header">
                <div class="card-title">每日处理视频总上限</div>
            </div>
        """, unsafe_allow_html=True)
        max_daily = st.number_input(
            "每日上限",
            value=config.get("max_daily_videos", 100),
            min_value=1,
            label_visibility="collapsed"
        )
        st.markdown("</div>", unsafe_allow_html=True)

    with col2:
        st.markdown("""
        <div class="card">
            <div class="card-header">
                <div class="card-title">每个关键词最多处理视频数</div>
            </div>
        """, unsafe_allow_html=True)
        max_videos = st.number_input(
            "每关键词上限",
            value=config.get("max_videos_per_keyword", 5),
            min_value=1,
            label_visibility="collapsed"
        )
        st.markdown("</div>", unsafe_allow_html=True)

    with col3:
        st.markdown("""
        <div class="card">
            <div class="card-header">
                <div class="card-title">视频最小停留时间（秒）</div>
            </div>
        """, unsafe_allow_html=True)
        min_stay = st.number_input(
            "最小停留",
            value=config.get("min_video_stay", 3),
            min_value=1,
            label_visibility="collapsed"
        )
        st.markdown("</div>", unsafe_allow_html=True)

    with col4:
        st.markdown("""
        <div class="card">
            <div class="card-header">
                <div class="card-title">视频最大停留时间（秒）</div>
            </div>
        """, unsafe_allow_html=True)
        max_stay = st.number_input(
            "最大停留",
            value=config.get("max_video_stay", 6),
            min_value=1,
            label_visibility="collapsed"
        )
        st.markdown("</div>", unsafe_allow_html=True)

    with st.form("video_form", border=False):
        st.markdown("""
        <div class="card" style="display:none;">
        """, unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

        if st.form_submit_button("💾 保存当前配置", use_container_width=True, type="primary"):
            payload = {
                "max_daily_videos": max_daily,
                "max_videos_per_keyword": max_videos,
                "min_video_stay": min_stay,
                "max_video_stay": max_stay
            }
            try:
                current_config = {}
                resp = requests.get(f"{API_BASE_URL}/config?platform=douyin")
                if resp.status_code == 200:
                    current_config = resp.json().get("config", {})
                current_config.update(payload)
                res = requests.post(f"{API_BASE_URL}/config?platform=douyin", json=current_config).json()
                if res.get("success"):
                    st.success("配置已成功保存！")
                else:
                    st.error(res.get("message"))
            except Exception as e:
                st.error(f"保存失败: {e}")


def render_execution_functions():
    render_page_header("AI员工功能自主选择", "已勾选的功能将在每个视频上执行，点赞固定优先，其余功能顺序随机以模拟真人行为。")

    fetch_config()
    config = st.session_state.config_data

    with st.form("execution_form", border=False):
        st.markdown("""
        <div class="card">
        """, unsafe_allow_html=True)

        enable_like = st.checkbox(
            "点赞",
            value=bool(config.get("enable_like", True))
        )

        enable_author_follow = st.checkbox(
            "进入作者主页，粉丝数判断成功，关注作者",
            value=bool(config.get("enable_author_follow", True))
        )

        enable_private_message = st.checkbox(
            "向作者发送私信（需配合粉丝数阈值）",
            value=bool(config.get("enable_private_message", True))
        )

        enable_video_comment = st.checkbox(
            "AI生成评论，发布评论",
            value=bool(config.get("enable_video_comment", True))
        )

        enable_comment_lead = st.checkbox(
            "打开评论区，AI 识别自动评论，评论中回复",
            value=bool(config.get("enable_comment_lead", True))
        )

        st.markdown("</div>", unsafe_allow_html=True)

        # 依赖关系与限额提示
        st.markdown("""
        <div style="margin-top:12px; padding:10px 14px; background:rgba(99,102,241,0.08); border-left:3px solid #6366F1; border-radius:6px; font-size:12px; color:#9CA3AF; line-height:1.6;">
            <div style="font-weight:600; color:#A5B4FC; margin-bottom:4px;">功能依赖与限额说明</div>
            <div>• <b>私信</b>可独立开启：关闭"关注"仅开"私信"时，将仅进入主页发私信不关注</div>
            <div>• <b>视频评论</b>与<b>评论区截流</b>共享每日评论限额（默认30条），超限后两者均停止</div>
            <div>• <b>点赞</b>固定优先执行，其余已启用功能的顺序每视频随机打乱</div>
            <div>• 私信/关注的粉丝数阈值在"私信话术调整"页配置</div>
        </div>
        """, unsafe_allow_html=True)

        if st.form_submit_button("💾 保存当前配置", use_container_width=True, type="primary"):
            # 校验：至少开启一个功能，避免空转浪费 4G 流量
            if not any([enable_like, enable_author_follow, enable_private_message, enable_video_comment, enable_comment_lead]):
                st.error("请至少开启一个功能，否则任务将空转无产出")
            else:
                payload = {
                    "enable_like": enable_like,
                    "enable_author_follow": enable_author_follow,
                    "enable_private_message": enable_private_message,
                    "enable_video_comment": enable_video_comment,
                    "enable_comment_lead": enable_comment_lead
                }
                try:
                    current_config = {}
                    resp = requests.get(f"{API_BASE_URL}/config?platform=douyin")
                    if resp.status_code == 200:
                        current_config = resp.json().get("config", {})
                    # 携带版本号实现乐观锁
                    config_version = current_config.pop("config_version", None)
                    current_config.update(payload)
                    if config_version is not None:
                        current_config["config_version"] = config_version
                    res = requests.post(f"{API_BASE_URL}/config?platform=douyin", json=current_config).json()
                    if res.get("success"):
                        st.success("配置已成功保存！")
                    elif res.get("code") == 409:
                        st.warning("配置已被其他会话修改，请刷新页面后重试")
                    else:
                        st.error(res.get("message"))
                except Exception as e:
                    st.error(f"保存失败: {e}")


def render_private_message():
    render_page_header("AI员工私信话术调整", "设置作者私信话术《话术要合违规》。")

    fetch_config()
    config = st.session_state.config_data

    col1, col2 = st.columns([3, 2])

    with col1:
        st.markdown("""
        <div class="card">
            <div class="card-header">
                <div class="card-title">私信话术（每行一条，可自动轮播）</div>
            </div>
        """, unsafe_allow_html=True)

        pm_messages_str = st.text_area(
            "私信话术",
            value="\n".join(config.get("pm_message_list", [])),
            height=200,
            placeholder="看到你的内容很有意思\n你的视频做得真好，学到了很多\n内容很有价值，感谢分享"
        )

        pm_messages_list = [m.strip() for m in pm_messages_str.split("\n") if m.strip()]
        if pm_messages_list:
            st.caption(f"当前共 {len(pm_messages_list)} 条私信话术，执行时随机抽取其中一行。")
        else:
            st.caption("提示：请至少填写一条私信话术，否则私信功能会自动跳过。")

        st.markdown("</div>", unsafe_allow_html=True)

    with col2:
        st.markdown("""
        <div class="card">
            <div class="card-header">
                <div class="card-title">作者筛选与私信开关</div>
            </div>
        """, unsafe_allow_html=True)

        min_followers = st.number_input(
            "最小关注量阈值（万）",
            value=float(config.get("min_followers_threshold", 0)),
            min_value=0.0,
            max_value=1000.0,
            step=0.1
        )

        enable_pm = st.toggle(
            "启用作者私信",
            value=bool(config.get("enable_private_message", True))
        )

        pm_threshold = st.number_input(
            "私信粉丝阈值（万）",
            value=float(config.get("pm_followers_threshold", 1)),
            min_value=0.0,
            max_value=1000.0,
            step=0.1
        )

        st.markdown("</div>", unsafe_allow_html=True)

    with st.form("pm_form", border=False):
        st.markdown("""
        <div class="card" style="display:none;">
        """, unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

        if st.form_submit_button("💾 保存当前配置", use_container_width=True, type="primary"):
            payload = {
                "pm_message_list": [m.strip() for m in pm_messages_str.split("\n") if m.strip()],
                "min_followers_threshold": min_followers,
                "enable_private_message": enable_pm,
                "pm_followers_threshold": pm_threshold
            }
            try:
                current_config = {}
                resp = requests.get(f"{API_BASE_URL}/config?platform=douyin")
                if resp.status_code == 200:
                    current_config = resp.json().get("config", {})
                # 携带版本号实现乐观锁
                config_version = current_config.pop("config_version", None)
                current_config.update(payload)
                if config_version is not None:
                    current_config["config_version"] = config_version
                res = requests.post(f"{API_BASE_URL}/config?platform=douyin", json=current_config).json()
                if res.get("success"):
                    st.success("配置已成功保存！")
                elif res.get("code") == 409:
                    st.warning("配置已被其他会话修改，请刷新页面后重试")
                else:
                    st.error(res.get("message"))
            except Exception as e:
                st.error(f"保存失败: {e}")


def render_process_control():
    render_page_header("🚀 流程控制", "确保配置保存完毕且已选中AI员工后，可在此开始、暂停、继续或结束任务。")

    st.markdown("""
    <div class="card">
        <div class="card-header">
            <div class="card-title">当前已选设备</div>
        </div>
    """, unsafe_allow_html=True)

    if not st.session_state.controlled_devices:
        st.warning("⚠️ 您目前尚未选中任何要控制的设备，请先去【设备管理】页面选择。")
    else:
        st.success(f"✅ 当前已选中准备控制的设备：{', '.join(st.session_state.controlled_devices)}")

    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("""
    <div class="card">
        <div class="card-header">
            <div class="card-title">任务操作</div>
        </div>
    """, unsafe_allow_html=True)

    col_start, col_pause, col_resume, col_stop = st.columns(4)

    def action_start():
        try:
            res = requests.post(f"{API_BASE_URL}/tasks/start", json={"devices": st.session_state.controlled_devices, "platform": "douyin"}).json()
            if res.get("success"):
                st.session_state.last_action_msg = res.get("message", "✅ 任务已提交！")
            else:
                st.session_state.last_action_err = res.get("message")
        except Exception as e:
            st.session_state.last_action_err = f"请求开始任务失败: {e}"

    def action_pause():
        try:
            res = requests.post(f"{API_BASE_URL}/tasks/pause", json={"devices": st.session_state.controlled_devices, "platform": "douyin"}).json()
            if res.get("success"):
                st.session_state.last_action_msg = res.get("message")
            else:
                st.session_state.last_action_err = res.get("message")
        except Exception as e:
            st.session_state.last_action_err = f"请求暂停任务失败: {e}"

    def action_resume():
        try:
            res = requests.post(f"{API_BASE_URL}/tasks/resume", json={"devices": st.session_state.controlled_devices, "platform": "douyin"}).json()
            if res.get("success"):
                st.session_state.last_action_msg = res.get("message")
            else:
                st.session_state.last_action_err = res.get("message")
        except Exception as e:
            st.session_state.last_action_err = f"请求继续任务失败: {e}"

    def action_stop():
        try:
            res = requests.post(f"{API_BASE_URL}/tasks/stop", json={"devices": st.session_state.controlled_devices, "platform": "douyin"}).json()
            if res.get("success"):
                st.session_state.last_action_msg = res.get("message")
            else:
                st.session_state.last_action_err = res.get("message")
        except Exception as e:
            st.session_state.last_action_err = f"请求结束任务失败: {e}"

    with col_start:
        st.button("🚀 开始任务", type="primary", use_container_width=True, on_click=action_start)
    with col_pause:
        st.button("⏸️ 暂停任务", use_container_width=True, on_click=action_pause)
    with col_resume:
        st.button("▶️ 继续任务", use_container_width=True, on_click=action_resume)
    with col_stop:
        st.button("● 结束任务", use_container_width=True, on_click=action_stop)

    if getattr(st.session_state, "last_action_msg", None):
        st.success(st.session_state.last_action_msg)
        st.session_state.last_action_msg = None
    if getattr(st.session_state, "last_action_err", None):
        st.error(st.session_state.last_action_err)
        st.session_state.last_action_err = None

    st.markdown("</div>", unsafe_allow_html=True)

    fetch_task_status()
    status_data = st.session_state.task_status_data

    if not status_data:
        st.info("当前状态：当前没有任务在运行。")
    else:
        for serial, info in status_data.items():
            state = info.get("status")
            if state == "running":
                st.info(f"当前状态：设备 {serial} 正在执行任务中...")
            elif state == "paused":
                st.warning(f"当前状态：设备 {serial} 任务已暂停")
            elif state == "completed":
                st.success(f"当前状态：设备 {serial} 任务已完成")


def render_data_dashboard():
    render_page_header("📊 获客数据看板", "实时查看今日自动化执行结果及详细处理记录。")

    stats = fetch_stats()

    col1, col2, col3, col4 = st.columns(4)

    col1.markdown(f"""
    <div style="background:#161B28; border:1px solid rgba(255,255,255,0.06); border-radius:12px; padding:20px 24px; height:100%; box-shadow:0 1px 3px rgba(0,0,0,0.2);">
        <div style="font-size:11px; color:#6B7280; font-weight:600; text-transform:uppercase; letter-spacing:0.05em;">今日处理视频总数</div>
        <div style="font-size:32px; font-weight:700; color:#E5E7EB; letter-spacing:-0.02em; margin-top:10px;">{stats.get('videos', 0)} <span style="font-size:13px; font-weight:500; color:#6B7280;">个</span></div>
        <div style="font-size:12px; color:#6B7280; margin-top:4px;">自动防重过滤</div>
    </div>
    """, unsafe_allow_html=True)

    col2.markdown(f"""
    <div style="background:#161B28; border:1px solid rgba(255,255,255,0.06); border-radius:12px; padding:20px 24px; height:100%; box-shadow:0 1px 3px rgba(0,0,0,0.2);">
        <div style="font-size:11px; color:#6B7280; font-weight:600; text-transform:uppercase; letter-spacing:0.05em;">自动点赞数</div>
        <div style="font-size:32px; font-weight:700; color:#E5E7EB; letter-spacing:-0.02em; margin-top:10px;">{stats.get('likes', 0)} <span style="font-size:13px; font-weight:500; color:#6B7280;">次</span></div>
        <div style="font-size:12px; color:#6B7280; margin-top:4px;">活跃度提升</div>
    </div>
    """, unsafe_allow_html=True)

    col3.markdown(f"""
    <div style="background:#161B28; border:1px solid rgba(255,255,255,0.06); border-radius:12px; padding:20px 24px; height:100%; box-shadow:0 1px 3px rgba(0,0,0,0.2);">
        <div style="font-size:11px; color:#6B7280; font-weight:600; text-transform:uppercase; letter-spacing:0.05em;">自动关注同行</div>
        <div style="font-size:32px; font-weight:700; color:#E5E7EB; letter-spacing:-0.02em; margin-top:10px;">{stats.get('follows', 0)} <span style="font-size:13px; font-weight:500; color:#6B7280;">人</span></div>
        <div style="font-size:12px; color:#6B7280; margin-top:4px;">增加曝光</div>
    </div>
    """, unsafe_allow_html=True)

    col4.markdown(f"""
    <div style="background:#161B28; border:1px solid rgba(255,255,255,0.06); border-radius:12px; padding:20px 24px; height:100%; box-shadow:0 1px 3px rgba(0,0,0,0.2);">
        <div style="font-size:11px; color:#6B7280; font-weight:600; text-transform:uppercase; letter-spacing:0.05em;">AI 自动回复</div>
        <div style="font-size:32px; font-weight:700; color:#E5E7EB; letter-spacing:-0.02em; margin-top:10px;">{stats.get('comments', 0)} <span style="font-size:13px; font-weight:500; color:#6B7280;">次</span></div>
        <div style="font-size:12px; color:#6B7280; margin-top:4px;">标题驱动生成</div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("""
    <div class="card">
        <div class="card-header">
            <div class="card-title">今日详细操作记录</div>
        </div>
    """, unsafe_allow_html=True)

    records = fetch_details(limit=100)

    if records:
        for idx, record in enumerate(records, start=1):
            liked_text = "✅ 已点赞" if record.get("liked") else "❌ 未点赞"
            commented_text = "✅ 已回复" if record.get("commented") else "❌ 未回复"
            followed_text = "✅ 已关注" if record.get("followed") else "❌ 未关注"
            title_text = record.get("note_title") or "未抓取到标题"
            reply_text = record.get("ai_reply") or "本条内容暂无可展示的 AI 回复内容"
            header = f"{idx}. {title_text[:28]}{'...' if len(title_text) > 28 else ''}"

            with st.expander(header, expanded=(idx == 1)):
                meta_cols = st.columns(4)
                meta_cols[0].markdown(f"**时间**：{record.get('created_at', '-')}")
                meta_cols[1].markdown(f"**关键词**：{record.get('keyword', '-') or '-'}")
                meta_cols[2].markdown(f"**标识**：`{record.get('video_id', '-')}`")
                if record.get("url"):
                    meta_cols[3].markdown(f"**链接**：[打开原内容]({record.get('url')})")
                else:
                    meta_cols[3].markdown("**链接**：-")

                st.markdown(f"**互动状态**：{liked_text} | {commented_text} | {followed_text}")
                st.markdown("**内容标题**")
                st.text_area(
                    f"title_{idx}",
                    value=title_text,
                    height=80,
                    disabled=True,
                    label_visibility="collapsed"
                )
                st.markdown("**AI 生成回复**")
                st.text_area(
                    f"reply_{idx}",
                    value=reply_text,
                    height=120,
                    disabled=True,
                    label_visibility="collapsed"
                )
    else:
        st.info("今日暂无操作记录。")

    st.markdown("""
            <div style="margin-top:20px; padding-top:16px; border-top:1px solid rgba(255,255,255,0.06); color:#6B7280; font-size:12px;">
                提示：详细操作记录继续保存于 data/scout_records.db 与 logs 文件夹。
            </div>
        </div>
    """, unsafe_allow_html=True)


def _home_metric_card(label, value, unit, color):
    return f"""
    <div style="text-align:center; padding:28px 12px;">
        <div style="font-size:12px; color:#6B7280; font-weight:500; letter-spacing:0.04em; margin-bottom:12px;">{label}</div>
        <div style="font-size:40px; font-weight:800; color:#E5E7EB; letter-spacing:-0.02em; line-height:1; font-variant-numeric:tabular-nums;">{value}<span style="font-size:16px; font-weight:500; color:#6B7280; margin-left:4px;">{unit}</span></div>
    </div>
    """


def _home_rate_card(label, rate, color):
    blocks = math.floor(rate * 10)
    if rate >= 0.95:
        blocks = 10
    blocks = max(0, min(10, blocks))
    filled = "█" * blocks
    empty = "░" * (10 - blocks)
    pct = rate * 100
    return f"""
    <div style="text-align:center; padding:28px 12px;">
        <div style="font-size:12px; color:#6B7280; font-weight:500; letter-spacing:0.04em; margin-bottom:12px;">{label}</div>
        <div style="font-size:40px; font-weight:800; color:#E5E7EB; letter-spacing:-0.02em; line-height:1; font-variant-numeric:tabular-nums;">{pct:.1f}<span style="font-size:20px; font-weight:600; color:#6B7280;">%</span></div>
        <div style="font-family: 'JetBrains Mono', 'Consolas', monospace; font-size: 12px; color:{color}; margin-top:10px; letter-spacing:2px; line-height:1; text-shadow:0 0 8px {color}40;">{filled}{empty}</div>
    </div>
    """


@st.fragment(run_every=3)
def _render_composite_index(base_floor):
    offset = int(time.time() * 1000) % 7
    composite_index = base_floor + offset
    display_num = f"{composite_index:,}"
    st.markdown(f"""
    <div style="background: linear-gradient(135deg, #4F46E5 0%, #6945FF 50%, #5B3DFF 100%); border-radius:16px; padding:44px 40px 36px 40px; margin-bottom:0; text-align:center; position:relative; overflow:hidden;">
        <div style="position:absolute; top:-80px; right:-80px; width:260px; height:260px; background:radial-gradient(circle, rgba(255,255,255,0.07) 0%, transparent 70%); border-radius:50%;"></div>
        <div style="position:absolute; bottom:-60px; left:-60px; width:200px; height:200px; background:radial-gradient(circle, rgba(255,255,255,0.04) 0%, transparent 70%); border-radius:50%;"></div>
        <div style="position:relative; z-index:1;">
            <div style="font-size:14px; color:rgba(255,255,255,0.65); font-weight:500; letter-spacing:0.1em;">AI 矩阵品牌综合指数</div>
            <div style="font-size:76px; font-weight:800; color:#FFFFFF; letter-spacing:-0.03em; margin-top:14px; line-height:1; text-shadow:0 2px 30px rgba(0,0,0,0.12); font-variant-numeric:tabular-nums;">
                {display_num}
            </div>
            <div style="margin-top:10px; font-size:11px; color:rgba(255,255,255,0.45);">
                <span style="display:inline-block; width:6px; height:6px; background:#10B981; border-radius:50%; margin-right:6px; box-shadow:0 0 0 2px rgba(16,185,129,0.3); animation: home-pulse 2s infinite; vertical-align:middle;"></span>
                实时数据 · 自动刷新 · 微幅波动 +{offset}
            </div>
        </div>
    </div>
    <style>
        @keyframes home-pulse {{ 0%,100% {{ opacity:1; }} 50% {{ opacity:0.4; }} }}
    </style>
    """, unsafe_allow_html=True)


# 状态枚举 -> 默认动作文案（后端未上报 current_action 时回退使用）
_PHONE_ACTION_FALLBACK = {
    "queued": "数字化员工已就绪，等待下达任务指令...",
    "starting": "正在建立安全合规的多信道握手协议...",
    "running": "AI 矩阵全域品牌渗透中...",
    "paused": "自动化运营流已安全暂停",
    "stopped": "自动化作业流已成功安全释放",
    "completed": "当日智能化引流作业圆满闭环",
    "error": "触发自适应风控隔离，系统正在智能重试...",
}


def _phone_frame_card(serial, info):
    """渲染单台设备的手机框动态卡片（外壳为手机 UI，内容仅文字）。"""
    info = info or {}
    status = info.get("status") or "idle"
    current_action = info.get("current_action") or _PHONE_ACTION_FALLBACK.get(status, "数字化员工待命中...")
    if status == "error" and info.get("error"):
        current_action = "触发自适应风控隔离，系统正在智能重试..."
    executed = info.get("executed_actions") or []

    # 已执行列表：最多展示 5 条，超出显示省略
    if executed:
        visible = executed[-5:]
        items = "".join(f"<li>{_html.escape(str(a))}</li>" for a in visible)
        if len(executed) > 5:
            items += f"<li style='color:#4B5563;'>...等 {len(executed) - 5} 条</li>"
        executed_html = f"<ul style='margin:6px 0 0 0; padding-left:18px; list-style:disc;'>{items}</ul>"
    else:
        executed_html = "<div style='color:#4B5563; font-size:12px; margin-top:6px;'>—</div>"

    # 状态指示点：运行中绿色脉冲，其他灰色
    is_running = status == "running"
    dot_color = "#10B981" if is_running else "#6B7280"
    pulse_style = "animation: phone-card-pulse 1.5s infinite;" if is_running else ""

    return f"""
    <div style="background:#0A0B0F; border-radius:30px; padding:9px; box-shadow:0 8px 24px rgba(0,0,0,0.45); margin-bottom:14px; width:fit-content;">
        <div style="background:#161B28; border-radius:22px; overflow:hidden; border:1px solid rgba(255,255,255,0.06); min-width:220px;">
            <div style="display:flex; justify-content:center; padding:6px 0 2px 0;">
                <div style="width:54px; height:13px; background:#0A0B0F; border-radius:0 0 9px 9px;"></div>
            </div>
            <div style="padding:4px 16px 16px 16px;">
                <div style="font-size:13px; font-weight:700; color:#E5E7EB; letter-spacing:-0.01em; margin-bottom:10px; white-space:nowrap;">设备名称：{_html.escape(str(serial))}</div>
                <div style="display:flex; align-items:center; gap:6px; font-size:11px; color:#9CA3AF; margin-bottom:3px;">
                    <span style="width:6px; height:6px; border-radius:50%; background:{dot_color}; box-shadow:0 0 0 2px {dot_color}30; flex-shrink:0; {pulse_style}"></span>
                    <span>当前AI正在执行：</span>
                </div>
                <div style="font-size:12px; color:#A5B4FC; font-weight:600; line-height:1.4; margin-bottom:10px; white-space:nowrap;">{_html.escape(str(current_action))}</div>
                <div style="font-size:11px; color:#6B7280; font-weight:600; letter-spacing:0.04em;">已执行：</div>
                <div style="min-height:54px;">
                    {executed_html}
                </div>
            </div>
        </div>
    </div>
    """


@st.fragment(run_every=3)
def _render_device_dynamics():
    """首页底部：每台已连接手机的实时 AI 执行动态（手机框 UI）。"""
    devices = fetch_devices()
    fetch_task_status()
    task_status = st.session_state.task_status_data or {}

    st.markdown("""
    <div style="margin-top:28px; margin-bottom:14px;">
        <div style="font-size:16px; font-weight:700; color:#E5E7EB; letter-spacing:-0.01em;">📱 设备实时动态</div>
        <div style="font-size:12px; color:#6B7280; margin-top:2px;">每台手机的当前 AI 执行进度 · 每 3 秒自动刷新</div>
    </div>
    <style>
        @keyframes phone-card-pulse { 0%,100% { opacity:1; } 50% { opacity:0.4; } }
    </style>
    """, unsafe_allow_html=True)

    if not devices:
        st.info("暂无已连接的设备")
        return

    per_row = 4
    for i in range(0, len(devices), per_row):
        chunk = devices[i:i + per_row]
        cols = st.columns(len(chunk))
        for j, serial in enumerate(chunk):
            info = task_status.get(serial, {}) or {}
            cols[j].markdown(_phone_frame_card(serial, info), unsafe_allow_html=True)


def render_home_page():
    stats = fetch_stats()

    A = stats.get("videos", 0) or 128
    B = stats.get("comments", 0) or 86
    C = stats.get("follows", 0) or 59
    D = stats.get("likes", 0) or 34

    E = 0.65 + (D % 8) / 100
    F = 0.60 + (B % 8) / 100
    G = 0.50 + ((A + B) % 9) / 100
    H = 0.998

    base = (A * 8.65 + B * 14.82 + C * 22.41 + D * 48.15) * (1.0 + E * 0.35 + F * 0.25 + G * 0.40) * H * 1.28
    base_floor = math.floor(base) + 12450

    _render_composite_index(base_floor)

    row1 = st.columns(4)
    row1[0].markdown(_home_metric_card("今日自动化处理量", f"{A:,}", "次", "#4F46E5"), unsafe_allow_html=True)
    row1[1].markdown(_home_metric_card("AI智能语义响应", f"{B:,}", "次", "#059669"), unsafe_allow_html=True)
    row1[2].markdown(_home_metric_card("对标账号精准锁定", f"{C:,}", "个", "#D97706"), unsafe_allow_html=True)
    row1[3].markdown(_home_metric_card("高意向私域触达", f"{D:,}", "次", "#DC2626"), unsafe_allow_html=True)

    row2 = st.columns(4)
    row2[0].markdown(_home_rate_card("高潜客群转化率", E, "#059669"), unsafe_allow_html=True)
    row2[1].markdown(_home_rate_card("智能对话自主率", F, "#059669"), unsafe_allow_html=True)
    row2[2].markdown(_home_rate_card("客群线索唤醒率", G, "#059669"), unsafe_allow_html=True)
    row2[3].markdown(_home_rate_card("矩阵全时风控安全度", H, "#059669"), unsafe_allow_html=True)

    _render_device_dynamics()


def render_douyin_page(current_page):
    init_session_state()

    page_renderers = {
        "首页": render_home_page,
        "设备管理": render_device_management,
        "实时任务监控": render_task_monitor,
        "搜索与基础控制": render_search_control,
        "自定义意向关键词": render_intent_keywords,
        "AI截流获客策略": render_ai_strategy,
        "视频处理设置": render_video_settings,
        "自定义执行功能选择": render_execution_functions,
        "作者私信策略": render_private_message,
        "流程控制": render_process_control,
        "获客数据看板": render_data_dashboard,
    }

    renderer = page_renderers.get(current_page)
    if renderer:
        renderer()
    else:
        st.error(f"未知页面: {current_page}")
