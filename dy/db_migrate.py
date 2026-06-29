"""
SQLite → PostgreSQL 数据迁移脚本
================================
将 SQLite 中所有 records_YYYYMMDD 表的数据迁移到 PostgreSQL。

用法：
    # 1. 先启动 PostgreSQL（docker-compose up -d）
    # 2. 安装依赖（pip install psycopg2-binary）
    # 3. 配置环境变量或直接修改下方默认值
    # 4. 运行迁移：
    python -m dy.db_migrate

    # 可选参数：
    python -m dy.db_migrate --sqlite data/scout_records.db --dry-run
"""
import os
import sys
import sqlite3
import logging

logger = logging.getLogger(__name__)


def _get_sqlite_path():
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(project_root, "data", "scout_records.db")


def _get_pg_conn():
    import psycopg2
    return psycopg2.connect(
        host=os.environ.get("PG_HOST", "127.0.0.1"),
        port=int(os.environ.get("PG_PORT", "5432")),
        dbname=os.environ.get("PG_DB", "scout"),
        user=os.environ.get("PG_USER", "scout"),
        password=os.environ.get("PG_PASSWORD", "scout123"),
    )


# 所有字段（按 SQLiteDBManager 的建表 + 扩展字段）
ALL_COLUMNS = [
    "id", "video_id", "keyword", "note_title", "ai_reply", "url",
    "liked", "commented", "followed", "private_messaged", "created_at",
    "video_index", "keyword_index", "process_status", "skip_reason",
    "stay_duration", "long_watch", "recovery_attempts",
    "intent_comment", "lead_reply", "lead_sent", "lead_pm_sent", "pm_sent",
    "follower_count", "error_message", "action_log",
]


def list_sqlite_tables(sqlite_path):
    """列出 SQLite 中所有 records_ 开头的表"""
    conn = sqlite3.connect(sqlite_path)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'records_%' ORDER BY name"
    )
    tables = [row[0] for row in cursor.fetchall()]
    conn.close()
    return tables


def get_sqlite_columns(sqlite_path, table_name):
    """获取 SQLite 表的实际列名（可能有旧表缺少扩展字段）"""
    conn = sqlite3.connect(sqlite_path)
    cursor = conn.cursor()
    cursor.execute(f"PRAGMA table_info({table_name})")
    cols = {row[1] for row in cursor.fetchall()}
    conn.close()
    return cols


def migrate_table(sqlite_path, table_name, pg_conn, dry_run=False):
    """迁移单个表"""
    existing_cols = get_sqlite_columns(sqlite_path, table_name)
    # 只迁移 SQLite 中实际存在的列
    cols_to_migrate = [c for c in ALL_COLUMNS if c in existing_cols]
    col_list = ", ".join(cols_to_migrate)
    placeholders = ", ".join(["%s"] * len(cols_to_migrate))

    # 确保 PostgreSQL 中的表存在（结构与 PostgresDBManager._init_daily_table 一致）
    pg_cur = pg_conn.cursor()
    pg_cur.execute(f'''
        CREATE TABLE IF NOT EXISTS {table_name} (
            id SERIAL PRIMARY KEY,
            video_id TEXT NOT NULL,
            keyword TEXT,
            note_title TEXT DEFAULT '',
            ai_reply TEXT DEFAULT '',
            url TEXT,
            liked INTEGER DEFAULT 0,
            commented INTEGER DEFAULT 0,
            followed INTEGER DEFAULT 0,
            private_messaged INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            video_index INTEGER DEFAULT 0,
            keyword_index INTEGER DEFAULT 0,
            process_status TEXT DEFAULT '',
            skip_reason TEXT DEFAULT '',
            stay_duration REAL DEFAULT 0,
            long_watch INTEGER DEFAULT 0,
            recovery_attempts INTEGER DEFAULT 0,
            intent_comment TEXT DEFAULT '',
            lead_reply TEXT DEFAULT '',
            lead_sent INTEGER DEFAULT 0,
            lead_pm_sent INTEGER DEFAULT 0,
            pm_sent INTEGER DEFAULT 0,
            follower_count TEXT DEFAULT '',
            error_message TEXT DEFAULT '',
            action_log TEXT DEFAULT '[]'
        )
    ''')
    pg_cur.execute(f'''
        CREATE INDEX IF NOT EXISTS idx_{table_name}_video_id
        ON {table_name} (video_id)
    ''')

    # 读取 SQLite 数据
    sqlite_conn = sqlite3.connect(sqlite_path)
    sqlite_cur = sqlite_conn.cursor()
    sqlite_cur.execute(f"SELECT {col_list} FROM {table_name}")
    rows = sqlite_cur.fetchall()
    sqlite_conn.close()

    if not rows:
        logger.info(f"  {table_name}: 无数据，跳过")
        pg_cur.close()
        return 0

    if dry_run:
        logger.info(f"  {table_name}: [DRY-RUN] 将迁移 {len(rows)} 行")
        pg_cur.close()
        return len(rows)

    # 批量插入 PostgreSQL（跳过 id 冲突，使用 ON CONFLICT DO NOTHING）
    # 注意：id 列在 PostgreSQL 中是 SERIAL，自动分配，不使用 SQLite 的 id
    non_id_cols = [c for c in cols_to_migrate if c != "id"]
    non_id_col_list = ", ".join(non_id_cols)
    non_id_placeholders = ", ".join(["%s"] * len(non_id_cols))

    insert_sql = f'''
        INSERT INTO {table_name} ({non_id_col_list})
        VALUES ({non_id_placeholders})
    '''

    batch = []
    for row in rows:
        # 去掉 id 列的值
        row_dict = dict(zip(cols_to_migrate, row))
        values = [row_dict[c] for c in non_id_cols]
        batch.append(values)

    pg_cur.executemany(insert_sql, batch)
    pg_conn.commit()
    pg_cur.close()

    logger.info(f"  {table_name}: 已迁移 {len(rows)} 行")
    return len(rows)


def migrate_accounts_db(pg_conn, dry_run=False):
    """迁移账号数据库（users + sessions）"""
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    accounts_db = os.path.join(project_root, "server_side", "social-account-api", "data", "accounts.db")

    if not os.path.exists(accounts_db):
        logger.info("账号数据库不存在，跳过账号迁移")
        return 0

    sqlite_conn = sqlite3.connect(accounts_db)
    sqlite_conn.row_factory = sqlite3.Row
    sqlite_cur = sqlite_conn.cursor()
    pg_cur = pg_conn.cursor()

    total = 0

    # 确保 PostgreSQL 中表存在
    pg_cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id            SERIAL PRIMARY KEY,
            email         TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at    TEXT NOT NULL,
            last_login_at TEXT
        )
    ''')
    pg_cur.execute('''
        CREATE TABLE IF NOT EXISTS sessions (
            token      TEXT PRIMARY KEY,
            user_id    INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT,
            revoked    INTEGER DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    pg_cur.execute('CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)')

    # 迁移 users 表
    try:
        sqlite_cur.execute("SELECT email, password_hash, created_at, last_login_at FROM users")
        rows = sqlite_cur.fetchall()
        if rows:
            if dry_run:
                logger.info(f"  users: [DRY-RUN] 将迁移 {len(rows)} 行")
                total += len(rows)
            else:
                for row in rows:
                    pg_cur.execute(
                        "INSERT INTO users (email, password_hash, created_at, last_login_at) "
                        "VALUES (%s, %s, %s, %s) ON CONFLICT (email) DO NOTHING",
                        (row["email"], row["password_hash"], row["created_at"], row["last_login_at"]),
                    )
                logger.info(f"  users: 已迁移 {len(rows)} 行")
                total += len(rows)
    except Exception as e:
        logger.error(f"  迁移 users 表失败: {e}")

    # 迁移 sessions 表
    try:
        sqlite_cur.execute("SELECT token, user_id, created_at, expires_at, revoked FROM sessions")
        rows = sqlite_cur.fetchall()
        if rows:
            if dry_run:
                logger.info(f"  sessions: [DRY-RUN] 将迁移 {len(rows)} 行")
                total += len(rows)
            else:
                for row in rows:
                    pg_cur.execute(
                        "INSERT INTO sessions (token, user_id, created_at, expires_at, revoked) "
                        "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (token) DO NOTHING",
                        (row["token"], row["user_id"], row["created_at"],
                         row["expires_at"], row["revoked"]),
                    )
                logger.info(f"  sessions: 已迁移 {len(rows)} 行")
                total += len(rows)
    except Exception as e:
        logger.error(f"  迁移 sessions 表失败: {e}")

    if not dry_run:
        pg_conn.commit()
    pg_cur.close()
    sqlite_conn.close()
    return total


def main():
    import argparse
    parser = argparse.ArgumentParser(description="SQLite → PostgreSQL 全量数据迁移")
    parser.add_argument("--sqlite", default=_get_sqlite_path(), help="业务 SQLite 数据库路径")
    parser.add_argument("--accounts-db", default=None, help="账号 SQLite 数据库路径（默认自动检测）")
    parser.add_argument("--dry-run", action="store_true", help="只打印不实际写入")
    parser.add_argument("--skip-accounts", action="store_true", help="跳过账号数据库迁移")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    # ===== 1. 迁移业务记录库 =====
    sqlite_path = args.sqlite
    if os.path.exists(sqlite_path):
        tables = list_sqlite_tables(sqlite_path)
        if tables:
            logger.info(f"[业务库] 发现 {len(tables)} 个表: {tables}")
            if args.dry_run:
                logger.info("** DRY-RUN 模式 **")

            try:
                pg_conn = _get_pg_conn()
                logger.info("[业务库] 已连接 PostgreSQL")
            except Exception as e:
                logger.error(f"[业务库] 连接 PostgreSQL 失败: {e}")
                logger.error("请确认: 1) docker-compose up -d 已启动  2) PG_* 环境变量已配置")
                sys.exit(1)

            total_rows = 0
            for tbl in tables:
                try:
                    total_rows += migrate_table(sqlite_path, tbl, pg_conn, dry_run=args.dry_run)
                except Exception as e:
                    logger.error(f"[业务库] 迁移表 {tbl} 失败: {e}")

            logger.info(f"[业务库] 迁移完成，共 {total_rows} 行")

            # ===== 2. 迁移账号库（复用同一连接） =====
            if not args.skip_accounts:
                logger.info("[账号库] 开始迁移 users + sessions...")
                try:
                    acct_total = migrate_accounts_db(pg_conn, dry_run=args.dry_run)
                    logger.info(f"[账号库] 迁移完成，共 {acct_total} 行")
                except Exception as e:
                    logger.error(f"[账号库] 迁移失败: {e}")

            pg_conn.close()
        else:
            logger.info("[业务库] 没有 records_ 开头的表，跳过")
    else:
        logger.info(f"[业务库] SQLite 不存在: {sqlite_path}")

    logger.info("全量迁移完成！")


if __name__ == "__main__":
    main()
