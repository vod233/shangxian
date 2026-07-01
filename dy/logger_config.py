import logging
import logging.handlers
import os
import re
import datetime
import collections

# 全局内存日志缓存（保留最近 100 条）
MEMORY_LOGS = collections.deque(maxlen=100)

# ======================== 日志脱敏（防止密钥/Token 落盘）========================
# 命中即替换为 [REDACTED]，避免 DeepSeek Key / saa_* 授权码 / Bearer token / 密码
# 等敏感信息写入日志文件或前端展示。
_REDACT_PATTERNS = [
    # DeepSeek API Key: sk-xxxx... (至少 32 位)
    (re.compile(r"sk-[A-Za-z0-9]{16,}"), "sk-[REDACTED]"),
    # 授权码：saa_xxxx...
    (re.compile(r"saa_[A-Za-z0-9]{16,}"), "saa_[REDACTED]"),
    # 管理员 token：adm_xxxx...
    (re.compile(r"adm_[A-Za-z0-9]{16,}"), "adm_[REDACTED]"),
    # Authorization: Bearer xxxx...
    (re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]{16,}", re.IGNORECASE), r"\1[REDACTED]"),
    # password=xxx / passwd=xxx / pwd=xxx（覆盖 URL 参数与赋值场景）
    (re.compile(r"(password|passwd|pwd)(\s*[=:]\s*)([^\s,;'\"]+)", re.IGNORECASE), r"\1\2[REDACTED]"),
    # PG_PASSWORD=xxx
    (re.compile(r"(PG_PASSWORD)(\s*[=:]\s*)([^\s,;'\"]+)", re.IGNORECASE), r"\1\2[REDACTED]"),
    # 邮箱（脱敏本地部分，保留域名，便于排查）：abc@example.com -> a***@example.com
    (re.compile(r"\b([A-Za-z0-9._%+\-])([A-Za-z0-9._%+\-]{1,})@([A-Za-z0-9.\-]+\.[A-Za-z]{2,})\b"),
     r"\1***@\3"),
]


def _redact(text: str) -> str:
    """对日志文本做敏感信息脱敏。"""
    if not text:
        return text
    for pattern, repl in _REDACT_PATTERNS:
        try:
            text = pattern.sub(repl, text)
        except Exception:
            # 脱敏失败不应中断日志记录
            continue
    return text


class _RedactingFilter(logging.Filter):
    """日志过滤器：在格式化后对 message 做敏感信息脱敏。"""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            # 同时脱敏原始 msg 与已格式化后的内容
            if isinstance(record.msg, str):
                record.msg = _redact(record.msg)
            if record.args:
                # 参数化日志（logger.info("key=%s", val)）的参数也脱敏
                if isinstance(record.args, dict):
                    record.args = {k: _redact(str(v)) if isinstance(v, str) else v for k, v in record.args.items()}
                elif isinstance(record.args, tuple):
                    record.args = tuple(_redact(str(a)) if isinstance(a, str) else a for a in record.args)
        except Exception:
            pass
        return True


class MemoryHandler(logging.Handler):
    """自定义 Handler，将日志内容写入到内存队列中，供前端 API 读取"""
    def emit(self, record):
        try:
            msg = self.format(record)
            MEMORY_LOGS.append(msg)
        except Exception:
            self.handleError(record)


def setup_logger():
    """
    配置全局日志记录器
    将日志同时输出到控制台、轮转文件（10MB x 5 份）以及内存队列中。
    所有日志在落盘/展示前经过脱敏过滤（_RedactingFilter）。
    """
    # 1. 创建 logs 文件夹
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    logs_dir = os.path.join(project_root, "logs")
    os.makedirs(logs_dir, exist_ok=True)

    # 2. 单一滚动日志文件（避免每次启动产生新文件导致磁盘膨胀）
    log_filepath = os.path.join(logs_dir, "app.log")

    # 3. 配置全局 logging
    # 清理已有的 handlers，防止重复记录
    root_logger = logging.getLogger()
    if root_logger.hasHandlers():
        root_logger.handlers.clear()

    root_logger.setLevel(logging.INFO)

    # 日志格式
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    # 脱敏过滤器（所有 handler 共享同一实例）
    redact_filter = _RedactingFilter()

    # 文件 Handler：10MB 轮转，最多保留 5 份历史（UTF-8 防止中文乱码）
    file_handler = logging.handlers.RotatingFileHandler(
        log_filepath,
        maxBytes=10 * 1024 * 1024,   # 10 MB
        backupCount=5,
        encoding='utf-8',
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    file_handler.addFilter(redact_filter)

    # 控制台 Handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    console_handler.addFilter(redact_filter)

    # 内存 Handler (供前端展示)
    memory_handler = MemoryHandler()
    memory_handler.setLevel(logging.INFO)
    memory_handler.setFormatter(formatter)
    memory_handler.addFilter(redact_filter)

    # 添加到全局 logger
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    root_logger.addHandler(memory_handler)

    # 打印一条启动日志，告知文件位置
    logging.info(f"已初始化日志系统（含脱敏与轮转），当前日志文件: {log_filepath}")

    return log_filepath
