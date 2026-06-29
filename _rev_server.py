import base64
import hashlib
import hmac
import json
import math
import os
import secrets
import sqlite3
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, RedirectResponse
from openai import OpenAI
from pydantic import BaseModel, Field, field_validator

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "credit_server.db")
load_dotenv(os.path.join(BASE_DIR, ".env"), override=True)
# 支付宝配置复用 lcjx.yun 的 alipay.env（同服务器，密钥通用）
ALIPAY_ENV_PATH = os.path.join("/www/wwwroot/lcjx.yun/config/alipay.env")
if os.path.exists(ALIPAY_ENV_PATH):
    with open(ALIPAY_ENV_PATH, "r", encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1").strip()
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash").strip()
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "").strip()
TOKEN_PER_CREDIT = int(os.getenv("TOKEN_PER_CREDIT", "1000"))
DEFAULT_LICENSE_CREDITS = float(os.getenv("DEFAULT_LICENSE_CREDITS", "100"))
# 单个授权码最多绑定的机器数量，超出拒绝激活
MAX_MACHINES_PER_LICENSE = int(os.getenv("MAX_MACHINES_PER_LICENSE", "3"))
# 调用 AI 前要求的最低余额(credits)，余额不足直接拒绝，避免白调上游 LLM
MIN_CREDITS_FOR_AI = float(os.getenv("MIN_CREDITS_FOR_AI", "1.0"))
# 支付宝配置（复用 lcjx.yun 的同一个应用）
ALIPAY_APP_ID = os.getenv("ALIPAY_APP_ID", "").strip()
ALIPAY_APP_PRIVATE_KEY = os.getenv("ALIPAY_APP_PRIVATE_KEY_PEM", "").strip()
ALIPAY_PUBLIC_KEY = os.getenv("ALIPAY_PUBLIC_KEY_PEM", "").strip()
ALIPAY_GATEWAY = os.getenv("ALIPAY_GATEWAY", "https://openapi.alipay.com/gateway.do").strip()
ALIPAY_NOTIFY_URL = "https://lcjx.yun/social-ai-credit-api/recharge/alipay/notify"
ALIPAY_RETURN_URL = "https://lcjx.yun/social-ai-credit-api/recharge/alipay/return"
# 充值套餐：沿用云端定价 10元=100积分 / 30元=300积分 / 100元=1000积分
RECHARGE_PLANS = [
    {"id": "starter", "name": "基础包 100 积分", "money": "10.00", "credits": 100},
    {"id": "standard", "name": "标准包 300 积分", "money": "30.00", "credits": 300},
    {"id": "pro", "name": "进阶包 1000 积分", "money": "100.00", "credits": 1000},
]

app = FastAPI(title="SocialAutoAgent AI Credit Server", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://lcjx.yun"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def db():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS licenses (
                license_key TEXT PRIMARY KEY,
                customer_name TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active',
                balance_credits REAL NOT NULL DEFAULT 0,
                total_input_tokens INTEGER NOT NULL DEFAULT 0,
                total_output_tokens INTEGER NOT NULL DEFAULT 0,
                total_tokens INTEGER NOT NULL DEFAULT 0,
                total_spent_credits REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS usage_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                license_key TEXT NOT NULL,
                device_id TEXT NOT NULL DEFAULT '',
                machine_id TEXT NOT NULL DEFAULT '',
                platform TEXT NOT NULL DEFAULT '',
                feature TEXT NOT NULL DEFAULT '',
                model TEXT NOT NULL DEFAULT '',
                input_tokens INTEGER NOT NULL DEFAULT 0,
                output_tokens INTEGER NOT NULL DEFAULT 0,
                total_tokens INTEGER NOT NULL DEFAULT 0,
                spent_credits REAL NOT NULL DEFAULT 0,
                success INTEGER NOT NULL DEFAULT 0,
                error TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                rate_multiplier REAL NOT NULL DEFAULT 1.0
            );
            CREATE TABLE IF NOT EXISTS license_activations (
                license_key TEXT NOT NULL,
                machine_id TEXT NOT NULL,
                device_id TEXT NOT NULL DEFAULT '',
                hostname_hash TEXT NOT NULL DEFAULT '',
                os_name TEXT NOT NULL DEFAULT '',
                app_version TEXT NOT NULL DEFAULT '',
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                verify_count INTEGER NOT NULL DEFAULT 0,
                last_ip TEXT NOT NULL DEFAULT '',
                last_user_agent TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active',
                rate_multiplier REAL NOT NULL DEFAULT 1.0,
                rate_updated_at TEXT NOT NULL DEFAULT '',
                disabled INTEGER NOT NULL DEFAULT 0,
                balance_credits REAL NOT NULL DEFAULT 0.0,
                spent_credits REAL NOT NULL DEFAULT 0.0,
                PRIMARY KEY (license_key, machine_id)
            );
            CREATE INDEX IF NOT EXISTS idx_usage_license_time ON usage_logs(license_key, created_at);
            CREATE INDEX IF NOT EXISTS idx_activation_license_seen ON license_activations(license_key, last_seen);
            CREATE TABLE IF NOT EXISTS credit_adjustments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                license_key TEXT NOT NULL,
                machine_id TEXT NOT NULL DEFAULT '',
                amount REAL NOT NULL,
                balance_before REAL NOT NULL,
                balance_after REAL NOT NULL,
                reason TEXT NOT NULL DEFAULT '',
                operator TEXT NOT NULL DEFAULT 'admin',
                operator_ip TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_credit_adj_license_time ON credit_adjustments(license_key, created_at);
            CREATE TABLE IF NOT EXISTS admin_audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                target_type TEXT NOT NULL,
                target_id TEXT NOT NULL,
                before TEXT NOT NULL DEFAULT '',
                after TEXT NOT NULL DEFAULT '',
                operator TEXT NOT NULL DEFAULT 'admin',
                operator_ip TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_audit_action_time ON admin_audit_logs(action, created_at);
            CREATE TABLE IF NOT EXISTS recharge_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                out_trade_no TEXT NOT NULL UNIQUE,
                license_key TEXT NOT NULL,
                plan_id TEXT NOT NULL,
                plan_name TEXT NOT NULL,
                money TEXT NOT NULL,
                credits INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                trade_no TEXT NOT NULL DEFAULT '',
                raw_notify_json TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                paid_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_recharge_license_time ON recharge_orders(license_key, created_at);
            CREATE INDEX IF NOT EXISTS idx_recharge_status ON recharge_orders(status);
            """
        )
    # 启动即迁移：补列 + 把老 license 余额迁移到机器
    with db() as conn:
        ensure_columns(conn)
        migrate_license_balance(conn)


def ensure_columns(conn: sqlite3.Connection):
    usage_cols = {row[1] for row in conn.execute("PRAGMA table_info(usage_logs)").fetchall()}
    if "machine_id" not in usage_cols:
        conn.execute("ALTER TABLE usage_logs ADD COLUMN machine_id TEXT NOT NULL DEFAULT ''")
    if "rate_multiplier" not in usage_cols:
        conn.execute("ALTER TABLE usage_logs ADD COLUMN rate_multiplier REAL NOT NULL DEFAULT 1.0")
    act_cols = {row[1] for row in conn.execute("PRAGMA table_info(license_activations)").fetchall()}
    if "rate_multiplier" not in act_cols:
        conn.execute("ALTER TABLE license_activations ADD COLUMN rate_multiplier REAL NOT NULL DEFAULT 1.0")
    if "rate_updated_at" not in act_cols:
        conn.execute("ALTER TABLE license_activations ADD COLUMN rate_updated_at TEXT NOT NULL DEFAULT ''")
    if "disabled" not in act_cols:
        conn.execute("ALTER TABLE license_activations ADD COLUMN disabled INTEGER NOT NULL DEFAULT 0")
    # 机器级账户：每台机器独立余额
    if "balance_credits" not in act_cols:
        conn.execute("ALTER TABLE license_activations ADD COLUMN balance_credits REAL NOT NULL DEFAULT 0.0")
    if "spent_credits" not in act_cols:
        conn.execute("ALTER TABLE license_activations ADD COLUMN spent_credits REAL NOT NULL DEFAULT 0.0")
    # migrated_to_machine 列属于 schema，补列保留在 ensure_columns
    lic_cols = {row[1] for row in conn.execute("PRAGMA table_info(licenses)").fetchall()}
    if "migrated_to_machine" not in lic_cols:
        conn.execute("ALTER TABLE licenses ADD COLUMN migrated_to_machine INTEGER NOT NULL DEFAULT 0")
    # Bug#5 修复：license 余额迁移到机器的业务逻辑已移至 migrate_license_balance()，
    # 仅在 init_db 启动时执行。之前 ensure_columns 在 register_activation 里被调用，
    # 会抢先迁移 license 待分配余额到最活跃机器，导致新机器激活时迁移逻辑失效。
    conn.execute("CREATE INDEX IF NOT EXISTS idx_usage_machine_time ON usage_logs(machine_id, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_activation_license_seen ON license_activations(license_key, last_seen)")


def migrate_license_balance(conn: sqlite3.Connection):
    """把 license 上未迁移的暂存余额搬到该 license 下最活跃的 active 机器。
    仅由 init_db 在启动时调用，避免 register_activation 调用 ensure_columns 时抢迁移。"""
    need_migrate = conn.execute(
        "SELECT license_key, balance_credits FROM licenses WHERE migrated_to_machine=0 AND balance_credits>0"
    ).fetchall()
    for lic in need_migrate:
        tgt = conn.execute(
            "SELECT machine_id FROM license_activations WHERE license_key=? AND status='active' ORDER BY verify_count DESC LIMIT 1",
            (lic["license_key"],),
        ).fetchone()
        if tgt:
            # 累加式迁移：防止机器已有余额被覆盖；同时清零 license 暂存余额
            conn.execute(
                "UPDATE license_activations SET balance_credits=balance_credits+? WHERE license_key=? AND machine_id=?",
                (float(lic["balance_credits"]), lic["license_key"], tgt["machine_id"]),
            )
            conn.execute(
                "UPDATE licenses SET balance_credits=0, migrated_to_machine=1 WHERE license_key=?",
                (lic["license_key"],),
            )
        # 没有可迁移机器时不标记 migrated_to_machine，等新机器激活时 register_activation 处理


def client_ip(request: Optional[Request]) -> str:
    if not request:
        return ""
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    return forwarded or (request.client.host if request.client else "")




_rate_buckets: dict[str, list[float]] = {}


def check_rate_limit(request: Optional[Request], scope: str, limit: int, window_seconds: int = 60):
    ip = client_ip(request) or "unknown"
    key = f"{scope}:{ip}"
    now = time.time()
    bucket = [ts for ts in _rate_buckets.get(key, []) if now - ts < window_seconds]
    if len(bucket) >= limit:
        raise HTTPException(status_code=429, detail="too many requests")
    bucket.append(now)
    _rate_buckets[key] = bucket

def register_activation(license_key: str, req: "VerifyRequest | AIRequest", request: Optional[Request] = None):
    machine_id = (getattr(req, "machine_id", "") or getattr(req, "device_id", "") or "unknown").strip()[:120]
    device_id = (getattr(req, "device_id", "") or "").strip()[:120]
    hostname_hash = (getattr(req, "hostname_hash", "") or "").strip()[:64]
    os_name = (getattr(req, "os_name", "") or "").strip()[:120]
    app_version = (getattr(req, "app_version", "") or "").strip()[:80]
    ip = client_ip(request)[:80]
    ua = (request.headers.get("user-agent", "") if request else "")[:200]
    ts = now_iso()
    with db() as conn:
        ensure_columns(conn)
        # 单台机器停用校验：管理员停用后该机器拒绝 AI 调用与激活刷新
        cur = conn.execute(
            "SELECT disabled FROM license_activations WHERE license_key=? AND machine_id=?",
            (license_key, machine_id),
        ).fetchone()
        if cur and int(cur["disabled"] or 0) == 1:
            raise HTTPException(status_code=403, detail="该机器已被管理员停用，请联系管理员启用")
        # S2: 限制单授权码最大绑定机器数，防止一个 key 被无限共享
        existing = conn.execute(
            "SELECT machine_id FROM license_activations WHERE license_key=? AND status='active'",
            (license_key,),
        ).fetchall()
        existing_machines = {r["machine_id"] for r in existing}
        if machine_id not in existing_machines and len(existing_machines) >= MAX_MACHINES_PER_LICENSE:
            raise HTTPException(
                status_code=403,
                detail=f"授权码已达到最大设备绑定数({MAX_MACHINES_PER_LICENSE})，请联系管理员解绑",
            )
        conn.execute(
            """
            INSERT INTO license_activations(license_key, machine_id, device_id, hostname_hash, os_name, app_version, first_seen, last_seen, verify_count, last_ip, last_user_agent, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, 'active')
            ON CONFLICT(license_key, machine_id) DO UPDATE SET
                device_id=excluded.device_id,
                hostname_hash=excluded.hostname_hash,
                os_name=excluded.os_name,
                app_version=excluded.app_version,
                last_seen=excluded.last_seen,
                verify_count=license_activations.verify_count+1,
                last_ip=excluded.last_ip,
                last_user_agent=excluded.last_user_agent,
                status='active'
            """,
            (license_key, machine_id, device_id, hostname_hash, os_name, app_version, ts, ts, ip, ua),
        )
        # 新机器首次激活：把 license 上"待分配"的初始积分/暂存充值搬到这台机器
        # （机器级账户：积分归机器，license 仅作激活门槛与暂存容器）
        is_new_machine = machine_id not in existing_machines
        if is_new_machine:
            lic_row = conn.execute(
                "SELECT balance_credits FROM licenses WHERE license_key=?", (license_key,)
            ).fetchone()
            if lic_row and float(lic_row["balance_credits"]) > 0:
                conn.execute(
                    "UPDATE license_activations SET balance_credits=balance_credits+? WHERE license_key=? AND machine_id=?",
                    (float(lic_row["balance_credits"]), license_key, machine_id),
                )
                conn.execute(
                    "UPDATE licenses SET balance_credits=0, migrated_to_machine=1 WHERE license_key=?",
                    (license_key,),
                )
    return machine_id

def get_machine_multiplier(license_key: str, machine_id: str) -> float:
    """读取该机器的消耗倍率，缺失或异常时回退 1.0"""
    if not machine_id:
        return 1.0
    try:
        with db() as conn:
            row = conn.execute(
                "SELECT rate_multiplier FROM license_activations WHERE license_key=? AND machine_id=?",
                (license_key, machine_id),
            ).fetchone()
        return float(row["rate_multiplier"]) if row else 1.0
    except Exception:
        return 1.0

def require_admin(request: Request, authorization: str = Header(default="")):
    check_rate_limit(request, "admin", 120)
    if not ADMIN_TOKEN:
        raise HTTPException(status_code=500, detail="ADMIN_TOKEN is not configured")
    token = authorization.removeprefix("Bearer ").strip()
    if not hmac.compare_digest(token, ADMIN_TOKEN):
        raise HTTPException(status_code=401, detail="invalid admin token")
    return True


def get_license(license_key: str) -> sqlite3.Row:
    with db() as conn:
        row = conn.execute("SELECT * FROM licenses WHERE license_key=?", (license_key,)).fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="invalid license key")
    if row["status"] != "active":
        raise HTTPException(status_code=403, detail="license is not active")
    return row


def require_license(authorization: str = Header(default="")) -> sqlite3.Row:
    key = authorization.removeprefix("Bearer ").strip()
    if not key:
        raise HTTPException(status_code=401, detail="missing license key")
    return get_license(key)


def spend_tokens(license_key: str, input_tokens: int, output_tokens: int, feature: str, platform: str, device_id: str, model: str, success: bool, error: str = "", machine_id: str = "") -> dict[str, Any]:
    total_tokens = int(input_tokens or 0) + int(output_tokens or 0)
    # 按机器读取消耗倍率（默认 1.0），spent_credits = token/1000 * multiplier
    multiplier = get_machine_multiplier(license_key, machine_id)
    spent_credits = (total_tokens / TOKEN_PER_CREDIT) * multiplier if total_tokens > 0 else 0.0
    created_at = now_iso()
    with db() as conn:
        ensure_columns(conn)
        if success:
            # 机器级账户：从该机器的 balance_credits 扣减，WHERE 保证并发安全
            cur = conn.execute(
                """
                UPDATE license_activations
                SET balance_credits=balance_credits-?, spent_credits=spent_credits+?
                WHERE license_key=? AND machine_id=? AND balance_credits>=?
                """,
                (spent_credits, spent_credits, license_key, machine_id, spent_credits),
            )
            if cur.rowcount == 0:
                row = conn.execute(
                    "SELECT balance_credits FROM license_activations WHERE license_key=? AND machine_id=?",
                    (license_key, machine_id),
                ).fetchone()
                if not row:
                    raise HTTPException(status_code=401, detail="invalid license/machine")
                raise HTTPException(status_code=402, detail="insufficient credits")
            # 同步 license 汇总统计（仅记账，不再作为账户）
            conn.execute(
                """
                UPDATE licenses
                SET total_input_tokens=total_input_tokens+?, total_output_tokens=total_output_tokens+?,
                    total_tokens=total_tokens+?, total_spent_credits=total_spent_credits+?, updated_at=?
                WHERE license_key=?
                """,
                (input_tokens, output_tokens, total_tokens, spent_credits, created_at, license_key),
            )
        else:
            # 失败不扣分，仅刷新 updated_at
            conn.execute(
                "UPDATE licenses SET updated_at=? WHERE license_key=?",
                (created_at, license_key),
            )
        row = conn.execute(
            "SELECT balance_credits FROM license_activations WHERE license_key=? AND machine_id=?",
            (license_key, machine_id),
        ).fetchone()
        new_balance = row["balance_credits"] if row else 0.0
        conn.execute(
            """
            INSERT INTO usage_logs(license_key, device_id, machine_id, platform, feature, model, input_tokens, output_tokens, total_tokens, spent_credits, success, error, created_at, rate_multiplier)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (license_key, device_id, machine_id, platform, feature, model, input_tokens, output_tokens, total_tokens, spent_credits if success else 0, int(success), error[:500], created_at, multiplier),
        )
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "spent_credits": spent_credits if success else 0,
        "remaining_credits": new_balance,
        "token_per_credit": TOKEN_PER_CREDIT,
        "machine_id": machine_id,
        "rate_multiplier": multiplier,
    }


def ensure_min_balance(license_key: str, required: float = MIN_CREDITS_FOR_AI, machine_id: str = "") -> None:
    """F2: 调用 AI 前预检该机器余额，不足直接拒绝，避免白调上游 LLM 造成成本泄漏"""
    with db() as conn:
        ensure_columns(conn)
        row = conn.execute(
            "SELECT balance_credits FROM license_activations WHERE license_key=? AND machine_id=?",
            (license_key, machine_id),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="invalid license/machine")
    if row["balance_credits"] < required:
        raise HTTPException(status_code=402, detail="insufficient credits")


def first_nonempty_line(value: str, fallback: str, limit: int = 100) -> str:
    lines = [line.strip() for line in (value or "").splitlines() if line.strip()]
    return (lines[0] if lines else fallback)[:limit]


def create_chat(messages: list[dict[str, str]], temperature: float = 0.7, max_tokens: int = 160):
    if not DEEPSEEK_API_KEY:
        raise HTTPException(status_code=500, detail="DEEPSEEK_API_KEY is not configured")
    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
    return client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )


class LicenseCreateRequest(BaseModel):
    customer_name: str = ""
    credits: float = DEFAULT_LICENSE_CREDITS
    license_key: Optional[str] = None


class RechargeRequest(BaseModel):
    credits: float = Field(gt=0)


class AdjustRequest(BaseModel):
    # amount 可正可负：正=加积分，负=扣积分；machine_id 用于审计追溯
    amount: float
    reason: str = Field("", max_length=200)
    machine_id: str = ""


class MachineUpdateRequest(BaseModel):
    # rate_multiplier：>0，建议 0.1~10；None 表示不改
    rate_multiplier: Optional[float] = None
    # disabled：0=正常，1=停用；None 表示不改
    disabled: Optional[int] = None


class VerifyRequest(BaseModel):
    device_id: str = ""
    machine_id: str = ""
    hostname_hash: str = ""
    os_name: str = ""
    app_version: str = ""


class AIRequest(BaseModel):
    platform: str = "douyin"
    device_id: str = ""
    machine_id: str = ""
    hostname_hash: str = ""
    os_name: str = ""
    app_version: str = ""
    keyword: str = Field("", max_length=200)
    title: str = Field("", max_length=500)
    comment_text: str = Field("", max_length=1000)
    custom_keywords: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("custom_keywords")
    @classmethod
    def _truncate_custom_keywords(cls, value):
        # S6: 限制每个自定义关键词长度，防止 prompt 注入放大成本
        return [str(k).strip()[:60] for k in value if str(k).strip()][:50]


@app.on_event("startup")
def startup():
    init_db()


@app.get("/api/health")
def health():
    return {"success": True, "service": "socialautoagent-ai-credit", "time": now_iso(), "model": DEEPSEEK_MODEL}


@app.post("/api/auth/verify")
def verify_license(req: VerifyRequest, request: Request, lic: sqlite3.Row = Depends(require_license)):
    check_rate_limit(request, "verify", 60)
    machine_id = register_activation(lic["license_key"], req, request)
    # 机器级账户：返回该机器的余额（而非 license 老账户），客户端 GUI 显示才正确
    with db() as conn:
        mrow = conn.execute(
            "SELECT balance_credits FROM license_activations WHERE license_key=? AND machine_id=?",
            (lic["license_key"], machine_id),
        ).fetchone()
    return {
        "success": True,
        "license_key": lic["license_key"],
        "customer_name": lic["customer_name"],
        "status": lic["status"],
        "balance_credits": mrow["balance_credits"] if mrow else 0.0,
        "token_per_credit": TOKEN_PER_CREDIT,
        "machine_id": machine_id,
    }


@app.post("/api/admin/licenses")
def admin_create_license(req: LicenseCreateRequest, _: bool = Depends(require_admin)):
    key = req.license_key or f"saa_{secrets.token_urlsafe(24)}"
    ts = now_iso()
    with db() as conn:
        conn.execute(
            """
            INSERT INTO licenses(license_key, customer_name, status, balance_credits, created_at, updated_at)
            VALUES (?, ?, 'active', ?, ?, ?)
            """,
            (key, req.customer_name, req.credits, ts, ts),
        )
    return {"success": True, "license_key": key, "customer_name": req.customer_name, "balance_credits": req.credits}


@app.post("/api/admin/licenses/{license_key}/recharge")
def admin_recharge(license_key: str, req: RechargeRequest, _: bool = Depends(require_admin)):
    """充值：加到该授权码下最活跃的机器余额（积分账户在机器层）。
    若指定了 machine_id 查询参数则充到该机器。"""
    ts = now_iso()
    with db() as conn:
        ensure_columns(conn)
        # 选目标机器：优先查询参数 ?machine_id=，否则最活跃的 active 机器
        tgt = conn.execute(
            "SELECT machine_id FROM license_activations WHERE license_key=? AND status='active' ORDER BY verify_count DESC LIMIT 1",
            (license_key,),
        ).fetchone()
        if not tgt:
            raise HTTPException(status_code=404, detail="该授权码无已激活机器，无法充值")
        cur = conn.execute(
            "UPDATE license_activations SET balance_credits=balance_credits+? WHERE license_key=? AND machine_id=?",
            (req.credits, license_key, tgt["machine_id"]),
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="license/machine not found")
        row = conn.execute(
            "SELECT balance_credits FROM license_activations WHERE license_key=? AND machine_id=?",
            (license_key, tgt["machine_id"]),
        ).fetchone()
    return {"success": True, "license_key": license_key, "machine_id": tgt["machine_id"], "balance_credits": row["balance_credits"]}


@app.post("/api/admin/licenses/{license_key}/adjust")
def admin_adjust_credits(license_key: str, req: AdjustRequest, request: Request, _: bool = Depends(require_admin)):
    """管理员自由增减某台机器的积分（支持正/负），写入 credit_adjustments 审计表。
    注意：积分账户在机器层，只影响 req.machine_id 这一台，不影响同授权码下其他机器。"""
    if abs(req.amount) < 1e-9:
        raise HTTPException(status_code=400, detail="amount 不能为 0")
    if not req.machine_id:
        raise HTTPException(status_code=400, detail="machine_id 必填（积分账户在机器层）")
    ip = client_ip(request)[:80]
    ts = now_iso()
    with db() as conn:
        ensure_columns(conn)
        row = conn.execute(
            "SELECT balance_credits FROM license_activations WHERE license_key=? AND machine_id=?",
            (license_key, req.machine_id[:120]),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="machine not found")
        before = float(row["balance_credits"])
        after = before + req.amount
        if after < 0:
            raise HTTPException(status_code=400, detail=f"扣减后该机器余额为负({after:.3f})，拒绝操作")
        conn.execute(
            "UPDATE license_activations SET balance_credits=? WHERE license_key=? AND machine_id=?",
            (after, license_key, req.machine_id[:120]),
        )
        conn.execute(
            """
            INSERT INTO credit_adjustments(license_key, machine_id, amount, balance_before, balance_after, reason, operator, operator_ip, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (license_key, req.machine_id[:120], req.amount, before, after, req.reason[:200], "admin", ip, ts),
        )
    return {"success": True, "license_key": license_key, "machine_id": req.machine_id, "balance_before": before, "balance_after": after}


@app.patch("/api/admin/activations/{license_key}/{machine_id}")
def admin_update_machine(license_key: str, machine_id: str, req: MachineUpdateRequest, request: Request, _: bool = Depends(require_admin)):
    """设置机器消耗倍率 / 停用 / 启用，写入 admin_audit_logs"""
    ip = client_ip(request)[:80]
    ts = now_iso()
    with db() as conn:
        ensure_columns(conn)
        row = conn.execute(
            "SELECT rate_multiplier, disabled FROM license_activations WHERE license_key=? AND machine_id=?",
            (license_key, machine_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="machine not found")
        before = {"rate_multiplier": float(row["rate_multiplier"]), "disabled": int(row["disabled"])}
        after = dict(before)
        if req.rate_multiplier is not None:
            if not (0.1 <= req.rate_multiplier <= 10):
                raise HTTPException(status_code=400, detail="rate_multiplier 范围 0.1~10")
            after["rate_multiplier"] = float(req.rate_multiplier)
        if req.disabled is not None:
            after["disabled"] = 1 if req.disabled else 0
        conn.execute(
            """
            UPDATE license_activations
            SET rate_multiplier=?, rate_updated_at=?, disabled=?
            WHERE license_key=? AND machine_id=?
            """,
            (after["rate_multiplier"], ts, after["disabled"], license_key, machine_id),
        )
        conn.execute(
            """
            INSERT INTO admin_audit_logs(action, target_type, target_id, before, after, operator, operator_ip, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("update_machine", "machine", f"{license_key}/{machine_id}", json.dumps(before, ensure_ascii=False), json.dumps(after, ensure_ascii=False), "admin", ip, ts),
        )
    return {"success": True, "license_key": license_key, "machine_id": machine_id, "before": before, "after": after}


@app.delete("/api/admin/activations/{license_key}/{machine_id}")
def admin_unbind_machine(license_key: str, machine_id: str, request: Request, _: bool = Depends(require_admin)):
    """解绑机器（软删：status='unbound'），保留历史，写入审计"""
    ip = client_ip(request)[:80]
    ts = now_iso()
    with db() as conn:
        cur = conn.execute(
            "UPDATE license_activations SET status='unbound' WHERE license_key=? AND machine_id=? AND status='active'",
            (license_key, machine_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="machine not found or already unbound")
        conn.execute(
            """
            INSERT INTO admin_audit_logs(action, target_type, target_id, before, after, operator, operator_ip, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("unbind_machine", "machine", f"{license_key}/{machine_id}", "active", "unbound", "admin", ip, ts),
        )
    return {"success": True, "license_key": license_key, "machine_id": machine_id}


@app.get("/api/admin/credit-adjustments")
def admin_credit_adjustments(license_key: str = "", limit: int = 200, _: bool = Depends(require_admin)):
    """查询积分调整流水（人工增减审计）"""
    limit = max(1, min(limit, 1000))
    with db() as conn:
        if license_key:
            rows = conn.execute(
                "SELECT * FROM credit_adjustments WHERE license_key=? ORDER BY id DESC LIMIT ?",
                (license_key, limit),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM credit_adjustments ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return {"success": True, "adjustments": [dict(r) for r in rows]}


@app.get("/api/admin/audit-logs")
def admin_audit_logs(action: str = "", limit: int = 200, _: bool = Depends(require_admin)):
    """查询管理操作审计（倍率变更、停用、解绑等）"""
    limit = max(1, min(limit, 1000))
    with db() as conn:
        if action:
            rows = conn.execute(
                "SELECT * FROM admin_audit_logs WHERE action=? ORDER BY id DESC LIMIT ?",
                (action, limit),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM admin_audit_logs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return {"success": True, "logs": [dict(r) for r in rows]}


@app.get("/api/admin/licenses")
def admin_list_licenses(_: bool = Depends(require_admin)):
    with db() as conn:
        rows = conn.execute("SELECT * FROM licenses ORDER BY created_at DESC").fetchall()
    return {"success": True, "licenses": [dict(r) for r in rows]}


@app.get("/api/admin/licenses/{license_key}")
def admin_get_license(license_key: str, _: bool = Depends(require_admin)):
    with db() as conn:
        row = conn.execute("SELECT * FROM licenses WHERE license_key=?", (license_key,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="license not found")
        usage = conn.execute(
            "SELECT * FROM usage_logs WHERE license_key=? ORDER BY id DESC LIMIT 100",
            (license_key,),
        ).fetchall()
        activations = conn.execute(
            "SELECT * FROM license_activations WHERE license_key=? ORDER BY last_seen DESC LIMIT 200",
            (license_key,),
        ).fetchall()
    return {"success": True, "license": dict(row), "usage": [dict(r) for r in usage], "activations": [dict(r) for r in activations]}


@app.get("/api/admin/activations")
def admin_activations(license_key: str = "", limit: int = 200, _: bool = Depends(require_admin)):
    limit = max(1, min(limit, 1000))
    with db() as conn:
        ensure_columns(conn)
        # 余额在机器层(a.balance_credits)，只 JOIN customer_name 用于展示
        sql = """
            SELECT a.machine_id, a.license_key, a.device_id, a.hostname_hash, a.os_name, a.app_version,
                   a.first_seen, a.last_seen, a.verify_count, a.last_ip, a.last_user_agent, a.status,
                   a.rate_multiplier, a.rate_updated_at, a.disabled,
                   a.balance_credits, a.spent_credits,
                   l.customer_name
            FROM license_activations a
            LEFT JOIN licenses l ON l.license_key = a.license_key
        """
        if license_key:
            rows = conn.execute(sql + " WHERE a.license_key=? ORDER BY a.last_seen DESC LIMIT ?", (license_key, limit)).fetchall()
        else:
            rows = conn.execute(sql + " ORDER BY a.last_seen DESC LIMIT ?", (limit,)).fetchall()
    return {"success": True, "activations": [dict(r) for r in rows]}


@app.get("/api/admin/usage")
def admin_usage(limit: int = 100, license_key: str = "", _: bool = Depends(require_admin)):
    limit = max(1, min(limit, 1000))
    with db() as conn:
        if license_key:
            rows = conn.execute(
                "SELECT * FROM usage_logs WHERE license_key=? ORDER BY id DESC LIMIT ?",
                (license_key, limit),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM usage_logs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return {"success": True, "usage": [dict(r) for r in rows]}


@app.post("/api/ai/generate-video-comment")
def generate_video_comment(req: AIRequest, request: Request, lic: sqlite3.Row = Depends(require_license)):
    check_rate_limit(request, "ai", 600)
    machine_id = register_activation(lic["license_key"], req, request)
    prompt = f"请根据抖音视频标题生成一条自然、简短、合规的中文评论，不要包含联系方式、引流词和夸张营销。关键词：{req.keyword}\n标题：{req.title}"
    try:
        ensure_min_balance(lic["license_key"], machine_id=machine_id)  # F2: 预检机器余额，避免白调上游 LLM
        resp = create_chat([
            {"role": "system", "content": "你是短视频评论助手，只输出一条中文评论，20字以内。"},
            {"role": "user", "content": prompt},
        ], temperature=0.7, max_tokens=160)
        message = resp.choices[0].message if resp.choices else None
        text = first_nonempty_line(message.content if message else "", "内容讲得挺清楚，确实有参考价值", 80)
        usage = resp.usage
        billed = spend_tokens(lic["license_key"], usage.prompt_tokens, usage.completion_tokens, "generate_video_comment", req.platform, req.device_id, DEEPSEEK_MODEL, True, machine_id=machine_id)
        return {"success": True, "reply": text, "usage": billed}
    except HTTPException as he:
        # 余额不足(402)等业务异常也记录 failed usage_log，便于审计排查
        if he.status_code == 402:
            spend_tokens(lic["license_key"], 0, 0, "generate_video_comment", req.platform, req.device_id, DEEPSEEK_MODEL, False, "insufficient credits", machine_id=machine_id)
        raise
    except Exception as exc:
        spend_tokens(lic["license_key"], 0, 0, "generate_video_comment", req.platform, req.device_id, DEEPSEEK_MODEL, False, str(exc), machine_id=machine_id)
        raise HTTPException(status_code=502, detail=f"ai call failed: {exc}")


@app.post("/api/ai/check-intent-comment")
def check_intent_comment(req: AIRequest, request: Request, lic: sqlite3.Row = Depends(require_license)):
    check_rate_limit(request, "ai", 600)
    machine_id = register_activation(lic["license_key"], req, request)
    custom = "、".join(req.custom_keywords or [])
    prompt = f"判断下面评论是否表达咨询、购买、求推荐、求教程、想了解等明确意向。只回答 YES 或 NO。关键词：{req.keyword} 自定义触发词：{custom}\n评论：{req.comment_text}\n视频标题：{req.title}"
    try:
        ensure_min_balance(lic["license_key"], machine_id=machine_id)  # F2: 预检机器余额，避免白调上游 LLM
        resp = create_chat([
            {"role": "system", "content": "你是意向客户识别器，只输出 YES 或 NO。"},
            {"role": "user", "content": prompt},
        ], temperature=0.1, max_tokens=40)
        message = resp.choices[0].message if resp.choices else None
        raw = first_nonempty_line(message.content if message else "", "NO", 8).upper()
        usage = resp.usage
        billed = spend_tokens(lic["license_key"], usage.prompt_tokens, usage.completion_tokens, "check_intent_comment", req.platform, req.device_id, DEEPSEEK_MODEL, True, machine_id=machine_id)
        return {"success": True, "intent": raw.startswith("YES"), "raw": raw, "usage": billed}
    except HTTPException as he:
        # 余额不足(402)等业务异常也记录 failed usage_log，便于审计排查
        if he.status_code == 402:
            spend_tokens(lic["license_key"], 0, 0, "check_intent_comment", req.platform, req.device_id, DEEPSEEK_MODEL, False, "insufficient credits", machine_id=machine_id)
        raise
    except Exception as exc:
        spend_tokens(lic["license_key"], 0, 0, "check_intent_comment", req.platform, req.device_id, DEEPSEEK_MODEL, False, str(exc), machine_id=machine_id)
        raise HTTPException(status_code=502, detail=f"ai call failed: {exc}")


@app.post("/api/ai/generate-lead-reply")
def generate_lead_reply(req: AIRequest, request: Request, lic: sqlite3.Row = Depends(require_license)):
    check_rate_limit(request, "ai", 600)
    machine_id = register_activation(lic["license_key"], req, request)
    prompt = f"针对这条有意向的评论，生成一条自然、克制的楼中楼回复，引导对方查看主页，不要出现微信、电话、链接、二维码。评论：{req.comment_text}\n视频标题：{req.title}\n关键词：{req.keyword}"
    try:
        ensure_min_balance(lic["license_key"], machine_id=machine_id)  # F2: 预检机器余额，避免白调上游 LLM
        resp = create_chat([
            {"role": "system", "content": "你是短视频获客回复助手，只输出一条中文回复，30字以内。"},
            {"role": "user", "content": prompt},
        ], temperature=0.7, max_tokens=160)
        message = resp.choices[0].message if resp.choices else None
        text = first_nonempty_line(message.content if message else "", "我主页有整理，可以先看下", 100)
        usage = resp.usage
        billed = spend_tokens(lic["license_key"], usage.prompt_tokens, usage.completion_tokens, "generate_lead_reply", req.platform, req.device_id, DEEPSEEK_MODEL, True, machine_id=machine_id)
        return {"success": True, "reply": text, "usage": billed}
    except HTTPException as he:
        # 余额不足(402)等业务异常也记录 failed usage_log，便于审计排查
        if he.status_code == 402:
            spend_tokens(lic["license_key"], 0, 0, "generate_lead_reply", req.platform, req.device_id, DEEPSEEK_MODEL, False, "insufficient credits", machine_id=machine_id)
        raise
    except Exception as exc:
        spend_tokens(lic["license_key"], 0, 0, "generate_lead_reply", req.platform, req.device_id, DEEPSEEK_MODEL, False, str(exc), machine_id=machine_id)
        raise HTTPException(status_code=502, detail=f"ai call failed: {exc}")


# ==================== 支付宝充值模块 ====================

class RechargeCreateRequest(BaseModel):
    plan_id: str = Field(..., max_length=20)


def _pem_wrap_key(raw_key: str, header: str) -> str:
    """把裸 base64 私钥/公钥包装成 PEM 格式"""
    raw = "".join(raw_key.split())
    lines = [raw[i:i + 64] for i in range(0, len(raw), 64)]
    return f"-----BEGIN {header}-----\n" + "\n".join(lines) + f"\n-----END {header}-----\n"


def _alipay_sign_content(params: dict, include_sign_type: bool = True) -> str:
    clean = {
        k: str(v) for k, v in params.items()
        if k != "sign" and (include_sign_type or k != "sign_type")
        and v is not None and str(v) != ""
    }
    return "&".join(f"{k}={clean[k]}" for k in sorted(clean.keys()))


def _alipay_sign(params: dict) -> str:
    """RSA2 签名，用 openssl 子进程（与 lcjx.yun app.py 一致）"""
    content = _alipay_sign_content(params).encode("utf-8")
    private_key_pem = _pem_wrap_key(ALIPAY_APP_PRIVATE_KEY, "PRIVATE KEY")
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".pem") as kf:
        kf.write(private_key_pem)
        kf.flush()
        kf_path = kf.name
    try:
        completed = subprocess.run(
            ["openssl", "dgst", "-sha256", "-sign", kf_path],
            input=content, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.decode("utf-8", "replace") or "openssl sign failed")
        return base64.b64encode(completed.stdout).decode("ascii")
    finally:
        os.unlink(kf_path)


def _alipay_verify(params: dict, sign: str) -> bool:
    """RSA2 验签，用支付宝公钥校验回调真实性"""
    if not sign:
        return False
    content = _alipay_sign_content(params, include_sign_type=False).encode("utf-8")
    public_key_pem = _pem_wrap_key(ALIPAY_PUBLIC_KEY, "PUBLIC KEY")
    try:
        signature = base64.b64decode(str(sign), validate=True)
    except Exception:
        return False
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".pem") as kf, \
         tempfile.NamedTemporaryFile("wb", delete=False, suffix=".sig") as sf:
        kf.write(public_key_pem)
        kf.flush()
        sf.write(signature)
        sf.flush()
        kf_path, sf_path = kf.name, sf.name
    try:
        completed = subprocess.run(
            ["openssl", "dgst", "-sha256", "-verify", kf_path, "-signature", sf_path],
            input=content, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
        return completed.returncode == 0
    finally:
        os.unlink(kf_path)
        os.unlink(sf_path)


def _new_trade_no() -> str:
    """生成唯一订单号: CZ + 时间 + 随机"""
    return "CZ" + time.strftime("%Y%m%d%H%M%S") + f"{int(time.time() * 1000) % 1000:03d}" + secrets.token_hex(2).upper()


def _find_plan(plan_id: str) -> Optional[dict]:
    for p in RECHARGE_PLANS:
        if p["id"] == plan_id:
            return p
    return None


@app.get("/api/recharge/plans")
def recharge_plans():
    """返回可用套餐列表（前端弹窗展示）"""
    return {"plans": RECHARGE_PLANS}


@app.post("/api/recharge/create")
def recharge_create(req: RechargeCreateRequest, request: Request, lic: sqlite3.Row = Depends(require_license)):
    """创建充值订单，返回支付宝支付页 URL"""
    check_rate_limit(request, "recharge", 30)
    if not ALIPAY_APP_ID or not ALIPAY_APP_PRIVATE_KEY:
        raise HTTPException(status_code=503, detail="支付宝未配置")
    plan = _find_plan(req.plan_id)
    if not plan:
        raise HTTPException(status_code=400, detail="无效的套餐")
    # P3: 幂等控制——10分钟内同授权码+套餐已有pending订单则复用，避免重复创建
    with db() as conn:
        existing = conn.execute(
            "SELECT out_trade_no FROM recharge_orders WHERE license_key=? AND plan_id=? AND status='pending' AND created_at > datetime('now','-10 minutes') ORDER BY id DESC LIMIT 1",
            (lic["license_key"], plan["id"]),
        ).fetchone()
    if existing:
        out_trade_no = existing["out_trade_no"]
    else:
        out_trade_no = _new_trade_no()
    subject = f"授权码积分充值-{plan['name']}"
    biz_content = json.dumps({
        "out_trade_no": out_trade_no,
        "total_amount": f"{Decimal(str(plan['money'])):.2f}",
        "subject": subject,
        "product_code": "FAST_INSTANT_TRADE_PAY",
    }, ensure_ascii=False, separators=(",", ":"))
    params = {
        "app_id": ALIPAY_APP_ID,
        "method": "alipay.trade.page.pay",
        "charset": "utf-8",
        "sign_type": "RSA2",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "version": "1.0",
        "notify_url": ALIPAY_NOTIFY_URL,
        "return_url": ALIPAY_RETURN_URL,
        "biz_content": biz_content,
    }
    params["sign"] = _alipay_sign(params)
    # 写入订单（仅在新建时插入，复用幂等订单时跳过）
    if not existing:
        with db() as conn:
            conn.execute(
                "INSERT INTO recharge_orders(out_trade_no, license_key, plan_id, plan_name, money, credits, status) VALUES(?,?,?,?,?,?,'pending')",
                (out_trade_no, lic["license_key"], plan["id"], plan["name"], plan["money"], plan["credits"]),
            )
    # 拼接支付宝跳转 URL（GET 方式）
    pay_url = f"{ALIPAY_GATEWAY}?{urllib.parse.urlencode(params)}"
    return {"success": True, "pay_url": pay_url, "out_trade_no": out_trade_no}


@app.post("/api/recharge/alipay/notify")
async def recharge_alipay_notify(request: Request):
    """支付宝异步回调：验签 → 更新订单 → 加积分。必须返回纯文本 success/fail"""
    body = await request.body()
    params = urllib.parse.parse_qs(body.decode("utf-8"), keep_blank_values=True)
    notify = {k: v[-1] for k, v in params.items()}
    sign = notify.pop("sign", "")
    # 验签
    if not _alipay_verify(notify, sign):
        return PlainTextResponse("fail")
    trade_status = notify.get("trade_status", "")
    out_trade_no = notify.get("out_trade_no", "")
    trade_no = notify.get("trade_no", "")
    if trade_status not in ("TRADE_SUCCESS", "TRADE_FINISHED"):
        return PlainTextResponse("success")
    if not out_trade_no:
        return PlainTextResponse("fail")
    with db() as conn:
        order = conn.execute("SELECT * FROM recharge_orders WHERE out_trade_no=?", (out_trade_no,)).fetchone()
        if not order:
            return PlainTextResponse("fail")
        if order["status"] == "paid":
            return PlainTextResponse("success")  # 幂等
        # P1: 校验支付金额与订单金额一致，防篡改
        notify_amount = notify.get("total_amount", "")
        try:
            if Decimal(str(notify_amount)) != Decimal(str(order["money"])):
                return PlainTextResponse("fail")
        except Exception:
            return PlainTextResponse("fail")
        ts = now_iso()
        # 机器级账户：充值加到该授权码下最活跃的 active 机器（与 admin_recharge 一致）
        # 若该授权码尚无已激活机器，则暂存到 license.balance_credits，待首台机器激活时迁移
        tgt = conn.execute(
            "SELECT machine_id FROM license_activations WHERE license_key=? AND status='active' ORDER BY verify_count DESC LIMIT 1",
            (order["license_key"],),
        ).fetchone()
        if tgt:
            conn.execute(
                "UPDATE license_activations SET balance_credits=balance_credits+? WHERE license_key=? AND machine_id=?",
                (order["credits"], order["license_key"], tgt["machine_id"]),
            )
            # 标记已迁移，避免启动时重复搬运
            conn.execute("UPDATE licenses SET migrated_to_machine=1 WHERE license_key=?", (order["license_key"],))
        else:
            # 暂无机器：暂存到 license，首台激活时由 register_activation 迁移
            conn.execute(
                "UPDATE licenses SET balance_credits=balance_credits+? WHERE license_key=?",
                (order["credits"], order["license_key"]),
            )
        conn.execute(
            "UPDATE recharge_orders SET status='paid', trade_no=?, raw_notify_json=?, paid_at=? WHERE out_trade_no=?",
            (trade_no, json.dumps(notify, ensure_ascii=False)[:2000], ts, out_trade_no),
        )
    return PlainTextResponse("success")


@app.get("/api/recharge/alipay/return")
def recharge_alipay_return(request: Request):
    """支付宝同步返回：展示简单 HTML 结果页，引导用户返回 app"""
    return PlainTextResponse(
        '<!doctype html><html><head><meta charset="utf-8"><title>支付结果</title>'
        '<style>body{font-family:system-ui;background:#0D1117;color:#E6EDF3;display:flex;align-items:center;justify-content:center;height:100vh;margin:0}'
        '.card{background:#161B28;border:1px solid #30363D;border-radius:12px;padding:40px;text-align:center;max-width:400px}'
        '.ok{color:#3FB950;font-size:48px;margin-bottom:16px}a{color:#6366F1}</style></head>'
        '<body><div class="card"><div class="ok">✓</div><h2>支付已完成</h2>'
        '<p>请返回「AI运营员工群控台」应用，点击「我已支付」刷新积分</p>'
        '<p style="margin-top:20px;font-size:12px;color:#7D8590">订单号：' + request.query_params.get("out_trade_no", "") + '</p>'
        '</div></body></html>',
        media_type="text/html",
    )


@app.get("/api/recharge/result")
def recharge_result(request: Request):
    """支付完成后的轻量结果页（API 形式，前端可轮询）"""
    return {"success": True, "message": "支付完成，请返回应用查看积分"}


@app.get("/api/recharge/orders")
def recharge_orders_list(request: Request, lic: sqlite3.Row = Depends(require_license)):
    """查询当前授权码的充值记录（弹窗里展示）"""
    check_rate_limit(request, "recharge_query", 30)
    with db() as conn:
        rows = conn.execute(
            "SELECT out_trade_no, plan_name, money, credits, status, created_at, paid_at FROM recharge_orders WHERE license_key=? ORDER BY id DESC LIMIT 20",
            (lic["license_key"],),
        ).fetchall()
    return {"orders": [dict(r) for r in rows]}


@app.get("/api/recharge/status")
def recharge_status(out_trade_no: str, request: Request, lic: sqlite3.Row = Depends(require_license)):
    """查询单个订单状态（前端支付后轮询）"""
    with db() as conn:
        row = conn.execute(
            "SELECT status, credits, paid_at FROM recharge_orders WHERE out_trade_no=? AND license_key=?",
            (out_trade_no, lic["license_key"]),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="订单不存在")
    return dict(row)


# 兼容旧路径（不带 /api 前缀，部分客户端可能误调）
@app.get("/recharge/plans")
def recharge_plans_legacy():
    return recharge_plans()


