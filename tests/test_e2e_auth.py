"""端到端测试：模拟前端 streamlit 的完整登录流程。"""
import requests
import json
import time

BASE = "http://127.0.0.1:8300/api"
EMAIL = f"e2e_{int(time.time())}@example.com"
PASSWORD = "e2etest123"


def show(title, resp, key=None):
    print(f"\n=== {title} ===  HTTP {resp.status_code}")
    data = resp.json()
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return data.get(key) if key else data


print("模拟前端 streamlit main() 流程\n" + "=" * 50)

# 1. main() → _ensure_logged_in() → /api/auth/check（未登录）
print("\n[1] 模拟首次打开：_ensure_logged_in() 调 /api/auth/check")
r = requests.get(f"{BASE}/auth/check", timeout=10)
data = show("check（应未登录）", r)
assert data.get("logged_in") is False, "应未登录"
print("→ 前端应渲染 _render_auth_page() 登录页")

# 2. 模拟用户在注册 tab 填表 → /api/auth/register
print("\n[2] 模拟用户注册：_render_auth_page() 调 /api/auth/register")
r = requests.post(f"{BASE}/auth/register", json={"email": EMAIL, "password": PASSWORD}, timeout=20)
data = show("register", r)
assert data.get("success") is True, "注册应成功"
print(f"→ 前端应设 session_state.account_logged_in=True 并 st.rerun()")

# 3. 模拟 rerun 后 _ensure_logged_in() → /api/auth/check（已登录）
print("\n[3] 模拟 rerun 后：_ensure_logged_in() 调 /api/auth/check")
r = requests.get(f"{BASE}/auth/check", timeout=10)
data = show("check（应已登录）", r)
assert data.get("logged_in") is True, "应已登录"
email = data.get("data", {}).get("email", "")
assert email == EMAIL, f"邮箱应匹配，实际: {email}"
print(f"→ 前端应进入主面板，侧边栏显示邮箱: {email}")

# 4. 验证现有授权码体系不受影响：/api/config 仍可正常调用
print("\n[4] 验证授权码体系未受影响：调 /api/config")
r = requests.get(f"{BASE}/config?platform=douyin", timeout=10)
data = show("config（应返回授权码配置）", r)
assert data.get("success") is True, "配置接口应正常"
print("→ 现有授权码配置接口正常，双门槛独立")

# 5. 模拟用户点退出登录 → /api/auth/logout
print("\n[5] 模拟退出登录：侧边栏按钮调 /api/auth/logout")
r = requests.post(f"{BASE}/auth/logout", timeout=10)
data = show("logout", r)
assert data.get("success") is True, "退出应成功"

# 6. 模拟 rerun 后 _ensure_logged_in() → /api/auth/check（未登录）
print("\n[6] 模拟退出后 rerun：_ensure_logged_in() 调 /api/auth/check")
r = requests.get(f"{BASE}/auth/check", timeout=10)
data = show("check（应未登录）", r)
assert data.get("logged_in") is False, "退出后应未登录"
print("→ 前端应回到登录页")

# 7. 模拟重新登录（永久记住场景：下次打开 exe）
print("\n[7] 模拟重新登录：调 /api/auth/login")
r = requests.post(f"{BASE}/auth/login", json={"email": EMAIL, "password": PASSWORD}, timeout=20)
data = show("login", r)
assert data.get("success") is True, "登录应成功"
print("→ token 写入 auth.json，下次打开 exe 直进面板（永久记住）")

print("\n" + "=" * 50)
print("端到端测试全部通过！")
print(f"测试账号: {EMAIL} / {PASSWORD}")
