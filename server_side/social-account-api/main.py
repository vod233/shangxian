"""账号登录微服务：注册 / 登录 / 校验 / 退出。

部署位置：服务器 /www/wwwroot/CloudSever.lcjx.yun/social-account-api/
对外地址：https://lcjx.yun/social-account-api  (Nginx 反代到本服务 127.0.0.1:8200)

数据库：PostgreSQL（通过 psycopg2 连接池）。
"""
import os
import re
import secrets
import time
import logging
from collections import defaultdict, deque
from contextlib import contextmanager
from datetime import datetime
from typing import Any

from dotenv import load_dotenv
import bcrypt
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator

# 从项目根目录加载 .env（本地开发），也尝试当前目录（服务器部署）
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(_project_root, ".env"), override=True)
load_dotenv(".env", override=True)

logger = logging.getLogger(__name__)

# ======================== 配置 ========================
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8200"))


# ======================== PostgreSQL 连接池 ========================
_pg_pool = None


def _get_pg_pool():
    global _pg_pool
    if _pg_pool is None:
        from psycopg2 import pool as pg_pool_mod
        _pg_pool = pg_pool_mod.ThreadedConnectionPool(
            minconn=2,
            maxconn=20,
            host=os.environ.get("PG_HOST", "127.0.0.1"),
            port=int(os.environ.get("PG_PORT", "5432")),
            dbname=os.environ.get("PG_DB", "scout"),
            user=os.environ.get("PG_USER", "scout"),
            password=os.environ.get("PG_PASSWORD", "scout123"),
        )
        logger.info(
            "账号服务 PostgreSQL 连接池已初始化: %s:%s/%s",
            os.environ.get("PG_HOST", "127.0.0.1"),
            os.environ.get("PG_PORT", "5432"),
            os.environ.get("PG_DB", "scout"),
        )
    return _pg_pool


def _close_pg_pool():
    global _pg_pool
    if _pg_pool is not None:
        _pg_pool.closeall()
        _pg_pool = None
        logger.info("账号服务 PostgreSQL 连接池已关闭")


# ======================== 数据库连接（统一接口）========================
@contextmanager
def get_db():
    """获取 PostgreSQL 数据库连接（通过连接池复用）。"""
    pool = _get_pg_pool()
    conn = pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


def _exec_sql(conn, sql, params=None):
    """执行 SQL 并返回 cursor。将 ? 占位符转换为 PostgreSQL 的 %s。"""
    cur = conn.cursor()
    pg_sql = sql.replace("?", "%s")
    cur.execute(pg_sql, params)
    return cur


def _fetchone_as_dict(cur):
    """将查询结果的第一行转为字典（兼容 psycopg2 的 tuple）"""
    row = cur.fetchone()
    if row is None:
        return None
    if hasattr(row, "keys"):
        return dict(row)
    cols = [desc[0] for desc in cur.description]
    return dict(zip(cols, row))


def init_db() -> None:
    """初始化数据库表结构（PostgreSQL）"""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id            SERIAL PRIMARY KEY,
                email         TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at    TEXT NOT NULL,
                last_login_at TEXT
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS sessions (
                token      TEXT PRIMARY KEY,
                user_id    INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT,
                revoked    INTEGER DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')
        cur.execute('''
            CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)
        ''')


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


def get_session_user(request: Request) -> dict:
    """校验 token 并返回用户信息字典"""
    token = get_bearer_token(request)
    with get_db() as conn:
        cur = _exec_sql(
            conn,
            "SELECT s.token, s.user_id, s.revoked, u.email, u.created_at, u.last_login_at "
            "FROM sessions s JOIN users u ON s.user_id = u.id "
            "WHERE s.token = ?",
            (token,),
        )
        row = _fetchone_as_dict(cur)
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
    try:
        init_db()
        logger.info("账号服务数据库已初始化 (后端: postgres)")
    except Exception as e:
        logger.error(f"账号服务数据库初始化失败: {e}")
        raise


@app.on_event("shutdown")
def _on_shutdown() -> None:
    _close_pg_pool()


@app.get("/health")
def health() -> dict[str, Any]:
    return {"success": True, "service": "social-account-api", "db_backend": "postgres"}


@app.post("/auth/register")
def register(req: RegisterRequest) -> dict[str, Any]:
    password_hash = hash_password(req.password)
    now = datetime.utcnow().isoformat()
    with get_db() as conn:
        try:
            # PostgreSQL: 使用 RETURNING 获取自增 ID
            cur = _exec_sql(
                conn,
                "INSERT INTO users (email, password_hash, created_at, last_login_at) "
                "VALUES (?, ?, ?, ?) RETURNING id",
                (req.email, password_hash, now, now),
            )
            row = cur.fetchone()
            user_id = row[0] if row else cur.lastrowid
        except Exception as exc:
            # 区分唯一约束冲突（邮箱已注册）与其他数据库错误
            is_duplicate = False
            try:
                from psycopg2.errors import UniqueViolation
                is_duplicate = isinstance(exc, UniqueViolation)
            except ImportError:
                is_duplicate = "duplicate key" in str(exc).lower() or "unique" in str(exc).lower()
            if is_duplicate:
                raise HTTPException(status_code=409, detail="该邮箱已注册")
            logger.error(f"注册时数据库错误: {exc}")
            raise HTTPException(status_code=500, detail="注册失败，请稍后重试")
        token = generate_token()
        _exec_sql(
            conn,
            "INSERT INTO sessions (token, user_id, created_at, expires_at, revoked) "
            "VALUES (?, ?, ?, NULL, 0)",
            (token, user_id, now),
        )
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
        cur = _exec_sql(
            conn,
            "SELECT id, email, password_hash FROM users WHERE email = ?",
            (req.email,),
        )
        row = _fetchone_as_dict(cur)
        if not row or not verify_password(req.password, row["password_hash"]):
            raise HTTPException(status_code=401, detail="邮箱或密码错误")
        now = datetime.utcnow().isoformat()
        token = generate_token()
        _exec_sql(
            conn,
            "INSERT INTO sessions (token, user_id, created_at, expires_at, revoked) "
            "VALUES (?, ?, ?, NULL, 0)",
            (token, row["id"], now),
        )
        _exec_sql(
            conn,
            "UPDATE users SET last_login_at = ? WHERE id = ?",
            (now, row["id"]),
        )
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
        _exec_sql(
            conn,
            "UPDATE sessions SET revoked = 1 WHERE token = ?",
            (user["token"],),
        )
    return {"success": True, "message": "已退出登录"}


if __name__ == "__main__":
    import uvicorn

    init_db()
    uvicorn.run(app, host=HOST, port=PORT)
