"""账号登录微服务：注册 / 登录 / 校验 / 退出。

部署位置：服务器 /www/wwwroot/CloudSever.lcjx.yun/social-account-api/
对外地址：https://lcjx.yun/social-account-api  (Nginx 反代到本服务 127.0.0.1:8200)

数据库：PostgreSQL（通过 psycopg2 连接池），兼容回退 SQLite。
"""
import os
import re
import hashlib
import secrets
import time
import logging
from collections import defaultdict, deque
from contextlib import contextmanager
from datetime import datetime, timedelta
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
MIN_PASSWORD_LEN = 6
LOGIN_RATE_LIMIT = 5        # 同 IP 每分钟最多尝试
LOGIN_RATE_WINDOW = 60      # 窗口 60 秒
TOKEN_BYTES = 48            # secrets.token_urlsafe(48) ≈ 64 字符
TOKEN_TTL_DAYS = 7          # 会话 token 有效期 7 天

# 数据库后端选择：postgres（默认）或 sqlite
DB_BACKEND = os.environ.get("ACCOUNT_DB_BACKEND", os.environ.get("DB_BACKEND", "postgres")).lower()
SQLITE_DB_PATH = os.environ.get("ACCOUNT_DB_PATH", "data/accounts.db")


# ======================== PostgreSQL 连接池 ========================
_pg_pool = None


def _get_pg_pool():
    global _pg_pool
    if _pg_pool is None:
        from psycopg2 import pool as pg_pool_mod
        # sslmode=require：强制加密传输，防止账号凭据明文泄露
        sslmode = os.environ.get("PG_SSLMODE", "require")
        _pg_pool = pg_pool_mod.ThreadedConnectionPool(
            minconn=2,
            maxconn=20,
            host=os.environ.get("PG_HOST", "127.0.0.1"),
            port=int(os.environ.get("PG_PORT", "5432")),
            dbname=os.environ.get("PG_DB", "scout"),
            user=os.environ.get("PG_USER", "scout"),
            password=os.environ.get("PG_PASSWORD", "scout123"),
            sslmode=sslmode,
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
    """
    获取数据库连接，支持 PostgreSQL 和 SQLite 两种后端。
    PostgreSQL 使用连接池；SQLite 每次新建连接。
    统一返回一个可执行 SQL 的连接对象。
    """
    if DB_BACKEND == "sqlite":
        import sqlite3
        db_dir = os.path.dirname(SQLITE_DB_PATH)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        conn = sqlite3.connect(SQLITE_DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    else:
        # PostgreSQL
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
    """执行 SQL 并返回 cursor（兼容 SQLite ? 和 PostgreSQL %s 占位符）"""
    cur = conn.cursor()
    if DB_BACKEND == "sqlite":
        # SQLite 使用 ? 占位符
        cur.execute(sql, params)
    else:
        # PostgreSQL 使用 %s 占位符，需要转换
        pg_sql = sql.replace("?", "%s")
        cur.execute(pg_sql, params)
    return cur


def _fetchone_as_dict(cur):
    """将查询结果的第一行转为字典（兼容 sqlite3.Row 和 psycopg2 的 tuple）"""
    row = cur.fetchone()
    if row is None:
        return None
    if hasattr(row, "keys"):
        # sqlite3.Row 或 psycopg2 的 RealDictCursor
        return dict(row)
    # 普通 tuple：从 cursor.description 获取列名
    cols = [desc[0] for desc in cur.description]
    return dict(zip(cols, row))


def init_db() -> None:
    """初始化数据库表结构"""
    if DB_BACKEND == "sqlite":
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
                CREATE TABLE IF NOT EXISTS user_devices (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id       INTEGER NOT NULL,
                    device_serial TEXT NOT NULL,
                    device_alias  TEXT,
                    registered_at TEXT NOT NULL,
                    last_active_at TEXT,
                    FOREIGN KEY (user_id) REFERENCES users(id),
                    UNIQUE(user_id, device_serial)
                );
                CREATE INDEX IF NOT EXISTS idx_user_devices_user ON user_devices(user_id);
                """
            )
            # 安全：清理遗留明文 token（旧版本未做哈希，expires_at 为 NULL）
            try:
                conn.executescript("DELETE FROM sessions WHERE expires_at IS NULL;")
            except Exception as exc:
                logger.warning(f"清理遗留明文 token 失败（忽略）: {exc}")
            conn.commit()
    else:
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
            cur.execute('''
                CREATE TABLE IF NOT EXISTS user_devices (
                    id            SERIAL PRIMARY KEY,
                    user_id       INTEGER NOT NULL,
                    device_serial TEXT NOT NULL,
                    device_alias  TEXT,
                    registered_at TEXT NOT NULL,
                    last_active_at TEXT,
                    FOREIGN KEY (user_id) REFERENCES users(id),
                    UNIQUE(user_id, device_serial)
                )
            ''')
            cur.execute('''
                CREATE INDEX IF NOT EXISTS idx_user_devices_user ON user_devices(user_id)
            ''')
            # 安全：清理遗留明文 token
            try:
                cur.execute("DELETE FROM sessions WHERE expires_at IS NULL;")
            except Exception as exc:
                logger.warning(f"清理遗留明文 token 失败（忽略）: {exc}")


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


class DeviceRegisterRequest(BaseModel):
    device_serial: str
    device_alias: str | None = None

    @field_validator("device_serial")
    @classmethod
    def _check_serial(cls, v: str) -> str:
        v = (v or "").strip()
        if not v or len(v) < 4 or len(v) > 128:
            raise ValueError("device_serial 长度需在 4-128 之间")
        # 仅允许字母数字与常见分隔符，防止注入
        if not re.match(r"^[A-Za-z0-9._:\-]+$", v):
            raise ValueError("device_serial 含非法字符")
        return v

    @field_validator("device_alias")
    @classmethod
    def _check_alias(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if len(v) > 64:
            raise ValueError("device_alias 过长（<=64）")
        return v or None


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


def _hash_token(token: str) -> str:
    """对会话 token 做 SHA-256 哈希；DB 仅存哈希，明文 token 不落盘。"""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _token_expiry(now_iso: str) -> str:
    """生成 token 过期时间（ISO 字符串，now + TOKEN_TTL_DAYS）。"""
    base = datetime.fromisoformat(now_iso) if isinstance(now_iso, str) else now_iso
    return (base + timedelta(days=TOKEN_TTL_DAYS)).isoformat()


def get_bearer_token(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未提供有效的认证信息")
    return auth[7:].strip()


def get_session_user(request: Request) -> dict:
    """校验 token 并返回用户信息字典。

    安全：
    - DB 中 token 列存的是 SHA-256 哈希，这里以哈希查询；
    - 检查 expires_at，过期则视为已撤销；
    - 顺便清理过期/已撤销会话（惰性回收）。
    """
    token = get_bearer_token(request)
    token_hash = _hash_token(token)
    with get_db() as conn:
        cur = _exec_sql(
            conn,
            "SELECT s.token, s.user_id, s.revoked, s.expires_at, u.email, u.created_at, u.last_login_at "
            "FROM sessions s JOIN users u ON s.user_id = u.id "
            "WHERE s.token = ?",
            (token_hash,),
        )
        row = _fetchone_as_dict(cur)
        if not row:
            raise HTTPException(status_code=401, detail="登录已失效，请重新登录")
        # 过期判定
        expired = False
        if row.get("expires_at"):
            try:
                expired = datetime.fromisoformat(row["expires_at"]) < datetime.utcnow()
            except Exception:
                expired = True  # 解析失败视为过期
        if row["revoked"] or expired:
            # 惰性回收：清掉过期/已撤销会话
            try:
                _exec_sql(
                    conn,
                    "DELETE FROM sessions WHERE token = ?",
                    (token_hash,),
                )
            except Exception:
                pass
            raise HTTPException(status_code=401, detail="登录已失效，请重新登录")
    return row


# ======================== FastAPI ========================
app = FastAPI(title="Social Account API", version="1.0.0")
# CORS 白名单：仅允许 lcjx.yun 主站，禁止通配符
_ALLOWED_ORIGINS = os.environ.get("CORS_ALLOWED_ORIGINS", "https://lcjx.yun").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _ALLOWED_ORIGINS if o.strip()],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.on_event("startup")
def _on_startup() -> None:
    try:
        init_db()
        logger.info(f"账号服务数据库已初始化 (后端: {DB_BACKEND})")
    except Exception as e:
        logger.error(f"账号服务数据库初始化失败: {e}")
        raise


@app.on_event("shutdown")
def _on_shutdown() -> None:
    if DB_BACKEND != "sqlite":
        _close_pg_pool()


@app.get("/health")
def health() -> dict[str, Any]:
    return {"success": True, "service": "social-account-api", "db_backend": DB_BACKEND}


@app.post("/auth/register")
def register(req: RegisterRequest) -> dict[str, Any]:
    password_hash = hash_password(req.password)
    now = datetime.utcnow().isoformat()
    with get_db() as conn:
        try:
            if DB_BACKEND == "sqlite":
                cur = _exec_sql(
                    conn,
                    "INSERT INTO users (email, password_hash, created_at, last_login_at) VALUES (?, ?, ?, ?)",
                    (req.email, password_hash, now, now),
                )
                user_id = cur.lastrowid
            else:
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
            if DB_BACKEND == "sqlite":
                import sqlite3 as _sqlite3
                is_duplicate = isinstance(exc, _sqlite3.IntegrityError)
            else:
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
        expires_at = _token_expiry(now)
        _exec_sql(
            conn,
            "INSERT INTO sessions (token, user_id, created_at, expires_at, revoked) "
            "VALUES (?, ?, ?, ?, 0)",
            (_hash_token(token), user_id, now, expires_at),
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
        expires_at = _token_expiry(now)
        _exec_sql(
            conn,
            "INSERT INTO sessions (token, user_id, created_at, expires_at, revoked) "
            "VALUES (?, ?, ?, ?, 0)",
            (_hash_token(token), row["id"], now, expires_at),
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
            (_hash_token(get_bearer_token(request)),),
        )
    return {"success": True, "message": "已退出登录"}


# ======================== 用户设备管理（BOLA 防护示范）========================
# 防御要点：GET/DELETE 单设备时强制 WHERE user_id = ? AND device_serial = ?，
# 防止用户A通过篡改 URL 中的 serial 访问用户B的设备（BOLA / OWASP API1）。

@app.post("/auth/devices", summary="注册当前用户的设备")
def register_device(req: DeviceRegisterRequest, request: Request) -> dict[str, Any]:
    user = get_session_user(request)
    now = datetime.utcnow().isoformat()
    with get_db() as conn:
        try:
            _exec_sql(
                conn,
                "INSERT INTO user_devices (user_id, device_serial, device_alias, registered_at, last_active_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (user["user_id"], req.device_serial, req.device_alias, now, now),
            )
        except Exception as exc:
            # 唯一约束冲突：设备已注册
            is_duplicate = False
            if DB_BACKEND == "sqlite":
                import sqlite3 as _sqlite3
                is_duplicate = isinstance(exc, _sqlite3.IntegrityError)
            else:
                try:
                    from psycopg2.errors import UniqueViolation
                    is_duplicate = isinstance(exc, UniqueViolation)
                except ImportError:
                    is_duplicate = "unique" in str(exc).lower() or "duplicate" in str(exc).lower()
            if is_duplicate:
                # 更新别名 + last_active
                _exec_sql(
                    conn,
                    "UPDATE user_devices SET device_alias = ?, last_active_at = ? "
                    "WHERE user_id = ? AND device_serial = ?",
                    (req.device_alias, now, user["user_id"], req.device_serial),
                )
                return {"success": True, "message": "设备已存在，已更新别名", "data": {"device_serial": req.device_serial}}
            logger.error(f"注册设备时数据库错误: {exc}")
            raise HTTPException(status_code=500, detail="设备注册失败")
    return {
        "success": True,
        "message": "设备注册成功",
        "data": {"device_serial": req.device_serial, "device_alias": req.device_alias},
    }


@app.get("/auth/devices", summary="列出当前用户的所有设备")
def list_devices(request: Request) -> dict[str, Any]:
    user = get_session_user(request)
    with get_db() as conn:
        cur = _exec_sql(
            conn,
            "SELECT device_serial, device_alias, registered_at, last_active_at "
            "FROM user_devices WHERE user_id = ? ORDER BY registered_at DESC",
            (user["user_id"],),
        )
        rows = _fetchall_as_dicts(cur)
    return {"success": True, "data": rows}


@app.get("/auth/devices/{serial}", summary="查询单台设备（含 BOLA 校验）")
def get_device(serial: str, request: Request) -> dict[str, Any]:
    user = get_session_user(request)
    # BOLA 防护：强制 user_id 与 serial 同时匹配
    with get_db() as conn:
        cur = _exec_sql(
            conn,
            "SELECT device_serial, device_alias, registered_at, last_active_at "
            "FROM user_devices WHERE user_id = ? AND device_serial = ?",
            (user["user_id"], serial),
        )
        row = _fetchone_as_dict(cur)
    if not row:
        # 不存在或不属于当前用户：统一返回 404，避免泄露存在性
        raise HTTPException(status_code=404, detail="设备不存在或无权访问")
    return {"success": True, "data": row}


@app.delete("/auth/devices/{serial}", summary="解绑设备（含 BOLA 校验）")
def delete_device(serial: str, request: Request) -> dict[str, Any]:
    user = get_session_user(request)
    # BOLA 防护：DELETE 必须带 user_id 限定
    with get_db() as conn:
        cur = _exec_sql(
            conn,
            "DELETE FROM user_devices WHERE user_id = ? AND device_serial = ?",
            (user["user_id"], serial),
        )
        deleted = cur.rowcount
    if deleted == 0:
        raise HTTPException(status_code=404, detail="设备不存在或无权访问")
    return {"success": True, "message": "设备已解绑", "data": {"device_serial": serial}}


def _fetchall_as_dicts(cur) -> list[dict]:
    """将查询结果全部转为字典列表。"""
    rows = []
    while True:
        row = cur.fetchone()
        if row is None:
            break
        if hasattr(row, "keys"):
            rows.append(dict(row))
        else:
            cols = [desc[0] for desc in cur.description]
            rows.append(dict(zip(cols, row)))
    return rows


if __name__ == "__main__":
    import uvicorn

    init_db()
    uvicorn.run(app, host=HOST, port=PORT)
