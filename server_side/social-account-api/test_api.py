"""本地接口自测脚本：注册→登录→profile→logout 全流程。"""
import requests
import json

BASE = "http://127.0.0.1:8200"
EMAIL = "test@example.com"
PASSWORD = "pass123"


def show(title, resp):
    print(f"\n=== {title} ===  HTTP {resp.status_code}")
    try:
        print(json.dumps(resp.json(), ensure_ascii=False, indent=2))
    except Exception:
        print(resp.text)


# 1. 健康检查
show("health", requests.get(f"{BASE}/health", timeout=5))

# 2. 注册
r = requests.post(f"{BASE}/auth/register", json={"email": EMAIL, "password": PASSWORD}, timeout=5)
show("register", r)
token = r.json().get("data", {}).get("token", "") if r.ok else ""

# 3. 重复注册（应 409）
show("register-duplicate",
     requests.post(f"{BASE}/auth/register", json={"email": EMAIL, "password": PASSWORD}, timeout=5))

# 4. 短密码（应 422）
show("register-short-pwd",
     requests.post(f"{BASE}/auth/register", json={"email": "x@y.z", "password": "123"}, timeout=5))

# 5. 非法邮箱（应 422）
show("register-bad-email",
     requests.post(f"{BASE}/auth/register", json={"email": "not-email", "password": PASSWORD}, timeout=5))

# 6. 登录
r = requests.post(f"{BASE}/auth/login", json={"email": EMAIL, "password": PASSWORD}, timeout=5)
show("login", r)
token = r.json().get("data", {}).get("token", "") if r.ok else token
H = {"Authorization": f"Bearer {token}"}

# 7. 登录错误密码（应 401）
show("login-wrong-pwd",
     requests.post(f"{BASE}/auth/login", json={"email": EMAIL, "password": "wrong"}, timeout=5))

# 8. profile（带 token）
show("profile", requests.get(f"{BASE}/auth/profile", headers=H, timeout=5))

# 9. profile 无 token（应 401）
show("profile-no-token", requests.get(f"{BASE}/auth/profile", timeout=5))

# 10. profile 错 token（应 401）
show("profile-bad-token",
     requests.get(f"{BASE}/auth/profile",
                  headers={"Authorization": "Bearer bad_token_xxx"}, timeout=5))

# 11. logout
show("logout", requests.post(f"{BASE}/auth/logout", headers=H, timeout=5))

# 12. logout 后再 profile（应 401）
show("profile-after-logout", requests.get(f"{BASE}/auth/profile", headers=H, timeout=5))

print("\n=== 全部测试完成 ===")
