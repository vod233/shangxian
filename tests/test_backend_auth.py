"""测试后端 /api/auth/* 接口全流程。"""
import requests
import json

BASE = "http://127.0.0.1:8300/api"
EMAIL = f"backend_test_{__import__('time').time()}@example.com"
PASSWORD = "test123"


def show(title, resp):
    print(f"\n=== {title} ===  HTTP {resp.status_code}")
    try:
        print(json.dumps(resp.json(), ensure_ascii=False, indent=2))
    except Exception:
        print(resp.text)


# 1. check 未登录
show("check-未登录", requests.get(f"{BASE}/auth/check", timeout=20))

# 2. register
r = requests.post(f"{BASE}/auth/register", json={"email": EMAIL, "password": PASSWORD}, timeout=20)
show("register", r)

# 3. check 已登录
show("check-注册后", requests.get(f"{BASE}/auth/check", timeout=20))

# 4. register 重复
show("register-重复",
     requests.post(f"{BASE}/auth/register", json={"email": EMAIL, "password": PASSWORD}, timeout=20))

# 5. login
show("login", requests.post(f"{BASE}/auth/login", json={"email": EMAIL, "password": PASSWORD}, timeout=20))

# 6. check 已登录
show("check-登录后", requests.get(f"{BASE}/auth/check", timeout=20))

# 7. login 错误密码
show("login-错误密码",
     requests.post(f"{BASE}/auth/login", json={"email": EMAIL, "password": "wrong"}, timeout=20))

# 8. logout
show("logout", requests.post(f"{BASE}/auth/logout", timeout=20))

# 9. check 退出后
show("check-退出后", requests.get(f"{BASE}/auth/check", timeout=20))

print("\n=== 后端 /api/auth/* 测试完成 ===")
