"""
PostgreSQL 数据库后端实现
========================
支持高并发写入（行级锁 + MVCC），通过连接池复用连接。
接口与 SQLiteDBManager 完全一致，可无缝切换。

切换方式：设置环境变量 DB_BACKEND=postgres
"""
import os
import json
import datetime
import logging
import threading
from contextlib import contextmanager

logger = logging.getLogger(__name__)

# 模块级连接池单例，所有 PostgresDBManager 实例共享
_pg_pool = None


def _get_pool():
    """获取或初始化 PostgreSQL 连接池（线程安全）"""
    global _pg_pool
    if _pg_pool is None:
        from psycopg2 import pool as pg_pool_mod
        _pg_pool = pg_pool_mod.ThreadedConnectionPool(
            minconn=2,
            maxconn=15,
            host=os.environ.get("PG_HOST", "127.0.0.1"),
            port=int(os.environ.get("PG_PORT", "5432")),
            dbname=os.environ.get("PG_DB", "scout"),
            user=os.environ.get("PG_USER", "scout"),
            password=os.environ.get("PG_PASSWORD", "scout123"),
        )
        logger.info(
            "PostgreSQL 连接池已初始化: %s:%s/%s",
            os.environ.get("PG_HOST", "127.0.0.1"),
            os.environ.get("PG_PORT", "5432"),
            os.environ.get("PG_DB", "scout"),
        )
    return _pg_pool


def close_pool():
    """关闭连接池（应用退出时调用）"""
    global _pg_pool
    if _pg_pool is not None:
        _pg_pool.closeall()
        _pg_pool = None
        logger.info("PostgreSQL 连接池已关闭")


class PostgresDBManager:
    """
    PostgreSQL 数据库管理器
    接口与 SQLiteDBManager 完全一致。
    利用 PostgreSQL 行级锁和 MVCC 支持多线程高并发写入。
    """

    # 类级锁和已初始化日期缓存，所有实例共享
    # 避免每次操作都执行 ALTER TABLE 导致死锁
    _table_init_lock = threading.Lock()
    _initialized_dates = set()

    def __init__(self):
        self._init_daily_table()

    @contextmanager
    def _get_cursor(self):
        """
        从连接池获取连接并创建游标。
        自动提交/回滚，用完归还连接。
        """
        pool = _get_pool()
        conn = pool.getconn()
        cur = None
        try:
            cur = conn.cursor()
            yield cur
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            if cur:
                cur.close()
            pool.putconn(conn)

    def _get_daily_table_name(self):
        """获取当天的表名，格式：records_YYYYMMDD"""
        today_str = datetime.datetime.now().strftime("%Y%m%d")
        return f"records_{today_str}"

    def _init_daily_table(self):
        """初始化当天的统计表"""
        table_name = self._get_daily_table_name()
        try:
            with self._get_cursor() as cur:
                cur.execute(f'''
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
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                cur.execute(f'''
                    CREATE INDEX IF NOT EXISTS idx_{table_name}_video_id
                    ON {table_name} (video_id)
                ''')
                self._ensure_record_columns(cur, table_name)
            logger.info(f"已连接 PostgreSQL 并校验当日数据表: {table_name}")
        except Exception as e:
            logger.error(f"初始化 PostgreSQL 表失败: {e}")

    def _ensure_record_columns(self, cur, table_name):
        """为历史表补齐新增字段（PostgreSQL 9.6+ 支持 ADD COLUMN IF NOT EXISTS）"""
        detail_columns = {
            "video_index": "INTEGER DEFAULT 0",
            "keyword_index": "INTEGER DEFAULT 0",
            "process_status": "TEXT DEFAULT ''",
            "skip_reason": "TEXT DEFAULT ''",
            "stay_duration": "REAL DEFAULT 0",
            "long_watch": "INTEGER DEFAULT 0",
            "recovery_attempts": "INTEGER DEFAULT 0",
            "intent_comment": "TEXT DEFAULT ''",
            "lead_reply": "TEXT DEFAULT ''",
            "lead_sent": "INTEGER DEFAULT 0",
            "lead_pm_sent": "INTEGER DEFAULT 0",
            "pm_sent": "INTEGER DEFAULT 0",
            "follower_count": "TEXT DEFAULT ''",
            "error_message": "TEXT DEFAULT ''",
            "action_log": "TEXT DEFAULT '[]'",
        }
        for col, col_type in detail_columns.items():
            try:
                cur.execute(
                    f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS {col} {col_type}"
                )
            except Exception as e:
                logger.debug(f"添加字段 {col} 失败（可能已存在）: {e}")

    def _ensure_table(self):
        """确保执行操作前当天的表存在（应对跨天运行的情况）"""
        table_name = self._get_daily_table_name()
        # 仅在当天首次调用时执行建表+ALTER，后续直接跳过（避免死锁）
        if table_name not in self._initialized_dates:
            with self._table_init_lock:
                if table_name not in self._initialized_dates:
                    self._init_daily_table()
                    self._initialized_dates.add(table_name)
        return table_name

    def record_video(self, video_id, keyword, url="", note_title=""):
        """
        记录一个新视频
        返回 True 表示是新视频并成功插入，返回 False 表示今天已经处理过该视频
        """
        table_name = self._ensure_table()
        try:
            with self._get_cursor() as cur:
                cur.execute(
                    f"SELECT id FROM {table_name} WHERE video_id = %s",
                    (video_id,),
                )
                if cur.fetchone():
                    return False

                cur.execute(f'''
                    INSERT INTO {table_name} (video_id, keyword, note_title, url)
                    VALUES (%s, %s, %s, %s)
                ''', (video_id, keyword, note_title, url))
                return True
        except Exception as e:
            logger.error(f"记录视频失败: {e}")
            return False

    def save_ai_reply(self, video_id, note_title="", ai_reply=""):
        """保存标题和 AI 回复，便于数据看板展示。"""
        table_name = self._ensure_table()
        try:
            with self._get_cursor() as cur:
                cur.execute(f'''
                    UPDATE {table_name}
                    SET note_title = COALESCE(NULLIF(%s, ''), note_title),
                        ai_reply = COALESCE(NULLIF(%s, ''), ai_reply)
                    WHERE video_id = %s
                ''', (note_title, ai_reply, video_id))
                return cur.rowcount > 0
        except Exception as e:
            logger.error(f"保存标题与 AI 回复失败: {e}")
            return False

    def update_interaction(self, video_id, action_type):
        """
        更新视频的互动状态
        :param action_type: 'like', 'comment', 'follow', 'private_message', 'lead_pm'
        """
        if action_type not in ('like', 'comment', 'follow', 'private_message', 'lead_pm'):
            logger.warning(f"未知的互动类型: {action_type}")
            return False

        table_name = self._ensure_table()
        field_map = {
            'like': 'liked',
            'comment': 'commented',
            'follow': 'followed',
            'private_message': 'private_messaged',
            'lead_pm': 'lead_pm_sent',
        }
        field_name = field_map[action_type]

        try:
            with self._get_cursor() as cur:
                cur.execute(f'''
                    UPDATE {table_name}
                    SET {field_name} = 1
                    WHERE video_id = %s
                ''', (video_id,))
                return cur.rowcount > 0
        except Exception as e:
            logger.error(f"更新视频互动状态 [{action_type}] 失败: {e}")
            return False

    def update_video_detail(self, video_id, **fields):
        """
        更新视频的执行过程详细字段。
        支持的字段：process_status/skip_reason/stay_duration/long_watch/
        recovery_attempts/intent_comment/lead_reply/lead_sent/lead_pm_sent/pm_sent/
        follower_count/error_message/video_index/keyword_index
        特殊字段 action_event：会作为一条事件追加到 action_log（JSON 数组）
        """
        allowed_fields = {
            "process_status", "skip_reason", "stay_duration", "long_watch",
            "recovery_attempts", "intent_comment", "lead_reply", "lead_sent",
            "lead_pm_sent", "pm_sent", "follower_count", "error_message",
            "video_index", "keyword_index",
        }
        table_name = self._ensure_table()
        action_event = fields.pop("action_event", None)

        try:
            with self._get_cursor() as cur:
                # 追加动作事件到 action_log（JSON 数组）
                if action_event:
                    cur.execute(
                        f"SELECT action_log FROM {table_name} WHERE video_id = %s",
                        (video_id,),
                    )
                    row = cur.fetchone()
                    try:
                        log_list = json.loads(row[0]) if row and row[0] else []
                    except Exception:
                        log_list = []
                    log_list.append(action_event)
                    # 限制最多 50 条事件，避免字段过长
                    if len(log_list) > 50:
                        log_list = log_list[-50:]
                    cur.execute(
                        f"UPDATE {table_name} SET action_log = %s WHERE video_id = %s",
                        (json.dumps(log_list, ensure_ascii=False), video_id),
                    )

                # 批量更新普通字段
                update_fields = {k: v for k, v in fields.items() if k in allowed_fields}
                if update_fields:
                    set_clause = ", ".join(f"{k} = %s" for k in update_fields.keys())
                    params = list(update_fields.values()) + [video_id]
                    cur.execute(
                        f"UPDATE {table_name} SET {set_clause} WHERE video_id = %s",
                        params,
                    )
                return True
        except Exception as e:
            logger.error(f"更新视频详细字段失败: {e}")
            return False

    def get_daily_stats(self):
        """获取当天的汇总统计数据"""
        table_name = self._ensure_table()
        try:
            with self._get_cursor() as cur:
                cur.execute(f'''
                    SELECT
                        COUNT(*) AS total_videos,
                        COALESCE(SUM(liked), 0) AS total_likes,
                        COALESCE(SUM(commented), 0) AS total_comments,
                        COALESCE(SUM(followed), 0) AS total_follows,
                        COALESCE(SUM(private_messaged), 0) AS total_private_messages,
                        COALESCE(SUM(lead_pm_sent), 0) AS total_lead_pms
                    FROM {table_name}
                ''')
                row = cur.fetchone()
                return {
                    "videos": row[0] or 0,
                    "likes": row[1] or 0,
                    "comments": row[2] or 0,
                    "follows": row[3] or 0,
                    "private_messages": row[4] or 0,
                    "lead_pms": row[5] or 0,
                }
        except Exception as e:
            logger.error(f"获取当天统计数据失败: {e}")
            return {"videos": 0, "likes": 0, "comments": 0, "follows": 0, "private_messages": 0, "lead_pms": 0}

    def get_daily_records(self, limit=100):
        """获取当天的详细操作记录，按时间倒序排列（含执行过程字段）"""
        table_name = self._ensure_table()
        try:
            with self._get_cursor() as cur:
                cur.execute(f'''
                    SELECT
                        video_id, keyword, note_title, ai_reply, url,
                        liked, commented, followed, private_messaged,
                        to_char(created_at, 'YYYY-MM-DD HH24:MI:SS'),
                        video_index, keyword_index, process_status, skip_reason,
                        stay_duration, long_watch, recovery_attempts,
                        intent_comment, lead_reply, lead_sent, lead_pm_sent, pm_sent,
                        follower_count, error_message, action_log
                    FROM {table_name}
                    ORDER BY created_at DESC
                    LIMIT %s
                ''', (limit,))
                rows = cur.fetchall()
                records = []
                for row in rows:
                    records.append({
                        "video_id": row[0],
                        "keyword": row[1],
                        "note_title": row[2] or "",
                        "ai_reply": row[3] or "",
                        "url": row[4],
                        "liked": bool(row[5]),
                        "commented": bool(row[6]),
                        "followed": bool(row[7]),
                        "private_messaged": bool(row[8]),
                        "created_at": row[9],
                        "video_index": row[10] or 0,
                        "keyword_index": row[11] or 0,
                        "process_status": row[12] or "",
                        "skip_reason": row[13] or "",
                        "stay_duration": row[14] or 0,
                        "long_watch": bool(row[15]),
                        "recovery_attempts": row[16] or 0,
                        "intent_comment": row[17] or "",
                        "lead_reply": row[18] or "",
                        "lead_sent": bool(row[19]),
                        "lead_pm_sent": bool(row[20]),
                        "pm_sent": bool(row[21]),
                        "follower_count": row[22] or "",
                        "error_message": row[23] or "",
                        "action_log": row[24] or "[]",
                    })
                return records
        except Exception as e:
            logger.error(f"获取当天详细记录失败: {e}")
            return []

    def reset_daily_progress(self):
        """重置当天的统计记录（清空当日表数据但保留表结构）"""
        table_name = self._ensure_table()
        try:
            with self._get_cursor() as cur:
                cur.execute(f"DELETE FROM {table_name}")
                return True
        except Exception as e:
            logger.error(f"重置当天进度失败: {e}")
            return False

    def cleanup_old_tables(self, keep_days=30):
        """删除超过指定天数的旧日期表，防止数据库无限膨胀"""
        try:
            with self._get_cursor() as cur:
                cur.execute("""
                    SELECT tablename FROM pg_tables
                    WHERE tablename LIKE 'records_%'
                """)
                tables = [row[0] for row in cur.fetchall()]
                cutoff = datetime.datetime.now() - datetime.timedelta(days=keep_days)
                cutoff_str = cutoff.strftime("%Y%m%d")
                dropped = 0
                for tbl in tables:
                    date_part = tbl.replace("records_", "")
                    if len(date_part) == 8 and date_part.isdigit() and date_part < cutoff_str:
                        cur.execute(f"DROP TABLE IF EXISTS {tbl}")
                        dropped += 1
                if dropped:
                    logger.info(f"已清理 {dropped} 个过期数据表（>{keep_days}天）")
                return dropped
        except Exception as e:
            logger.error(f"清理旧表失败: {e}")
            return 0
