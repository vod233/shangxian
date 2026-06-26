import os
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

# requests 不认 NO_PROXY 中的 127.* 通配符，导致 localhost 请求被系统代理（如 Clash）拦截返回 502
# 追加精确 127.0.0.1，仅绕过本机回环，不影响外部请求（license/AI 云端仍走代理）
_np = os.environ.get("NO_PROXY", "")
if "127.0.0.1" not in _np:
    os.environ["NO_PROXY"] = (_np + "," if _np else "") + "127.0.0.1"
    os.environ["no_proxy"] = os.environ["NO_PROXY"]

import streamlit as st
from douyin.douyin_app import render_douyin_page

st.set_page_config(page_title="抖音自动化群控系统", page_icon="🎵", layout="wide")


def main():
    st.sidebar.title("🎵 抖音群控")
    page = st.sidebar.selectbox("功能菜单", ["🎵 抖音控制台"])
    if page == "🎵 抖音控制台":
        render_douyin_page()


if __name__ == "__main__":
    main()
