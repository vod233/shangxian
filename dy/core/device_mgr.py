import os
import yaml
import logging
import adbutils
from device_connect_lock import locked_u2_connect

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class DeviceManager:
    def __init__(self, serial=None):
        self.serial = serial
        self.u2_device = None
        self.config_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'config',
            'scout_settings.yaml'
        )

    def _get_last_bound_serial(self):
        """读取配置文件中记录的上一次绑定的序列号"""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    config = yaml.safe_load(f)
                    if config and 'device' in config and 'last_bound_serial' in config['device']:
                        return config['device']['last_bound_serial']
            except Exception as e:
                logging.error(f"读取配置文件失败: {e}")
        return None

    def _save_last_bound_serial(self, serial):
        """更新配置文件中的序列号"""
        config = {'device': {'last_bound_serial': serial}}
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    existing_config = yaml.safe_load(f) or {}
                    if 'device' not in existing_config:
                        existing_config['device'] = {}
                    existing_config['device']['last_bound_serial'] = serial
                    config = existing_config
            except Exception:
                pass
                
        try:
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            with open(self.config_path, 'w', encoding='utf-8') as f:
                yaml.safe_dump(config, f, allow_unicode=True)
        except Exception as e:
            logging.error(f"保存配置文件失败: {e}")

    def connect(self):
        """连接设备的主逻辑"""
        # 1. ADB 实例校验
        devices = adbutils.adb.device_list()
        if not devices:
            raise RuntimeError("当前没有任何设备通过 ADB 连接到电脑，请先运行 scan_and_connect.py 或检查 USB 连接。")

        connected_serials = [d.serial for d in devices]
        logging.info(f"当前 ADB 连接设备列表: {connected_serials}")

        # 2. 序列号匹配分配
        # FIX(DEV-C3 兜底争抢设备):
        # 旧实现 `target_serial = connected_serials[0]` 在传入 serial 不在列表中时
        # 会强行接管第一台设备，50 并发下多线程同时回退到第一台 => 设备被并发抢夺失控。
        # 改为：传了 serial 但不在列表 => 直接抛错，拒绝回退；
        #       仅在未传 serial (None) 时才允许取第一台（单设备调试场景）。
        target_serial = None
        if self.serial:
            if self.serial in connected_serials:
                target_serial = self.serial
                logging.info(f"使用传入的序列号: {target_serial}")
            else:
                raise RuntimeError(
                    f"指定的设备序列号 {self.serial} 不在 ADB 连接列表 {connected_serials} 中，"
                    f"拒绝回退接管其他设备（避免 50 并发下多线程争抢同一台设备）。"
                )
        else:
            # 尝试读取配置文件
            last_serial = self._get_last_bound_serial()
            if last_serial and last_serial in connected_serials:
                target_serial = last_serial
                logging.info(f"使用配置文件中上一次绑定的序列号: {target_serial}")
            else:
                # 仅在未显式指定 serial 时允许取第一台（单设备调试场景）
                target_serial = connected_serials[0]
                logging.warning(f"未指定序列号，回退接管第一台设备: {target_serial}")

        self.serial = target_serial
        self._save_last_bound_serial(self.serial)

        # 3. 挂载 UIAutomator2 引擎
        logging.info(f"正在向设备 {self.serial} 挂载 UIAutomator2 引擎...")
        self.u2_device = locked_u2_connect(self.serial)
        logging.info(f"设备 {self.serial} uiautomator2 引擎挂载成功。")

        return self.u2_device

    def check_health(self):
        """心跳保活检查（轻量，仅探测，不重连）"""
        if not self.u2_device:
            logging.error("设备未连接或引擎未挂载，无法检查健康状态。")
            return False

        try:
            # 通过获取屏幕状态验证设备通讯通道
            screen_on = self.u2_device.info.get('screenOn')
            logging.info(f"心跳检查 - 设备 {self.serial} 屏幕状态: {'亮起' if screen_on else '熄灭'}")
            return True
        except Exception as e:
            logging.error(f"心跳检查失败，设备 {self.serial} 通讯通道可能已断开: {e}")
            return False

    def healthcheck_with_recovery(self, max_retries=2):
        """运行中心跳检查 + 自动恢复。

        FIX(DEV-C1/C2/C4):
        - DEV-C1: 旧实现 check_health 仅初始化时调用一次，全程无心跳；
                  设备掉线后任务空转，DB 持续写假数据。这里改为可由任务循环周期调用。
        - DEV-C2: 探测失败时尝试 u2 重连，恢复通讯通道。
        - DEV-C4: 探测失败时先尝试 atx-agent healthcheck（重启 uiautomator2 APK），
                  应对长时间运行后 atx-agent OOM/ANR。
        返回 True 表示设备当前可用（含恢复成功）；False 表示彻底不可用，上层应停止任务。
        """
        if not self.u2_device:
            return False
        for attempt in range(max_retries + 1):
            try:
                # info 接口会触发 atx-agent HTTP RPC，是最敏感的存活探测
                _ = self.u2_device.info
                return True
            except Exception as e:
                logging.warning(
                    f"设备 {self.serial} 心跳失败(尝试 {attempt + 1}/{max_retries + 1}): {e}"
                )
                if attempt >= max_retries:
                    return False
                # 恢复步骤 ①：atx-agent healthcheck（重启 uiautomator2 APK，应对 OOM/ANR）
                try:
                    if hasattr(self.u2_device, 'healthcheck'):
                        self.u2_device.healthcheck()
                        logging.info(f"设备 {self.serial} atx-agent healthcheck 已执行")
                        # 短暂等待 atx-agent 重启
                        import time as _t
                        _t.sleep(2)
                except Exception as hc_err:
                    logging.warning(f"设备 {self.serial} atx-agent healthcheck 失败: {hc_err}")
                # 恢复步骤 ②：重新 u2.connect（应对 USB 断开 / atx-agent 端口失效）
                try:
                    self.u2_device = locked_u2_connect(self.serial)
                    logging.info(f"设备 {self.serial} u2 重连成功")
                except Exception as rc_err:
                    logging.error(f"设备 {self.serial} u2 重连失败: {rc_err}")
        return False

    def reconnect(self):
        """显式重连：重新挂载 uiautomator2 引擎。

        FIX(DEV-C2): 旧实现无任何重连代码路径，单台设备掉线即本轮卡死，需人工重启后端。
        这里提供显式重连入口，供任务流在检测到异常时主动调用。
        """
        logging.info(f"设备 {self.serial} 执行显式重连...")
        try:
            self.u2_device = locked_u2_connect(self.serial)
            logging.info(f"设备 {self.serial} 重连成功")
            return True
        except Exception as e:
            logging.error(f"设备 {self.serial} 重连失败: {e}")
            return False

class ScoutControllerHybrid:
    def __init__(self, serial=None):
        self.device_mgr = DeviceManager(serial=serial)
        # 连接成功后，返回的 u2_device 对象被赋给 self.d
        self.d = self.device_mgr.connect()

    def check_status(self):
        return self.device_mgr.check_health()

    def check_status_with_recovery(self, max_retries=2):
        """运行中健康检查 + 自动重连（供 task_runner 任务循环周期调用）。

        FIX(DEV-C1): 暴露带恢复的心跳接口，让长循环能在每个视频处理前确认设备仍可用。
        """
        return self.device_mgr.healthcheck_with_recovery(max_retries=max_retries)
