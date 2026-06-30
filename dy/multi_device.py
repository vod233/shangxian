import threading
import time
import subprocess
import adbutils
import logging

logger = logging.getLogger(__name__)

# FIX(DEV-S2): 50 并发线程同时调用 adbutils.adb.device_list() 会全部打到本地 5037 端口的
# 单一 adb server 进程，触发命令排队 / device offline 抖动 / device unauthorized 偶发错误。
# 这里用全局 RLock 串行化 device_list 调用，并加 2 秒短缓存：2 秒内复用上一次结果，
# 避免 50 个线程在相近时刻各发一次 device_list。
_device_list_lock = threading.RLock()
_device_list_cache = {"ts": 0.0, "data": None}
_DEVICE_LIST_CACHE_TTL = 2.0  # 秒

# FIX(DEV-C5): ADB server 单点故障全局保护
# 旧实现 adb server 崩溃后所有设备视为掉线，无重启机制，必须人工 adb kill-server。
# 这里用全局标志 + 锁，确保多线程并发触发时只重启一次 adb server。
_adb_server_rebuild_lock = threading.Lock()
_adb_last_rebuild_ts = 0.0


def _rebuild_adb_server():
    """重启 ADB server（kill-server + start-server），用于 adb server 崩溃后自动恢复。

    FIX(DEV-C5): 旧实现无任何 adb server 重启逻辑，server 崩溃后 50 台任务全 error。
    这里在检测到 adb server 异常时自动 kill-server + start-server，并加 10 秒冷却
    避免多线程并发触发频繁重启。
    """
    global _adb_last_rebuild_ts
    with _adb_server_rebuild_lock:
        now = time.time()
        if now - _adb_last_rebuild_ts < 10.0:
            logger.info("ADB server 重启在冷却期内（10s），跳过本次重启")
            return False
        _adb_last_rebuild_ts = now
        logger.warning("检测到 ADB server 异常，执行 kill-server + start-server 重建")
        try:
            subprocess.run(["adb", "kill-server"], capture_output=True, timeout=15, check=False)
            time.sleep(1)
            subprocess.run(["adb", "start-server"], capture_output=True, timeout=30, check=False)
            time.sleep(2)
            logger.info("ADB server 重建完成")
            # 重建后清空设备列表缓存，强制下一次重新查询
            with _device_list_lock:
                _device_list_cache["data"] = None
                _device_list_cache["ts"] = 0.0
            return True
        except Exception as exc:
            logger.error(f"ADB server 重建失败: {exc}")
            return False


def get_connected_devices(force_refresh=False):
    """获取当前通过 ADB 连接的所有真实设备序列号列表。

    FIX(DEV-C5 + DEV-S2):
    - DEV-S2: 全局 RLock 串行化 + 2 秒短缓存，避免 50 并发线程同时打 adb server。
    - DEV-C5: 检测到 adb server 异常（device_list 抛错）时自动 kill-server + start-server，
              重启后重试一次；仍失败才返回空列表。
    """
    with _device_list_lock:
        # 短缓存命中（非 force_refresh 时）
        if not force_refresh and _device_list_cache["data"] is not None:
            if time.time() - _device_list_cache["ts"] < _DEVICE_LIST_CACHE_TTL:
                logger.debug("设备列表缓存命中，复用上一次结果（避免并发打 adb server）")
                return list(_device_list_cache["data"])

        # 第一次尝试
        try:
            devices = adbutils.adb.device_list()
            valid_devices = []
            for d in devices:
                # 过滤掉局域网 mDNS (ZeroConf) 广播的虚拟设备名
                if "._adb-tls-" not in d.serial and not d.serial.endswith("._tcp"):
                    valid_devices.append(d.serial)
            _device_list_cache["data"] = list(valid_devices)
            _device_list_cache["ts"] = time.time()
            return valid_devices
        except Exception as e:
            logger.error(f"获取设备列表失败（第一次）: {e}")
            # DEV-C5: 怀疑 adb server 崩溃，触发重建后重试一次
            rebuilt = _rebuild_adb_server()
            if not rebuilt:
                return []
            try:
                devices = adbutils.adb.device_list()
                valid_devices = []
                for d in devices:
                    if "._adb-tls-" not in d.serial and not d.serial.endswith("._tcp"):
                        valid_devices.append(d.serial)
                _device_list_cache["data"] = list(valid_devices)
                _device_list_cache["ts"] = time.time()
                logger.info(f"ADB server 重建后设备列表: {valid_devices}")
                return valid_devices
            except Exception as e2:
                logger.error(f"ADB server 重建后获取设备列表仍失败: {e2}")
                return []

def select_devices_interactively():
    """在控制台让用户交互式选择要操作的设备"""
    devices = get_connected_devices()
    
    if not devices:
        print("\n❌ 未检测到任何连接的设备！")
        print("请先通过 USB 连接手机，或运行 wireless_connect.py / scan_and_connect.py 进行无线连接。")
        return []
        
    print("\n" + "="*40)
    print("📱 已连接的设备列表")
    print("="*40)
    
    for idx, serial in enumerate(devices, 1):
        print(f" [{idx}] {serial}")
        
    print(" [0] 全部设备")
    print("="*40)
    
    while True:
        choice = input("\n请选择要执行任务的设备编号 (多个设备请用逗号分隔，如 '1,3'，输入 '0' 选择全部): ").strip()
        if not choice:
            continue
            
        if choice == '0':
            return devices
            
        selected_serials = []
        try:
            indices = [int(x.strip()) for x in choice.replace('，', ',').split(',')]
            for idx in indices:
                if 1 <= idx <= len(devices):
                    selected_serials.append(devices[idx-1])
                else:
                    print(f"⚠️ 警告: 编号 {idx} 超出范围，将被忽略。")
            
            if selected_serials:
                return list(set(selected_serials))  # 去重返回
            else:
                print("没有选择任何有效的设备，请重新输入。")
        except ValueError:
            print("❌ 输入格式错误，请输入数字编号，多个编号用逗号分隔。")
