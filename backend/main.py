import sys
import os
import json
import yaml
import logging
import concurrent.futures
import threading
import time
from functools import partial

import requests

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"), override=True)
from contextlib import asynccontextmanager
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

# 确保能找到项目根目录下的模块
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

from dy.multi_device import get_connected_devices
from dy.task_runner import TikTokTaskFlow
from dy.db_manager import DBManager
from dy.logger_config import setup_logger, MEMORY_LOGS
from wireless_connect import run_cmd, ADB_BIN
from usb_connect import detect_usb_devices

from backend.schemas import AppConfig, TaskStartRequest, TaskResponse, DeviceConnectRequest, DevicePairRequest, LicenseVerifyRequest, AuthRegisterRequest, AuthLoginRequest
from social_license import DEFAULT_LICENSE_SERVER_URL, LicenseError, mask_license_key, verify_license

# 初始化全局日志
setup_logger()

# ======================== 全局并发控制 ========================
# 任务状态字典与运行任务字典的线程锁
_task_status_lock = threading.Lock()
_task_status = {}
# 保存正在运行的任务实例引用，以便可以调用 stop()
_running_tasks = {}
_stop_requested = set()
# 全局线程池，限制最大并发设备数
MAX_CONCURRENT_DEVICES = 50
_task_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=MAX_CONCURRENT_DEVICES,
    thread_name_prefix="device_task"
)

# 为了兼容旧代码，创建 task_status 和 running_tasks 的代理属性
class _LockedDict:
    """线程安全的字典代理"""
    def __init__(self, lock, data):
        self._lock = lock
        self._data = data

    def get(self, key, default=None):
        with self._lock:
            return self._data.get(key, default)

    def __getitem__(self, key):
        with self._lock:
            return self._data[key]

    def __setitem__(self, key, value):
        with self._lock:
            self._data[key] = value

    def __delitem__(self, key):
        with self._lock:
            del self._data[key]

    def __contains__(self, key):
        with self._lock:
            return key in self._data

    def items(self):
        with self._lock:
            return list(self._data.items())

    def values(self):
        with self._lock:
            return list(self._data.values())

    def keys(self):
        with self._lock:
            return list(self._data.keys())

    def pop(self, key, *args):
        with self._lock:
            return self._data.pop(key, *args)

# 为了向后兼容，我们保留原始字典但用函数封装操作
# 实际使用时通过 get_task_status / set_task_status / del_task_status 函数访问
def get_task_status(serial, default=None):
    with _task_status_lock:
        return _task_status.get(serial, default)

def set_task_status(serial, status, current_action=None, executed_action=None):
    """
    更新设备任务状态。status 字段会与既有状态合并（保留 current_action/executed_actions）。
    - current_action: 不为 None 时覆盖"当前正在执行"的描述。
    - executed_action: 不为 None 时追加到"已执行"列表（最多保留 30 条）。
    """
    with _task_status_lock:
        existing = _task_status.get(serial, {})
        if not isinstance(existing, dict):
            existing = {}
        merged = dict(existing)
        merged.update(status)
        if current_action is not None:
            merged["current_action"] = current_action
        if executed_action is not None:
            executed_list = list(merged.get("executed_actions") or [])
            executed_list.append(executed_action)
            if len(executed_list) > 30:
                executed_list = executed_list[-30:]
            merged["executed_actions"] = executed_list
        _task_status[serial] = merged

def del_task_status(serial):
    with _task_status_lock:
        if serial in _task_status:
            del _task_status[serial]

def get_running_task(serial):
    with _task_status_lock:
        return _running_tasks.get(serial)

def set_running_task(serial, task):
    with _task_status_lock:
        _running_tasks[serial] = task

def del_running_task(serial):
    with _task_status_lock:
        if serial in _running_tasks:
            del _running_tasks[serial]

def get_all_running_tasks():
    with _task_status_lock:
        return list(_running_tasks.items())

def is_task_running(serial):
    with _task_status_lock:
        status = _task_status.get(serial, {}).get("status")
        return status in {"queued", "starting", "running", "paused"}

def set_task_queued(serial, platform):
    """入队时重置动作进度，避免残留上一轮任务的记录。"""
    with _task_status_lock:
        _task_status[serial] = {
            "status": "queued",
            "error": None,
            "platform": platform,
            "current_action": "数字化员工已就绪，等待下达任务指令...",
            "executed_actions": [],
        }

def report_device_action(serial, current_action=None, executed_action=None):
    """供任务流上报"当前动作"与"已执行动作"，不影响 status 枚举。"""
    with _task_status_lock:
        existing = _task_status.get(serial)
        if not isinstance(existing, dict):
            return
        if current_action is not None:
            existing["current_action"] = current_action
        if executed_action is not None:
            executed_list = list(existing.get("executed_actions") or [])
            executed_list.append(executed_action)
            if len(executed_list) > 30:
                executed_list = executed_list[-30:]
            existing["executed_actions"] = executed_list

def request_task_stop(serial):
    with _task_status_lock:
        _stop_requested.add(serial)

def clear_task_stop_request(serial):
    with _task_status_lock:
        _stop_requested.discard(serial)

def is_task_stop_requested(serial):
    with _task_status_lock:
        return serial in _stop_requested

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时执行：清理过期历史表，防止数据库膨胀
    try:
        keep_days = int(os.environ.get("DB_CLEANUP_KEEP_DAYS", "30"))
        db_manager.cleanup_old_tables(keep_days=keep_days)
    except Exception as e:
        logging.warning(f"启动清理旧表失败（不影响运行）: {e}")
    yield
    # 关闭时执行：优雅地清理所有后台正在运行的设备任务
    logging.info("接收到关闭信号，正在停止所有后台设备任务...")
    for serial, task in get_all_running_tasks():
        try:
            task.stop()
            logging.info(f"已发送停止信号给设备: {serial}")
        except Exception as e:
            logging.error(f"停止设备 {serial} 时出错: {e}")
    # 关闭线程池
    _task_executor.shutdown(wait=True)
    logging.info("线程池已关闭。")
    # 关闭 PostgreSQL 连接池（如果使用 PostgreSQL 后端）
    if os.environ.get("DB_BACKEND", "").lower() == "postgres":
        try:
            from dy.db_postgres import close_pool
            close_pool()
            logging.info("PostgreSQL 连接池已关闭。")
        except Exception:
            pass

app = FastAPI(title="抖音自动化后端 API", version="1.0.0", lifespan=lifespan)

# 允许跨域请求，方便未来 Streamlit 前端调用
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 抖音配置路径
DY_USER_CONFIG_PATH = os.path.join(PROJECT_ROOT, "dy", "config", "user_settings.yaml")
DY_API_CONFIG_PATH = os.path.join(PROJECT_ROOT, "dy", "config", "api_settings.yaml")

db_manager = DBManager()


# ======================== 账号登录（透传云端 social-account-api）========================
# 云端账号微服务地址（Nginx 反代到 127.0.0.1:8200）
ACCOUNT_API_BASE = os.environ.get("APP_ACCOUNT_API_BASE", "https://lcjx.yun/social-account-api")
# 本地 token 持久化文件：config/auth.json（launcher 设置 APP_CONFIG_DIR）
_AUTH_CONFIG_DIR = os.environ.get("APP_CONFIG_DIR") or os.path.join(PROJECT_ROOT, "config")
AUTH_FILE_PATH = os.path.join(_AUTH_CONFIG_DIR, "auth.json")


def _read_auth_file() -> dict:
    """读取本地持久化的账号 token，返回 {} 表示未登录。"""
    if not os.path.exists(AUTH_FILE_PATH):
        return {}
    try:
        with open(AUTH_FILE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        logging.warning(f"读取 auth.json 失败: {exc}")
        return {}


def _write_auth_file(token: str, email: str) -> None:
    """登录/注册成功后写入 token（永久记住）。"""
    try:
        os.makedirs(os.path.dirname(AUTH_FILE_PATH), exist_ok=True)
        payload = {
            "token": token,
            "email": email,
            "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        with open(AUTH_FILE_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        logging.error(f"写入 auth.json 失败: {exc}")


def _clear_auth_file() -> None:
    """退出登录时删除本地 token。"""
    try:
        if os.path.exists(AUTH_FILE_PATH):
            os.remove(AUTH_FILE_PATH)
    except Exception as exc:
        logging.warning(f"删除 auth.json 失败: {exc}")


def _account_request(path: str, method: str = "GET", json_body: dict = None, token: str = "", timeout: int = 20):
    """统一调用云端账号微服务，返回 (resp_data_dict, error_message)。
    成功时 error_message 为 None；失败时 resp_data 为 None。
    """
    url = f"{ACCOUNT_API_BASE.rstrip('/')}{path}"
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        if method == "GET":
            resp = requests.get(url, headers=headers, timeout=timeout)
        else:
            resp = requests.post(url, json=json_body or {}, headers=headers, timeout=timeout)
    except requests.RequestException as exc:
        return None, f"账号服务连接失败: {exc}"
    try:
        data = resp.json()
    except Exception:
        return None, f"账号服务响应异常: HTTP {resp.status_code}"
    if not resp.ok:
        # 透传云端返回的 detail 字段
        detail = data.get("detail") or data.get("message") or f"HTTP {resp.status_code}"
        return None, str(detail)
    return data, None


def _load_yaml_file(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as exc:
        logging.warning(f"读取配置文件失败 {path}: {exc}")
        return {}


def _save_yaml_file(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)


# ======================== 抖音配置逻辑 ========================

def _load_douyin_runtime_config():
    user_data = _load_yaml_file(DY_USER_CONFIG_PATH)
    api_data = _load_yaml_file(DY_API_CONFIG_PATH)

    normalized_user_data = {
        key: value for key, value in user_data.items()
        if key != "ai_reply"
    }
    normalized_api_data = {
        key: value for key, value in api_data.items()
        if key not in ("search", "crawler")
    }

    search_data = user_data.get("search") if isinstance(user_data.get("search"), dict) else {}
    crawler_data = user_data.get("crawler") if isinstance(user_data.get("crawler"), dict) else {}
    ai_reply_data = api_data.get("ai_reply") if isinstance(api_data.get("ai_reply"), dict) else {}

    if not search_data and isinstance(api_data.get("search"), dict):
        search_data = api_data["search"]
    if not crawler_data and isinstance(api_data.get("crawler"), dict):
        crawler_data = api_data["crawler"]
    if not ai_reply_data and isinstance(user_data.get("ai_reply"), dict):
        ai_reply_data = user_data["ai_reply"]

    if search_data:
        normalized_user_data["search"] = search_data
    if crawler_data:
        normalized_user_data["crawler"] = crawler_data
    if ai_reply_data:
        normalized_api_data["ai_reply"] = ai_reply_data

    return {
        "search": normalized_user_data.get("search", {}),
        "crawler": normalized_user_data.get("crawler", {}),
        "comments": normalized_user_data.get("comments", []),
        "target": normalized_user_data.get("target", {}),
        "interaction": normalized_user_data.get("interaction", {}),
        "ai_reply": normalized_api_data.get("ai_reply", {}),
        "anti_detection": normalized_user_data.get("anti_detection", {}),
    }


def _load_douyin_config_for_frontend():
    data = _load_douyin_runtime_config()
    license_data = data.get("ai_reply", {}).get("license", {}) if isinstance(data.get("ai_reply", {}).get("license"), dict) else {}
    license_key = license_data.get("key") or data.get("ai_reply", {}).get("license_key", "")
    return {
        "search_keywords": data.get("search", {}).get("keywords", []),
        "sort_by": data.get("search", {}).get("sort_by", "latest"),
        "max_daily_videos": data.get("crawler", {}).get("max_daily_videos", 100),
        "max_videos_per_keyword": data.get("crawler", {}).get("max_videos_per_keyword", 5),
        "comments": data.get("comments", []),
        "target_keywords": data.get("target", {}).get("keywords", []),
        "reply_texts": data.get("target", {}).get("reply_texts", []),
        "min_video_stay": data.get("crawler", {}).get("min_video_stay", 3),
        "max_video_stay": data.get("crawler", {}).get("max_video_stay", 6),
        "max_comment_swipes": data.get("interaction", {}).get("max_comment_swipes", 2),
        "max_ai_comment_reviews": data.get("interaction", {}).get("max_ai_comment_reviews", 20),
        "intent_keywords": ",".join(data.get("interaction", {}).get("intent_keywords", [])),
        "keyword_override_ai": data.get("interaction", {}).get("keyword_override_ai", True),
        "enable_like": data.get("interaction", {}).get("enable_like", True),
        "enable_author_follow": data.get("interaction", {}).get("enable_author_follow", True),
        "enable_video_comment": data.get("interaction", {}).get("enable_video_comment", True),
        "enable_comment_lead": data.get("interaction", {}).get("enable_comment_lead", True),
        "enable_comment_lead_pm": data.get("interaction", {}).get("enable_comment_lead_pm", True),
        "min_followers_threshold": data.get("interaction", {}).get("min_followers_threshold", 0),
        "enable_private_message": data.get("interaction", {}).get("enable_private_message", True),
        "pm_followers_threshold": data.get("interaction", {}).get("pm_followers_threshold", 1),
        "pm_message_list": data.get("interaction", {}).get("pm_message_list", []),
        "lead_pm_message_list": data.get("interaction", {}).get("lead_pm_message_list", []),
        "ai_enabled": data.get("ai_reply", {}).get("enabled", True),
        "ai_base_url": data.get("ai_reply", {}).get("cloud_base_url", DEFAULT_LICENSE_SERVER_URL),
        "ai_api_key": "",
        "ai_model": data.get("ai_reply", {}).get("model", "deepseek-v4-flash"),
        "ai_temperature": data.get("ai_reply", {}).get("temperature", 0.7),
        "ai_max_tokens": data.get("ai_reply", {}).get("max_tokens", 120),
        "ai_persona": data.get("ai_reply", {}).get("persona", "a_zhen"),
        "license_key": "",
        "license_key_masked": mask_license_key(license_key),
        "has_license_key": bool(license_key),
        "license_server_url": license_data.get("server_url", DEFAULT_LICENSE_SERVER_URL),
        "night_mode_enabled": data.get("anti_detection", {}).get("night_mode", {}).get("enabled", True),
        "enable_anti_detection_probability": data.get("anti_detection", {}).get("interaction_probability", {}).get("enabled", False),
        "turbo_test_mode": data.get("anti_detection", {}).get("turbo_test_mode", {}).get("enabled", False),
    }


def _save_douyin_config(config: AppConfig):
    previous_api_data = _load_yaml_file(DY_API_CONFIG_PATH)
    previous_ai = previous_api_data.get("ai_reply", {}) if isinstance(previous_api_data.get("ai_reply"), dict) else {}
    previous_license = previous_ai.get("license", {}) if isinstance(previous_ai.get("license"), dict) else {}
    license_key = (config.license_key or "").strip() or previous_license.get("key", "") or previous_ai.get("license_key", "")
    license_server_url = (config.license_server_url or "").strip() or previous_license.get("server_url", DEFAULT_LICENSE_SERVER_URL)
    # 读取已有用户配置，保留前端未覆盖的段落（如 anti_detection 防风控配置）
    previous_user_data = _load_yaml_file(DY_USER_CONFIG_PATH)
    user_yaml_data = {
        "search": {
            "keywords": config.search_keywords,
            "sort_by": "latest",
        },
        "crawler": {
            "max_daily_videos": config.max_daily_videos,
            "max_videos_per_keyword": config.max_videos_per_keyword,
            "min_video_stay": config.min_video_stay,
            "max_video_stay": config.max_video_stay,
        },
        "comments": config.comments,
        "target": {
            "keywords": config.target_keywords,
            "reply_texts": config.reply_texts,
        },
        "interaction": {
            "max_comment_swipes": config.max_comment_swipes,
            "max_ai_comment_reviews": config.max_ai_comment_reviews,
            "intent_keywords": config.intent_keywords,
            "keyword_override_ai": config.keyword_override_ai,
            "enable_like": config.enable_like,
            "enable_author_follow": config.enable_author_follow,
            "enable_video_comment": config.enable_video_comment,
            "enable_comment_lead": config.enable_comment_lead,
            "enable_comment_lead_pm": config.enable_comment_lead_pm,
            "min_followers_threshold": config.min_followers_threshold,
            "enable_private_message": config.enable_private_message,
            "pm_followers_threshold": config.pm_followers_threshold,
            "pm_message_list": config.pm_message_list,
            "lead_pm_message_list": config.lead_pm_message_list,
        }
    }
    # 夜间静默时段：前端只控总开关，start_hour/end_hour 从旧配置保留，避免被重置
    # anti_detection 下其它子项（interaction_probability、daily_limits 等）也一并从旧配置继承，避免被覆盖丢失
    prev_anti = previous_user_data.get("anti_detection", {}) if isinstance(previous_user_data, dict) and isinstance(previous_user_data.get("anti_detection"), dict) else {}
    existing_anti = dict(prev_anti)  # 先继承旧 anti_detection 全部子项
    prev_night = prev_anti.get("night_mode", {}) if isinstance(prev_anti.get("night_mode"), dict) else {}
    existing_anti["night_mode"] = {
        "enabled": config.night_mode_enabled,
        "start_hour": prev_night.get("start_hour", 23),
        "end_hour": prev_night.get("end_hour", 7),
    }
    # 概率决策开关：保留旧 interaction_probability 下的概率值，仅更新 enabled 总开关
    prev_prob = prev_anti.get("interaction_probability", {}) if isinstance(prev_anti.get("interaction_probability"), dict) else {}
    existing_anti["interaction_probability"] = {
        **prev_prob,
        "enabled": config.enable_anti_detection_probability,
    }
    # 极速测试模式：单总开关，控制 HumanSleep/BehaviorRandomizer/InteractionProbability
    existing_anti["turbo_test_mode"] = {
        "enabled": config.turbo_test_mode,
    }
    user_yaml_data["anti_detection"] = existing_anti
    # mode 与本地 LLM 凭据从旧配置继承，避免前端保存其他配置时把 mode 重置为 cloud 或清空凭据
    prev_ai_mode = previous_ai.get("mode", "cloud")
    prev_base_url = previous_ai.get("base_url", "")
    prev_api_key = previous_ai.get("api_key", "")
    api_yaml_data = {
        "ai_reply": {
            "enabled": config.ai_enabled,
            "mode": prev_ai_mode,
            "cloud_base_url": license_server_url,
            "base_url": prev_base_url,
            "api_key": prev_api_key,
            "model": config.ai_model,
            "temperature": config.ai_temperature,
            "max_tokens": config.ai_max_tokens,
            "persona": config.ai_persona,
            "license": {
                "server_url": license_server_url,
                "key": license_key,
            },
        },
    }
    _save_yaml_file(DY_USER_CONFIG_PATH, user_yaml_data)
    _save_yaml_file(DY_API_CONFIG_PATH, api_yaml_data)


def _get_license_config_for_platform(platform: str) -> dict:
    api_path = DY_API_CONFIG_PATH
    api_data = _load_yaml_file(api_path)
    ai_reply = api_data.get("ai_reply", {}) if isinstance(api_data.get("ai_reply"), dict) else {}
    license_data = ai_reply.get("license", {}) if isinstance(ai_reply.get("license"), dict) else {}
    return {
        "key": (license_data.get("key") or ai_reply.get("license_key") or "").strip(),
        "server_url": (license_data.get("server_url") or ai_reply.get("cloud_base_url") or DEFAULT_LICENSE_SERVER_URL).strip(),
    }


def _verify_platform_license(platform: str, device_id: str = "") -> dict:
    license_config = _get_license_config_for_platform(platform)
    try:
        return verify_license(
            license_config.get("key", ""),
            license_config.get("server_url", DEFAULT_LICENSE_SERVER_URL),
            device_id=device_id,
        )
    except LicenseError as exc:
        raise HTTPException(status_code=403, detail=str(exc))


def _save_platform_license(platform: str, license_key: str, server_url: str) -> None:
    api_path = DY_API_CONFIG_PATH
    api_data = _load_yaml_file(api_path)
    ai_reply = api_data.get("ai_reply", {}) if isinstance(api_data.get("ai_reply"), dict) else {}
    license_server_url = (server_url or "").strip() or DEFAULT_LICENSE_SERVER_URL
    api_data["ai_reply"] = {
        **ai_reply,
        "enabled": ai_reply.get("enabled", True),
        "mode": "cloud",
        "cloud_base_url": license_server_url,
        "base_url": "",
        "api_key": "",
        "model": ai_reply.get("model", "deepseek-v4-flash"),
        "temperature": ai_reply.get("temperature", 0.7),
        "max_tokens": ai_reply.get("max_tokens", 120),
        "license": {
            "server_url": license_server_url,
            "key": (license_key or "").strip(),
        },
    }
    _save_yaml_file(api_path, api_data)


# ======================== API 路由 ========================

@app.get("/", summary="根目录重定向")
def root_redirect():
    """将根目录请求重定向到 Swagger API 文档"""
    return RedirectResponse(url="/docs")


# ----------------- 接口: 设备管理 -----------------
@app.get("/api/devices", summary="获取已连接设备列表")
def api_get_devices():
    devices = get_connected_devices()
    return {"success": True, "devices": devices}


@app.post("/api/devices/usb/detect", summary="检测 USB 连接设备")
def api_detect_usb_devices():
    result = detect_usb_devices(verify_u2=True, persist=True)
    logging.info(f"USB 设备检测结果: {result.get('message')}")
    return result


@app.post("/api/devices/pair", summary="无线配对设备")
def api_pair_device(req: DevicePairRequest):
    ip_port = req.ip_port.strip()
    code = req.code.strip()
    if not ip_port or not code:
        return {"success": False, "message": "IP地址端口和配对码不能为空"}

    logging.info(f"尝试配对设备: {ip_port} (验证码: {code})")
    if run_cmd([ADB_BIN, "pair", ip_port, code]):
        return {"success": True, "message": f"成功与设备 {ip_port} 完成配对"}
    else:
        return {"success": False, "message": f"配对 {ip_port} 失败，请检查配对码是否正确或已过期"}


@app.post("/api/devices/connect", summary="无线连接设备")
def api_connect_device(req: DeviceConnectRequest):
    ip_port = req.ip_port.strip()
    if not ip_port:
        return {"success": False, "message": "IP地址和端口不能为空"}

    logging.info(f"尝试连接设备: {ip_port}")
    if not run_cmd([ADB_BIN, "connect", ip_port]):
        return {"success": False, "message": f"连接 {ip_port} 失败，请检查手机是否开启无线调试或IP端口是否正确"}

    # adb connect 即使对不可达地址也会返回 0，需要再次确认设备是否真实出现在设备列表中
    connected_devices = get_connected_devices()
    if ip_port in connected_devices:
        return {"success": True, "message": f"成功连接至设备 {ip_port}"}
    logging.warning(f"adb connect 命令成功但设备列表中未出现 {ip_port}，当前设备: {connected_devices}")
    return {"success": False, "message": f"连接 {ip_port} 失败，设备未真实上线，请检查手机是否开启无线调试或IP端口是否正确"}


@app.post("/api/devices/disconnect", summary="断开设备连接")
def api_disconnect_device(req: DeviceConnectRequest):
    serial = req.ip_port.strip()
    if not serial:
        return {"success": False, "message": "设备标识不能为空"}

    logging.info(f"尝试断开设备连接: {serial}")
    if run_cmd([ADB_BIN, "disconnect", serial]):
        # 停止该设备上的任务并清理状态
        task = get_running_task(serial)
        if task:
            try:
                task.stop()
            except Exception:
                pass
            del_running_task(serial)
        del_task_status(serial)
        return {"success": True, "message": f"已成功断开设备 {serial} 的连接"}
    else:
        return {"success": False, "message": f"断开设备 {serial} 失败"}


# ----------------- 接口: 配置管理 -----------------
@app.get("/api/config", summary="读取当前配置")
def api_get_config(platform: str = "douyin"):
    """
    读取指定平台的运行配置
    - platform: "douyin" (抖音)，默认为 "douyin"
    """
    try:
        config = _load_douyin_config_for_frontend()
        return {"success": True, "config": config}
    except Exception as e:
        return {"success": False, "message": f"读取配置失败: {str(e)}"}


@app.post("/api/config", summary="保存前端配置")
def api_save_config(config: AppConfig, platform: str = "douyin"):
    """
    保存指定平台的运行配置
    - platform: "douyin" (抖音)，默认为 "douyin"
    """
    try:
        if (config.license_key or "").strip():
            verify_license(
                config.license_key,
                config.license_server_url or DEFAULT_LICENSE_SERVER_URL,
            )

        old_data = _load_yaml_file(DY_USER_CONFIG_PATH)
        previous_max_daily = old_data.get("crawler", {}).get("max_daily_videos") if isinstance(old_data.get("crawler"), dict) else None
        _save_douyin_config(config)

        if previous_max_daily is not None and previous_max_daily != config.max_daily_videos:
            if db_manager.reset_daily_progress():
                logging.info("检测到每日处理内容总上限变更，已重置当天统计记录和待处理缓存。")
                return {
                    "success": True,
                    "message": "配置保存成功，今日处理数和待处理缓存已归零"
                }
            logging.warning("每日处理内容总上限已更新，但重置当天统计记录失败。")
            return {
                "success": False,
                "message": "配置已保存，但今日处理数和待处理缓存归零失败"
            }

        return {"success": True, "message": "配置保存成功"}
    except LicenseError as e:
        return {"success": False, "message": f"授权码验证失败: {str(e)}"}
    except Exception as e:
        return {"success": False, "message": f"保存配置失败: {str(e)}"}


@app.post("/api/license/verify", summary="验证客户授权码")
def api_verify_license(req: LicenseVerifyRequest):
    try:
        data = verify_license(
            req.license_key,
            req.license_server_url or DEFAULT_LICENSE_SERVER_URL,
            device_id=req.device_id,
        )
        return {
            "success": True,
            "message": "授权码验证成功",
            "data": {
                "customer_name": data.get("customer_name", ""),
                "status": data.get("status", ""),
                "balance_credits": data.get("balance_credits", 0),
                "token_per_credit": data.get("token_per_credit", 1000),
                "license_key_masked": mask_license_key(req.license_key),
            },
        }
    except LicenseError as exc:
        return {"success": False, "message": str(exc), "data": {}}


@app.post("/api/license/save", summary="验证并保存客户授权码")
def api_save_license(req: LicenseVerifyRequest, platform: str = "douyin"):
    try:
        data = verify_license(
            req.license_key,
            req.license_server_url or DEFAULT_LICENSE_SERVER_URL,
            device_id=req.device_id,
        )
        _save_platform_license(platform, req.license_key, req.license_server_url or DEFAULT_LICENSE_SERVER_URL)
        return {
            "success": True,
            "message": "授权码验证并保存成功",
            "data": {
                "customer_name": data.get("customer_name", ""),
                "status": data.get("status", ""),
                "balance_credits": data.get("balance_credits", 0),
                "token_per_credit": data.get("token_per_credit", 1000),
                "license_key_masked": mask_license_key(req.license_key),
            },
        }
    except LicenseError as exc:
        return {"success": False, "message": str(exc), "data": {}}
    except Exception as exc:
        return {"success": False, "message": f"保存授权码失败: {exc}", "data": {}}


@app.get("/api/license/status", summary="获取当前授权码状态和积分余额")
def api_license_status(platform: str = "douyin"):
    """返回已保存授权码的当前余额信息。无需重新提交授权码。"""
    try:
        license_config = _get_license_config_for_platform(platform)
        license_key = license_config.get("key", "")
        if not license_key:
            return {"success": True, "data": {"has_license": False}}
        data = verify_license(
            license_key,
            license_config.get("server_url", DEFAULT_LICENSE_SERVER_URL),
        )
        return {
            "success": True,
            "data": {
                "has_license": True,
                "customer_name": data.get("customer_name", ""),
                "balance_credits": data.get("balance_credits", 0),
                "token_per_credit": data.get("token_per_credit", 1000),
                "license_key_masked": mask_license_key(license_key),
                "status": data.get("status", ""),
            },
        }
    except LicenseError as exc:
        return {"success": False, "message": str(exc), "data": {"has_license": False}}
    except Exception as exc:
        return {"success": False, "message": f"查询状态失败: {exc}", "data": {"has_license": False}}


# ----------------- 接口: 账号登录 -----------------
@app.post("/api/auth/register", summary="邮箱注册账号")
def api_auth_register(req: AuthRegisterRequest):
    """注册新账号（邮箱+密码，无验证码），成功后自动登录并写入本地 token。"""
    data, err = _account_request("/auth/register", method="POST", json_body={
        "email": req.email,
        "password": req.password,
    })
    if err:
        return {"success": False, "message": err, "data": {}}
    payload = data.get("data") or {}
    token = payload.get("token", "")
    user = payload.get("user") or {}
    email = user.get("email", "")
    if token:
        _write_auth_file(token, email)
    return {"success": True, "message": data.get("message", "注册成功"), "data": payload}


@app.post("/api/auth/login", summary="邮箱登录账号")
def api_auth_login(req: AuthLoginRequest):
    """登录账号，成功后写入本地 token（永久记住）。"""
    data, err = _account_request("/auth/login", method="POST", json_body={
        "email": req.email,
        "password": req.password,
    })
    if err:
        return {"success": False, "message": err, "data": {}}
    payload = data.get("data") or {}
    token = payload.get("token", "")
    user = payload.get("user") or {}
    email = user.get("email", "")
    if token:
        _write_auth_file(token, email)
    return {"success": True, "message": data.get("message", "登录成功"), "data": payload}


@app.get("/api/auth/check", summary="校验当前登录态")
def api_auth_check():
    """读 config/auth.json 的 token，调云端 /auth/profile 校验有效性。"""
    auth = _read_auth_file()
    token = auth.get("token", "")
    if not token:
        return {"success": False, "logged_in": False, "message": "未登录"}
    data, err = _account_request("/auth/profile", method="GET", token=token)
    if err:
        # token 失效或服务异常，清掉本地 token 避免反复用坏 token
        _clear_auth_file()
        return {"success": False, "logged_in": False, "message": err}
    profile = data.get("data") or {}
    return {
        "success": True,
        "logged_in": True,
        "message": "已登录",
        "data": {
            "email": profile.get("email", auth.get("email", "")),
            "created_at": profile.get("created_at", ""),
            "last_login_at": profile.get("last_login_at", ""),
        },
    }


@app.post("/api/auth/logout", summary="退出登录")
def api_auth_logout():
    """调云端 /auth/logout 吊销 token，并删除本地 auth.json。"""
    auth = _read_auth_file()
    token = auth.get("token", "")
    if token:
        _account_request("/auth/logout", method="POST", token=token)
    _clear_auth_file()
    return {"success": True, "message": "已退出登录"}


# ----------------- 接口: 任务控制 -----------------
def _get_config_path() -> str:
    """返回抖音任务流所需的配置文件路径"""
    return DY_USER_CONFIG_PATH


def run_task_on_device(serial: str, platform: str = "douyin", startup_delay: float = 0):
    """
    后台执行实际任务的函数。
    每个设备在独立线程中运行，线程由 _task_executor 统一调度。
    支持短暂、可解释的启动错峰，避免多台设备同时初始化导致 USB/ADB 争抢。
    """
    set_task_status(serial, {"status": "starting", "error": None, "platform": platform})
    if startup_delay > 0:
        logging.info(f"设备 {serial} 将在 {startup_delay:.1f}s 后启动，避免 ADB 初始化瞬时争抢")
        time.sleep(startup_delay)
    if is_task_stop_requested(serial):
        set_task_status(serial, {"status": "stopped", "error": None, "platform": platform})
        logging.info(f"<== API: 设备 {serial} 在启动前已被取消")
        clear_task_stop_request(serial)
        return
    logging.info(f"==> API: 开始初始化设备 {serial} 的{platform}平台任务")

    config_path = _get_config_path()
    try:
        task_flow = TikTokTaskFlow(
            serial=serial,
            config_path=config_path,
            status_reporter=partial(report_device_action, serial),
        )

        set_running_task(serial, task_flow)
        if is_task_stop_requested(serial):
            task_flow.stop()
            set_task_status(serial, {"status": "stopped", "error": None, "platform": platform})
            logging.info(f"<== API: 设备 {serial} 初始化后检测到取消请求")
            return
        set_task_status(serial, {"status": "running", "error": None, "platform": platform})
        logging.info(f"==> API: 设备 {serial} 已进入运行状态")
        task_flow.start()

        if task_flow.is_stopped:
            set_task_status(serial, {"status": "stopped", "error": None})
            logging.info(f"<== API: 设备 {serial} 任务被手动停止")
        else:
            set_task_status(serial, {"status": "completed", "error": None})
            logging.info(f"<== API: 设备 {serial} 任务执行完毕")

    except InterruptedError as e:
        set_task_status(serial, {"status": "stopped", "error": str(e)})
        logging.info(f"<== API: 设备 {serial} 任务已中断: {e}")
    except Exception as e:
        set_task_status(serial, {"status": "error", "error": str(e)})
        logging.error(f"API: 设备 {serial} 执行异常: {e}")
    finally:
        clear_task_stop_request(serial)
        del_running_task(serial)


@app.post("/api/tasks/start", summary="启动设备自动化任务")
def api_start_tasks(req: TaskStartRequest):
    if not req.devices:
        return {"success": False, "message": "未选择任何设备"}

    try:
        license_info = _verify_platform_license(req.platform, device_id=req.devices[0] if req.devices else "")
        balance = license_info.get("balance_credits", 0)
        # F1: 启动任务前校验余额，避免余额为 0 的用户启动后跑到 AI 环节才失败
        try:
            balance_val = float(balance)
        except (TypeError, ValueError):
            balance_val = 0.0
        if balance_val <= 0:
            return {"success": False, "message": "授权码积分不足，请充值后启动任务"}
        logging.info(
            "授权码验证通过，客户: %s，剩余积分: %s",
            license_info.get("customer_name", ""),
            balance,
        )
    except HTTPException as exc:
        return {"success": False, "message": f"授权校验失败：{exc.detail}"}

    started_devices = []
    skipped_devices = []
    for index, serial in enumerate(req.devices):
        if is_task_running(serial):
            skipped_devices.append(serial)
            continue
        clear_task_stop_request(serial)
        set_task_queued(serial, req.platform)
        # 使用全局线程池调度任务，支持最大 MAX_CONCURRENT_DEVICES 并发
        _task_executor.submit(run_task_on_device, serial, req.platform, min(index * 0.5, 25.0))
        started_devices.append(serial)

    if started_devices:
        message = f"成功提交 {len(started_devices)} 台设备任务（最大并发 10 台）"
        if skipped_devices:
            message += f"，已跳过 {len(skipped_devices)} 台启动中/运行中的设备"
        return {"success": True, "message": message, "data": {"devices": started_devices, "skipped": skipped_devices}}
    else:
        return {"success": False, "message": "设备已在启动中或运行中，无法重复启动"}


@app.post("/api/tasks/stop", summary="结束设备自动化任务")
def api_stop_tasks(req: TaskStartRequest):
    if not req.devices:
        return {"success": False, "message": "未选择任何设备"}

    stopped_devices = []
    for serial in req.devices:
        task = get_running_task(serial)
        if task:
            task.stop()
            stopped_devices.append(serial)
            continue
        status = get_task_status(serial, {})
        if status.get("status") in {"queued", "starting"}:
            request_task_stop(serial)
            set_task_status(serial, {"status": "stopped", "error": None, "platform": status.get("platform", req.platform)})
            stopped_devices.append(serial)

    if stopped_devices:
        return {"success": True, "message": f"已向 {len(stopped_devices)} 台设备发送结束指令"}
    else:
        return {"success": False, "message": "所选设备当前没有运行中的任务"}


@app.post("/api/tasks/pause", summary="暂停设备自动化任务")
def api_pause_tasks(req: TaskStartRequest):
    if not req.devices:
        return {"success": False, "message": "未选择任何设备"}

    paused_devices = []
    for serial in req.devices:
        task = get_running_task(serial)
        if task:
            task.pause()
            set_task_status(serial, {"status": "paused", "error": None})
            paused_devices.append(serial)

    if paused_devices:
        return {"success": True, "message": f"已暂停 {len(paused_devices)} 台设备"}
    else:
        return {"success": False, "message": "所选设备当前没有运行中的任务"}


@app.post("/api/tasks/resume", summary="继续设备自动化任务")
def api_resume_tasks(req: TaskStartRequest):
    if not req.devices:
        return {"success": False, "message": "未选择任何设备"}

    resumed_devices = []
    for serial in req.devices:
        task = get_running_task(serial)
        if task:
            task.resume()
            set_task_status(serial, {"status": "running", "error": None})
            resumed_devices.append(serial)

    if resumed_devices:
        return {"success": True, "message": f"已恢复 {len(resumed_devices)} 台设备"}
    else:
        return {"success": False, "message": "所选设备当前没有可恢复的任务"}


@app.get("/api/tasks/status", summary="查询所有设备的任务运行状态")
def api_get_task_status():
    with _task_status_lock:
        return {"success": True, "status": dict(_task_status)}


@app.get("/api/logs", summary="获取最新系统日志")
def api_get_logs():
    return {"success": True, "logs": list(MEMORY_LOGS)}


# ----------------- 接口: 数据统计 -----------------
@app.get("/api/stats", summary="获取今日数据大屏统计")
def api_get_stats():
    stats = db_manager.get_daily_stats()
    return {"success": True, "data": stats}


@app.get("/api/stats/details", summary="获取今日详细操作记录")
def api_get_stats_details(limit: int = 100):
    records = db_manager.get_daily_records(limit=limit)
    return {"success": True, "data": records}


@app.delete("/api/stats", summary="清空今日所有操作记录")
def api_clear_today_stats():
    """清空当日 records_YYYYMMDD 表的全部行（保留表结构）。

    用于客户在 GUI 上手动重置今日数据。注意：
    - 仅清空当日表，不影响历史日期表
    - 不影响已配置的关键词、设备等设置
    """
    try:
        if db_manager.reset_daily_progress():
            logging.info("GUI 触发清空今日操作记录成功")
            return {"success": True, "message": "今日操作记录已清空"}
        logging.warning("GUI 触发清空今日操作记录失败")
        return {"success": False, "message": "清空今日操作记录失败"}
    except Exception as e:
        logging.error(f"清空今日操作记录异常: {e}")
        return {"success": False, "message": f"清空失败：{e}"}


if __name__ == "__main__":
    import uvicorn
    # 不使用 reload：任务执行时数据库文件频繁变化会触发重启，导致 GUI 窗口被信号终止
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000)
