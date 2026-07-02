class DBManager:
    """
    数据库管理器工厂类
    统一使用 PostgreSQL 后端（不再支持 SQLite）。
    需安装 psycopg2-binary 并配置 PG_* 环境变量。

    用法不变：db = DBManager()，所有方法签名一致。
    """

    def __new__(cls):
        try:
            from dy.db_postgres import PostgresDBManager
            return PostgresDBManager()
        except ImportError:
            raise RuntimeError(
                "psycopg2 未安装，PostgreSQL 是唯一支持的后端。请执行: pip install psycopg2-binary"
            )
        except Exception as exc:
            raise RuntimeError(f"连接 PostgreSQL 失败: {exc}")
