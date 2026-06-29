"""账号登录微服务：注册 / 登录 / 校验 / 退出。

部署位置：服务器 /www/wwwroot/CloudSever.lcjx.yun/social-account-api/
对外地址：https://lcjx.yun/social-account-api  (Nginx 反代到本服务 127.0.0.1:8200)
"""
import os
import re
import secrets
import sqlite3
import time
from collections import defaultdict, deque
from contextlib import contextmanager
from datetime import datetime
from typing import Any

import bcrypt
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator

# ======================== 配置 ========================
DB_PATH = os.environ.get("ACCOUNT_DB_PATH", "data/accounts.db")
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8200"))
MIN_PASSWORD_LEN = 6
LOGIN_RATE_LIMIT = 5        # 同 IP 每分钟最多尝试
LOGIN_RATE_WINDOW = 60      # 窗口 60 秒
TOKEN_BYTES = 48            # secrets.token_urlsafe(48) ≈ 64 字符


# ======================== 数据库 ========================
@contextmanager
def get_db():
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    with get_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                email         TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at    TEXT NOT NULL,
                last_login_at TEXT
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token      TEXT PRIMARY KEY,
                user_id    INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT,
                revoked    INTEGER DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
            CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
            """
        )
        conn.commit()


# ======================== 限流（内存，按 IP）========================
_login_attempts: dict[str, deque[float]] = defaultdict(deque)


def check_login_rate_limit(ip: str) -> None:
    now = time.time()
    attempts = _login_attempts[ip]
    while attempts and attempts[0] < now - LOGIN_RATE_WINDOW:
        attempts.popleft()
    if len(attempts) >= LOGIN_RATE_LIMIT:
        raise HTTPException(status_code=429, detail="登录尝试过于频繁，请稍后再试")
    attempts.append(now)


# ======================== 请求模型 ========================
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class RegisterRequest(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, v: str) -> str:
        v = (v or "").strip().lower()
        if not EMAIL_RE.match(v):
            raise ValueError("邮箱格式不正确")
        return v

    @field_validator("password")
    @classmethod
    def _check_password(cls, v: str) -> str:
        if len(v or "") < MIN_PASSWORD_LEN:
            raise ValueError(f"密码至少 {MIN_PASSWORD_LEN} 位")
        return v


class LoginRequest(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, v: str) -> str:
        return (v or "").strip().lower()


# ======================== 工具函数 ========================
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except Exception:
        return False


def generate_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def get_bearer_token(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未提供有效的认证信息")
    return auth[7:].strip()


def get_session_user(request: Request) -> sqlite3.Row:
    token = get_bearer_token(request)
    with get_db() as conn:
        row = conn.execute(
            "SELECT s.token, s.user_id, s.revoked, u.email, u.created_at, u.last_login_at "
            "FROM sessions s JOIN users u ON s.user_id = u.id "
            "WHERE s.token = ?",
            (token,),
        ).fetchone()
    if not row or row["revoked"]:
        raise HTTPException(status_code=401, detail="登录已失效，请重新登录")
    return row


# ======================== FastAPI ========================
app = FastAPI(title="Social Account API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _on_startup() -> None:
    init_db()


@app.get("/health")
def health() -> dict[str, Any]:
    return {"success": True, "service": "social-account-api"}


@app.post("/auth/register")
def register(req: RegisterRequest) -> dict[str, Any]:
    password_hash = hash_password(req.password)
    now = datetime.utcnow().isoformat()
    with get_db() as conn:
        try:
            cur = conn.execute(
                "INSERT INTO users (email, password_hash, created_at, last_login_at) VALUES (?, ?, ?, ?)",
                (req.email, password_hash, now, now),
            )
            user_id = cur.lastrowid
        except sqlite3.IntegrityError:
            raise HTTPException(status_code=409, detail="该邮箱已注册")
        token = generate_token()
        conn.execute(
            "INSERT INTO sessions (token, user_id, created_at, expires_at, revoked) "
            "VALUES (?, ?, ?, NULL, 0)",
            (token, user_id, now),
        )
        conn.commit()
    return {
        "success": True,
        "message": "注册成功",
        "data": {"token": token, "user": {"id": user_id, "email": req.email}},
    }


@app.post("/auth/login")
def login(req: LoginRequest, request: Request) -> dict[str, Any]:
    client_ip = request.client.host if request.client else "unknown"
    check_login_rate_limit(client_ip)
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, email, password_hash FROM users WHERE email = ?",
            (req.email,),
        ).fetchone()
        if not row or not verify_password(req.password, row["password_hash"]):
            raise HTTPException(status_code=401, detail="邮箱或密码错误")
        now = datetime.utcnow().isoformat()
        token = generate_token()
        conn.execute(
            "INSERT INTO sessions (token, user_id, created_at, expires_at, revoked) "
            "VALUES (?, ?, ?, NULL, 0)",
            (token, row["id"], now),
        )
        conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (now, row["id"]))
        conn.commit()
    return {
        "success": True,
        "message": "登录成功",
        "data": {"token": token, "user": {"id": row["id"], "email": row["email"]}},
    }


@app.get("/auth/profile")
def profile(request: Request) -> dict[str, Any]:
    user = get_session_user(request)
    return {
        "success": True,
        "data": {
            "id": user["user_id"],
            "email": user["email"],
            "created_at": user["created_at"],
            "last_login_at": user["last_login_at"],
        },
    }


@app.post("/auth/logout")
def logout(request: Request) -> dict[str, Any]:
    user = get_session_user(request)
    with get_db() as conn:
        conn.execute("UPDATE sessions SET revoked = 1 WHERE token = ?", (user["token"],))
        conn.commit()
    return {"success": True, "message": "已退出登录"}


if __name__ == "__main__":
    import uvicorn

    init_db()
    uvicorn.run(app, host=HOST, port=PORT)
