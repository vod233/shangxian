-- ===========================================
-- PostgreSQL 初始化脚本
-- 首次启动容器时自动执行
-- ===========================================

-- 账号认证表（原 server_side/social-account-api/accounts.db）
CREATE TABLE IF NOT EXISTS users (
    id            SERIAL PRIMARY KEY,
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

-- 业务记录表会在应用代码中按天自动创建（records_YYYYMMDD）
-- 此处仅创建账号相关表
