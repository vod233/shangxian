import os
import datetime
import logging

from dy.db_postgres import PostgresDBManager

logger = logging.getLogger(__name__)


class DBManager:
    """数据库管理器（PostgreSQL 后端，通过连接池复用连接）。"""

    def __new__(cls):
        return PostgresDBManager()
