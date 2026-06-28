import sqlite3
import os
import datetime
import logging

logger = logging.getLogger(__name__)

class DBManager:
    """
    SQLite 数据库管理器
    负责管理按天建表，并记录每天处理的视频数量、点赞、评论和关注等数据。
    支持多线程并发写入（WAL 模式）。
    """
    def __init__(self):
        # 确定数据库存储路径
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.db_dir = os.path.join(project_root, "data")
        os.makedirs(self.db_dir, exist_ok=True)
        
        self.db_path = os.path.join(self.db_dir, "scout_records.db")
        self._init_daily_table()

    def _get_connection(self):
        """
        获取配置了 WAL 模式和超时设置的数据库连接。
        每次调用创建新连接，确保线程安全。
        """
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL")      # 开启 WAL 模式，支持读写并发
        conn.execute("PRAGMA busy_timeout=5000")      # 写锁等待 5 秒
        conn.execute("PRAGMA synchronous=NORMAL")      # 平衡安全与性能
        return conn

    def _get_daily_table_name(self):
        """获取当天的表名，格式：records_YYYYMMDD"""
        today_str = datetime.datetime.now().strftime("%Y%m%d")
        return f"records_{today_str}"

    def _init_daily_table(self):
        """初始化当天的统计表"""
        table_name = self._get_daily_table_name()
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                # 创建每天的记录表
                cursor.execute(f'''
                    CREATE TABLE IF NOT EXISTS {table_name} (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
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
                # 为 video_id 创建索引，加速查询
                cursor.execute(f'''
                    CREATE INDEX IF NOT EXISTS idx_{table_name}_video_id 
                    ON {table_name} (video_id)
                ''')
                self._ensure_record_columns(cursor, table_name)
                conn.commit()
            logger.info(f"已连接数据库并校验当日数据表: {table_name}")
        except Exception as e:
            logger.error(f"初始化数据库表失败: {e}")

    def _ensure_record_columns(self, cursor, table_name):
        """为历史表补齐新增字段，避免旧库升级后读写失败。"""
        cursor.execute(f"PRAGMA table_info({table_name})")
        existing_columns = {row[1] for row in cursor.fetchall()}

        if "note_title" not in existing_columns:
            cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN note_title TEXT DEFAULT ''")
        if "ai_reply" not in existing_columns:
            cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN ai_reply TEXT DEFAULT ''")
        if "private_messaged" not in existing_columns:
            cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN private_messaged INTEGER DEFAULT 0")
        # 执行过程详细字段（v2 扩展，便于前端透明展示每条视频的处理过程）
        detail_columns = {
            "video_index": "INTEGER DEFAULT 0",           # 本关键词内第几个视频
            "keyword_index": "INTEGER DEFAULT 0",          # 第几个关键词
            "process_status": "TEXT DEFAULT ''",           # 处理结果：completed/skipped/error
            "skip_reason": "TEXT DEFAULT ''",              # 跳过原因：duplicate/限额/概率/功能关闭
            "stay_duration": "REAL DEFAULT 0",             # 实际停留时长(秒)
            "long_watch": "INTEGER DEFAULT 0",             # 是否触发长停留
            "recovery_attempts": "INTEGER DEFAULT 0",      # 状态恢复尝试次数
            "intent_comment": "TEXT DEFAULT ''",           # AI识别到的意向评论文本
            "lead_reply": "TEXT DEFAULT ''",               # 楼中楼回复内容
            "lead_sent": "INTEGER DEFAULT 0",              # 楼中楼是否发送成功
            "lead_pm_sent": "INTEGER DEFAULT 0",           # 楼中楼回复后私信评论者是否成功
            "pm_sent": "INTEGER DEFAULT 0",                # 私信是否发送（兼容旧 private_messaged）
            "follower_count": "TEXT DEFAULT ''",           # 作者粉丝数（原始文本）
            "error_message": "TEXT DEFAULT ''",            # 执行异常信息
            "action_log": "TEXT DEFAULT ''",               # 执行动作流水（JSON 数组字符串）
        }
        for col, col_type in detail_columns.items():
            if col not in existing_columns:
                try:
                    cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {col} {col_type}")
                except Exception as e:
                    logger.debug(f"添加字段 {col} 失败（可能已存在）: {e}")

    def _ensure_table(self):
        """确保执行操作前当天的表存在（应对跨天运行的情况）"""
        self._init_daily_table()
        return self._get_daily_table_name()

    def record_video(self, video_id, keyword, url="", note_title=""):
        """
        记录一个新视频
        返回 True 表示是新视频并成功插入，返回 False 表示今天已经处理过该视频
        """
        table_name = self._ensure_table()
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                # 检查是否已存在
                cursor.execute(f"SELECT id FROM {table_name} WHERE video_id = ?", (video_id,))
                if cursor.fetchone():
                    return False
                
                # 插入新记录
                cursor.execute(f'''
                    INSERT INTO {table_name} (video_id, keyword, note_title, url)
                    VALUES (?, ?, ?, ?)
                ''', (video_id, keyword, note_title, url))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"记录视频失败: {e}")
            return False

    def save_ai_reply(self, video_id, note_title="", ai_reply=""):
        """保存标题和 AI 回复，便于数据看板展示。"""
        table_name = self._ensure_table()
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(f'''
                    UPDATE {table_name}
                    SET note_title = COALESCE(NULLIF(?, ''), note_title),
                        ai_reply = COALESCE(NULLIF(?, ''), ai_reply)
                    WHERE video_id = ?
                ''', (note_title, ai_reply, video_id))
                conn.commit()
                return cursor.rowcount > 0
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
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(f'''
                    UPDATE {table_name} 
                    SET {field_name} = 1 
                    WHERE video_id = ?
                ''', (video_id,))
                conn.commit()
                return cursor.rowcount > 0
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
            with self._get_connection() as conn:
                cursor = conn.cursor()

                # 追加动作事件到 action_log（JSON 数组）
                if action_event:
                    import json
                    cursor.execute(
                        f"SELECT action_log FROM {table_name} WHERE video_id = ?",
                        (video_id,)
                    )
                    row = cursor.fetchone()
                    try:
                        log_list = json.loads(row[0]) if row and row[0] else []
                    except Exception:
                        log_list = []
                    log_list.append(action_event)
                    # 限制最多 50 条事件，避免字段过长
                    if len(log_list) > 50:
                        log_list = log_list[-50:]
                    cursor.execute(
                        f"UPDATE {table_name} SET action_log = ? WHERE video_id = ?",
                        (json.dumps(log_list, ensure_ascii=False), video_id)
                    )

                # 批量更新普通字段
                update_fields = {k: v for k, v in fields.items() if k in allowed_fields}
                if update_fields:
                    set_clause = ", ".join(f"{k} = ?" for k in update_fields.keys())
                    params = list(update_fields.values()) + [video_id]
                    cursor.execute(
                        f"UPDATE {table_name} SET {set_clause} WHERE video_id = ?",
                        params
                    )
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"更新视频详细字段失败: {e}")
            return False

    def get_daily_stats(self):
        """获取当天的汇总统计数据"""
        table_name = self._ensure_table()
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                # 兼容旧表：lead_pm_sent 字段可能不存在，使用 try/except 兜底
                try:
                    cursor.execute(f'''
                        SELECT
                            COUNT(*) as total_videos,
                            SUM(liked) as total_likes,
                            SUM(commented) as total_comments,
                            SUM(followed) as total_follows,
                            SUM(private_messaged) as total_private_messages,
                            SUM(lead_pm_sent) as total_lead_pms
                        FROM {table_name}
                    ''')
                    row = cursor.fetchone()
                    lead_pms = row[5] or 0
                except Exception:
                    cursor.execute(f'''
                        SELECT
                            COUNT(*) as total_videos,
                            SUM(liked) as total_likes,
                            SUM(commented) as total_comments,
                            SUM(followed) as total_follows,
                            SUM(private_messaged) as total_private_messages
                        FROM {table_name}
                    ''')
                    row = cursor.fetchone()
                    lead_pms = 0
                return {
                    "videos": row[0] or 0,
                    "likes": row[1] or 0,
                    "comments": row[2] or 0,
                    "follows": row[3] or 0,
                    "private_messages": row[4] or 0,
                    "lead_pms": lead_pms
                }
        except Exception as e:
            logger.error(f"获取当天统计数据失败: {e}")
            return {"videos": 0, "likes": 0, "comments": 0, "follows": 0, "private_messages": 0, "lead_pms": 0}

    def get_daily_records(self, limit=100):
        """获取当天的详细操作记录，按时间倒序排列（含执行过程字段）"""
        table_name = self._ensure_table()
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(f'''
                    SELECT
                        video_id, keyword, note_title, ai_reply, url,
                        liked, commented, followed, private_messaged, created_at,
                        video_index, keyword_index, process_status, skip_reason,
                        stay_duration, long_watch, recovery_attempts,
                        intent_comment, lead_reply, lead_sent, lead_pm_sent, pm_sent,
                        follower_count, error_message, action_log
                    FROM {table_name}
                    ORDER BY created_at DESC
                    LIMIT ?
                ''', (limit,))
                rows = cursor.fetchall()
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
