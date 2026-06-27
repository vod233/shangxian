"""
抖音防风控核心引擎
====================
行业工作室顶级水平的防风控系统，包含：
1. 贝塞尔曲线滑动轨迹模拟（真人手势）
2. 坐标随机抖动（像素级偏移）
3. 人性化操作间隔（替代固定sleep）
4. 概率化互动决策（非100%互动）
5. 每日互动限额管理（账号级保护）
6. 夜间静默时段控制
7. 设备指纹痕迹清理
8. 行为模式随机化（模拟走神/回看等）
"""

import random
import time
import math
import logging
import json
import os
from datetime import datetime, timedelta
from functools import wraps

logger = logging.getLogger(__name__)


def _shell_text(result):
    if hasattr(result, "output"):
        return str(result.output or "")
    return str(result or "")


class HumanGesture:
    """
    真人手势模拟器
    - 贝塞尔曲线生成自然滑动轨迹
    - 多段速度变化（起步慢→中间快→收尾慢）
    - 轨迹微抖动（模拟手指不完全直线）
    - 起止点随机偏移
    """

    @staticmethod
    def _bezier_point(t, p0, p1, p2, p3):
        """三次贝塞尔曲线计算"""
        u = 1 - t
        tt = t * t
        uu = u * u
        return (uu * u * p0 + 3 * uu * t * p1 + 3 * u * tt * p2 + tt * t * p3)

    @staticmethod
    def _ease_in_out(t):
        """缓入缓出速度曲线，模拟手指起步和收尾的自然减速"""
        return 0.5 * (1 - math.cos(math.pi * t))

    @classmethod
    def generate_swipe_path(cls, sx, sy, ex, ey, steps=None):
        """
        生成从 (sx,sy) 到 (ex,ey) 的贝塞尔曲线轨迹点序列
        返回 [(x, y), ...] 列表
        """
        distance = math.hypot(ex - sx, ey - sy)
        if steps is None:
            # 根据距离动态计算步数，距离越长步数越多
            steps = max(15, min(40, int(distance / 15)))

        # 控制点偏移：在起止点连线两侧随机偏移，形成弧线
        mid_x = (sx + ex) / 2
        mid_y = (sy + ey) / 2
        # 偏移量与距离成正比，方向随机
        offset_mag = distance * random.uniform(0.08, 0.2)
        offset_angle = random.uniform(-math.pi / 3, math.pi / 3)
        cx1 = mid_x + math.cos(offset_angle) * offset_mag * random.uniform(0.5, 1.0)
        cy1 = mid_y + math.sin(offset_angle) * offset_mag * random.uniform(0.5, 1.0)
        cx2 = mid_x + math.cos(offset_angle) * offset_mag * random.uniform(0.3, 0.7)
        cy2 = mid_y + math.sin(offset_angle) * offset_mag * random.uniform(0.3, 0.7)

        points = []
        for i in range(steps + 1):
            t = i / steps
            eased_t = cls._ease_in_out(t)
            x = cls._bezier_point(eased_t, sx, cx1, cx2, ex)
            y = cls._bezier_point(eased_t, sy, cy1, cy2, ey)
            # 添加微小抖动（±1~2px），模拟手指不稳
            x += random.uniform(-1.5, 1.5)
            y += random.uniform(-1.5, 1.5)
            points.append((int(x), int(y)))
        return points

    @classmethod
    def human_swipe(cls, device, sx, sy, ex, ey, duration=None):
        """
        执行人性化滑动
        :param device: uiautomator2 设备实例
        :param sx, sy: 起点坐标
        :param ex, ey: 终点坐标
        :param duration: 可选固定时长，否则随机
        """
        if duration is None:
            distance = math.hypot(ex - sx, ey - sy)
            if distance > 500:
                duration = random.uniform(0.10, 0.18)
            else:
                duration = random.uniform(0.06, 0.12)

        # 起止点随机偏移（±5~15px）
        jitter = random.randint(5, 15)
        sx += random.randint(-jitter, jitter)
        sy += random.randint(-jitter, jitter)
        ex += random.randint(-jitter, jitter)
        ey += random.randint(-jitter, jitter)

        # uiautomator2 的 swipe 不支持同时设置 duration 和 steps
        # 只使用 duration，u2 内部会自动计算步数
        device.swipe(sx, sy, ex, ey, duration=duration)

    @classmethod
    def human_swipe_with_curve(cls, device, sx, sy, ex, ey, duration=None):
        """
        执行贝塞尔曲线滑动（恢复真实曲线轨迹）。

        此前为避免误触长按菜单退化为普通 swipe，导致曲线轨迹未生效。
        现改用 swipe_points，通过控制点间时长 < 80ms 避免长按判定，
        并在起止点附近加入随机抖动。
        """
        if duration is None:
            distance = math.hypot(ex - sx, ey - sy)
            duration = random.uniform(0.30, 0.55) if distance > 500 else random.uniform(0.20, 0.40)

        jitter = random.randint(3, 12)
        sx += random.randint(-jitter, jitter)
        sy += random.randint(-jitter, jitter)
        ex += random.randint(-jitter, jitter)
        ey += random.randint(-jitter, jitter)

        # 生成贝塞尔曲线轨迹点
        points = cls.generate_swipe_path(sx, sy, ex, ey)
        # 每点间隔控制在 20~40ms，总时长 = 点数 × 间隔，远低于长按阈值(500ms 按住)
        step_ms = max(20, min(40, int(duration * 1000 / max(1, len(points)))))
        try:
            device.swipe_points(points, duration=step_ms / 1000.0 * len(points))
        except Exception:
            # 兜底：swipe_points 不可用时退回普通 swipe
            device.swipe(sx, sy, ex, ey, duration=duration)

    @classmethod
    def fast_tap(cls, device, x, y, hold=0.045):
        """短按点击，降低抖音视频页把 click 误判成长按的概率。"""
        try:
            device.touch.down(x, y)
            time.sleep(hold)
            device.touch.up(x, y)
        except Exception:
            device.click(x, y)

    @classmethod
    def human_click(cls, device, x, y, jitter_range=8):
        """
        人性化点击：在目标坐标附近随机偏移后点击
        :param jitter_range: 像素抖动范围
        """
        x += random.randint(-jitter_range, jitter_range)
        y += random.randint(-jitter_range, jitter_range)
        cls.fast_tap(device, x, y)

    @classmethod
    def human_double_click(cls, device, x, y, jitter_range=10):
        """
        人性化双击：两次点击位置略有不同，间隔随机
        """
        # 第一次点击
        x1 = x + random.randint(-jitter_range, jitter_range)
        y1 = y + random.randint(-jitter_range, jitter_range)
        cls.fast_tap(device, x1, y1)

        # 随机间隔（0.08~0.18秒，真人双击间隔）
        time.sleep(random.uniform(0.08, 0.18))

        # 第二次点击（位置略有偏移）
        x2 = x + random.randint(-jitter_range, jitter_range)
        y2 = y + random.randint(-jitter_range, jitter_range)
        cls.fast_tap(device, x2, y2)


class HumanSleep:
    """
    人性化等待时间
    - 替代所有固定 time.sleep
    - 引入偶发长停顿（模拟走神/看内容）
    - 操作间隔随机化
    """

    # 预定义的操作类型及其默认时间范围
    SLEEP_RANGES = {
        'fast': (0.3, 0.8),        # 快速操作（按钮点击后）
        'normal': (0.8, 2.0),     # 正常操作（页面切换）
        'slow': (2.0, 4.5),       # 慢操作（加载等待）
        'page_load': (2.5, 5.0),  # 页面加载
        'video_stay': (5.0, 15.0), # 视频停留
        'comment_browse': (1.0, 3.0), # 评论区浏览
        'action_gap': (1.0, 3.5), # 操作间隙
    }

    @classmethod
    def sleep(cls, sleep_type='normal', custom_range=None):
        """
        执行人性化等待
        :param sleep_type: 预定义类型
        :param custom_range: 自定义范围 (min, max)
        """
        if custom_range:
            min_t, max_t = custom_range
        else:
            min_t, max_t = cls.SLEEP_RANGES.get(sleep_type, (0.8, 2.0))

        wait_time = random.uniform(min_t, max_t)

        # 5% 概率出现长停顿（模拟走神/被内容吸引）
        if sleep_type in ('normal', 'action_gap') and random.random() < 0.05:
            wait_time += random.uniform(2.0, 6.0)
            logger.debug(f"模拟走神停顿: +{wait_time:.1f}s")

        time.sleep(wait_time)
        return wait_time

    @classmethod
    def interruptible_sleep(cls, seconds, check_callback=None, interval=0.5):
        """
        可中断的人性化等待
        """
        slept = 0.0
        while slept < seconds:
            if check_callback:
                check_callback()
            actual_interval = min(interval + random.uniform(-0.1, 0.2), seconds - slept)
            if actual_interval <= 0:
                break
            time.sleep(max(0.1, actual_interval))
            slept += actual_interval


class InteractionProbability:
    """
    概率化互动决策
    - 模拟真人不是每个视频都点赞/评论/关注
    - 可配置互动概率
    """

    DEFAULT_PROBABILITIES = {
        'like': 0.45,          # 45% 概率点赞
        'comment': 0.15,       # 15% 概率评论
        'follow': 0.20,       # 20% 概率关注
        'private_message': 0.10, # 10% 概率私信
        'comment_lead': 0.30, # 30% 概率查看评论区
        'long_watch': 0.15,    # 15% 概率长停留（看完视频）
    }

    @classmethod
    def should_interact(cls, action_type, config=None):
        """
        根据概率决定是否执行互动
        :param action_type: like/comment/follow/private_message/comment_lead/long_watch
        :param config: 配置字典，可覆盖默认概率
        """
        anti_cfg = (config or {}).get('anti_detection', {})
        prob_cfg = anti_cfg.get('interaction_probability', {})
        probability = prob_cfg.get(action_type, cls.DEFAULT_PROBABILITIES.get(action_type, 1.0))

        result = random.random() < probability
        if not result:
            logger.info(f"概率决策: 跳过 {action_type} (概率={probability:.0%})")
        return result


class DailyLimitManager:
    """
    每日互动限额管理器
    - 防止单账号单日互动次数过高
    - 支持自定义每种互动的日上限
    - 超限自动停止对应互动
    - 使用 per-instance 内存计数器，避免多设备共享全局 db 统计导致限额合并
    """

    DEFAULT_LIMITS = {
        'daily_like_limit': 80,        # 每日点赞上限
        'daily_comment_limit': 30,     # 每日评论上限
        'daily_follow_limit': 20,      # 每日关注上限
        'daily_message_limit': 15,     # 每日私信上限
        'daily_video_limit': 100,      # 每日视频上限
    }

    # action_type -> 内存计数 key 的映射
    _ACTION_TO_COUNT_KEY = {
        'like': 'likes',
        'comment': 'comments',
        'follow': 'follows',
        'private_message': 'private_messages',
        'video': 'videos',
    }

    def __init__(self, config=None, db_manager=None):
        self.config = config or {}
        self.db = db_manager
        anti_cfg = self.config.get('anti_detection', {})
        limits_cfg = anti_cfg.get('daily_limits', {})
        self.limits = {**self.DEFAULT_LIMITS, **limits_cfg}
        # 本实例（即本设备）今日已执行计数
        self._counts = {
            'likes': 0, 'comments': 0, 'follows': 0, 'private_messages': 0, 'videos': 0,
        }

    def _get_current_stats(self):
        """获取今日互动统计：优先用本实例内存计数，避免多设备合并"""
        return dict(self._counts)

    def record_action(self, action_type):
        """记录一次已执行的互动，供限额统计使用"""
        key = self._ACTION_TO_COUNT_KEY.get(action_type)
        if key:
            self._counts[key] = self._counts.get(key, 0) + 1

    def can_do(self, action_type):
        """检查是否还能执行某类互动"""
        stats = self._get_current_stats()

        checks = {
            'like': ('daily_like_limit', stats.get('likes', 0)),
            'comment': ('daily_comment_limit', stats.get('comments', 0)),
            'follow': ('daily_follow_limit', stats.get('follows', 0)),
            'private_message': ('daily_message_limit', stats.get('private_messages', 0)),
            'video': ('daily_video_limit', stats.get('videos', 0)),
        }

        if action_type not in checks:
            return True

        limit_key, current = checks[action_type]
        limit = self.limits.get(limit_key, 999999)

        if current >= limit:
            logger.warning(f"⚠️ {action_type} 已达每日上限 ({current}/{limit})，自动跳过")
            return False
        return True

    def check_all_limits(self):
        """检查是否所有互动都已超限（应该休息了）"""
        all_exceeded = True
        for action_type in ['like', 'comment', 'follow', 'private_message']:
            if self.can_do(action_type):
                all_exceeded = False
                break
        return all_exceeded


class NightModeController:
    """
    夜间静默时段控制
    - 在指定时间段内暂停所有操作
    - 模拟真人作息规律
    """

    def __init__(self, config=None):
        anti_cfg = (config or {}).get('anti_detection', {})
        night_cfg = anti_cfg.get('night_mode', {})
        self.enabled = night_cfg.get('enabled', True)
        self.start_hour = night_cfg.get('start_hour', 23)  # 23:00 开始静默
        self.end_hour = night_cfg.get('end_hour', 7)        # 07:00 结束静默
        self.pause_duration = night_cfg.get('pause_duration', 36000)  # 默认暂停10小时

    def is_night_time(self):
        """当前是否处于静默时段"""
        if not self.enabled:
            return False
        hour = datetime.now().hour
        if self.start_hour > self.end_hour:
            # 跨天，如 23:00 ~ 07:00
            return hour >= self.start_hour or hour < self.end_hour
        else:
            return self.start_hour <= hour < self.end_hour

    def wait_until_morning(self, check_callback=None):
        """等待到静默时段结束"""
        if not self.is_night_time():
            return

        now = datetime.now()
        end_today = now.replace(hour=self.end_hour, minute=0, second=0, microsecond=0)
        if end_today <= now:
            end_today += timedelta(days=1)

        wait_seconds = (end_today - now).total_seconds()
        logger.info(f"🌙 夜间静默时段，等待 {wait_seconds/3600:.1f} 小时后恢复...")

        slept = 0
        while slept < wait_seconds:
            if check_callback:
                try:
                    check_callback()
                except InterruptedError:
                    return
            # 随机化轮询间隔，避免固定 30s 节奏
            time.sleep(random.uniform(25, 40))
            slept += 30


class DeviceFingerprintGuard:
    """
    设备指纹防护
    - 清理 uiautomator2 在设备上留下的痕迹
    - 设备参数差异化建议
    """

    # uiautomator2 相关包名
    U2_PACKAGES = [
        'com.github.uiautomator',
        'com.github.uiautomator.test',
    ]

    # atx-agent 相关路径
    ATX_AGENT_PATH = '/data/local/tmp/atx-agent'

    @classmethod
    def cleanup_u2_traces(cls, device):
        """
        清理 uiautomator2 可检测的痕迹
        注意：这不会卸载 uiautomator2 本身（否则无法继续自动化），
        而是清理一些可被抖音检测的日志和缓存
        """
        try:
            # 清理 logcat 中的自动化痕迹
            device.shell(['logcat', '-c'])
            logger.debug("已清理 logcat 缓存")

            # 清理 /data/local/tmp 下的临时文件（保留 atx-agent）
            result = device.shell(['ls', '/data/local/tmp/'])
            result_text = _shell_text(result)
            if result_text:
                for line in result_text.strip().split('\n'):
                    line = line.strip()
                    # 删除 minicap/minitouch 等可被检测的工具
                    if line in ('minicap', 'minitouch', 'minicap.so') and not line.startswith('atx'):
                        try:
                            device.shell(['rm', '-f', f'/data/local/tmp/{line}'])
                            logger.debug(f"已清理: {line}")
                        except Exception:
                            pass
        except Exception as e:
            logger.warning(f"清理设备痕迹时出错: {e}")

    @classmethod
    def get_device_fingerprint_status(cls, device):
        """获取设备指纹相关状态"""
        try:
            info = {}
            info['android_id'] = _shell_text(device.shell(['settings', 'get', 'secure', 'android_id'])).strip()
            info['model'] = _shell_text(device.shell(['getprop', 'ro.product.model'])).strip()
            info['brand'] = _shell_text(device.shell(['getprop', 'ro.product.brand'])).strip()
            info['sdk'] = _shell_text(device.shell(['getprop', 'ro.build.version.sdk'])).strip()
            return info
        except Exception as e:
            logger.warning(f"获取设备信息失败: {e}")
            return {}


class NetworkStatusChecker:
    """
    4G 网络状态感知
    - 检测网络类型（4G/WiFi/无）
    - 检测信号强度
    - 用于 4G 流量卡场景下避免弱网下机械操作
    """

    @classmethod
    def check(cls, device):
        """返回 {'type': '4G'/'WIFI'/'NONE', 'level': 0-4, 'usable': bool}"""
        result = {'type': 'UNKNOWN', 'level': 0, 'usable': True}
        try:
            telephony_text = _shell_text(device.shell(['dumpsys', 'telephony.registry'])).lower()
            # 信号强度等级
            import re
            m = re.search(r'signalstrength.*?=(\d+)', telephony_text)
            if m:
                level = int(m.group(1))
                # dBm 值越接近 0 越好，-50 ~ -120
                if level > -70:
                    result['level'] = 4
                elif level > -85:
                    result['level'] = 3
                elif level > -100:
                    result['level'] = 2
                elif level > -110:
                    result['level'] = 1
                else:
                    result['level'] = 0
            # 网络类型
            if 'lte' in telephony_text or '4g' in telephony_text:
                result['type'] = '4G'
            elif 'nr' in telephony_text or '5g' in telephony_text:
                result['type'] = '5G'

            # 信号过弱视为不可用
            if result['level'] <= 0:
                result['usable'] = False
        except Exception as e:
            logger.debug(f"网络状态检测失败: {e}")
        return result


class BehaviorRandomizer:
    """
    行为模式随机化
    - 模拟真人的多样化行为
    - 偶尔回看、偶尔快速划过、偶尔长时间停留
    """

    @staticmethod
    def maybe_rewind(device, probability=0.05):
        """
        小概率回看上一个视频（模拟真人觉得有趣回看）
        """
        if random.random() < probability:
            logger.info("模拟行为: 回看上一个视频")
            w, h = device.window_size()
            # 向下滑动（回看）
            HumanGesture.human_swipe(device,
                                     w // 2 + random.randint(-20, 20),
                                     int(h * 0.3),
                                     w // 2 + random.randint(-20, 20),
                                     int(h * 0.7))
            HumanSleep.sleep('video_stay')
            # 再滑回来
            HumanGesture.human_swipe(device,
                                     w // 2 + random.randint(-20, 20),
                                     int(h * 0.7),
                                     w // 2 + random.randint(-20, 20),
                                     int(h * 0.3))
            HumanSleep.sleep('normal')

    @staticmethod
    def maybe_fast_scroll(device, probability=0.08):
        """
        小概率快速划过视频（模拟真人快速浏览不感兴趣的内容）
        """
        if random.random() < probability:
            logger.info("模拟行为: 快速划过视频")
            w, h = device.window_size()
            HumanGesture.human_swipe(device,
                                     w // 2 + random.randint(-15, 15),
                                     int(h * 0.75),
                                     w // 2 + random.randint(-15, 15),
                                     int(h * 0.25),
                                     duration=random.uniform(0.15, 0.25))
            return True
        return False

    @staticmethod
    def maybe_browse_home_feed(device, probability=0.03):
        """
        小概率切到首页推荐流浏览（模拟真人非任务行为）
        增加状态确认：返回后验证是否到达首页，避免误点
        """
        if random.random() < probability:
            logger.info("模拟行为: 切到首页推荐流浏览")
            try:
                device.press("back")
                HumanSleep.sleep('normal')
                # 点击首页 tab，并确认点击成功
                home_tab = device.xpath('//*[@text="首页"]')
                if home_tab.exists(timeout=2):
                    home_tab.click()
                    HumanSleep.sleep('page_load')
                    # 二次确认：首页 tab 是否处于选中态
                    if not device.xpath('//*[@text="首页" and @selected="true"]').exists(timeout=1):
                        logger.debug("首页 tab 未选中，放弃推荐流浏览")
                        return
                    # 随机刷 2-4 个推荐视频
                    for _ in range(random.randint(2, 4)):
                        w, h = device.window_size()
                        HumanGesture.human_swipe(device,
                                                 w // 2 + random.randint(-20, 20),
                                                 int(h * 0.7),
                                                 w // 2 + random.randint(-20, 20),
                                                 int(h * 0.3))
                        HumanSleep.sleep('video_stay')
                    logger.info("推荐流浏览完毕，返回搜索")
            except Exception as e:
                logger.debug(f"浏览首页推荐流异常: {e}")

    @staticmethod
    def maybe_pause_and_think(probability=0.04):
        """
        小概率长停顿（模拟真人思考/走神/回复消息）
        """
        if random.random() < probability:
            pause_time = random.uniform(5.0, 15.0)
            logger.info(f"模拟行为: 停顿思考 {pause_time:.1f}s")
            time.sleep(pause_time)
            return True
        return False


class AntiDetectionEngine:
    """
    防风控引擎总调度器
    整合所有防风控组件，提供统一接口
    每个任务流实例持有独立引擎，避免多设备共享限额/状态
    """

    def __init__(self, config=None, db_manager=None):
        self.config = config or {}
        self.gesture = HumanGesture()
        self.sleep_mgr = HumanSleep()
        self.probability = InteractionProbability()
        self.daily_limit = DailyLimitManager(config=self.config, db_manager=db_manager)
        self.night_mode = NightModeController(config=self.config)
        self.fingerprint = DeviceFingerprintGuard()
        self.behavior = BehaviorRandomizer()
        logger.info("🛡️ 防风控引擎已初始化")

    def human_swipe(self, device, sx, sy, ex, ey, duration=None):
        """人性化滑动"""
        self.gesture.human_swipe(device, sx, sy, ex, ey, duration)

    def human_swipe_curve(self, device, sx, sy, ex, ey, duration=None):
        """贝塞尔曲线滑动"""
        self.gesture.human_swipe_with_curve(device, sx, sy, ex, ey, duration)

    def human_click(self, device, x, y, jitter_range=8):
        """人性化点击"""
        self.gesture.human_click(device, x, y, jitter_range)

    def human_double_click(self, device, x, y, jitter_range=10):
        """人性化双击"""
        self.gesture.human_double_click(device, x, y, jitter_range)

    def sleep(self, sleep_type='normal', custom_range=None):
        """人性化等待"""
        return self.sleep_mgr.sleep(sleep_type, custom_range)

    def should_interact(self, action_type):
        """概率决策"""
        return self.probability.should_interact(action_type, self.config)

    def can_do(self, action_type):
        """限额检查"""
        return self.daily_limit.can_do(action_type)

    def record_action(self, action_type):
        """记录已执行互动，供限额统计"""
        self.daily_limit.record_action(action_type)

    def check_night_mode(self, check_callback=None):
        """夜间模式检查"""
        if self.night_mode.is_night_time():
            self.night_mode.wait_until_morning(check_callback)

    def cleanup_device(self, device):
        """清理设备痕迹，并记录设备指纹"""
        self.fingerprint.cleanup_u2_traces(device)
        fp = self.fingerprint.get_device_fingerprint_status(device)
        if fp:
            logger.info(f"📱 设备指纹: {fp}")

    def random_behavior(self, device):
        """随机行为模拟"""
        self.behavior.maybe_rewind(device)
        self.behavior.maybe_fast_scroll(device)
        self.behavior.maybe_pause_and_think()

    def check_network_status(self, device):
        """检测设备网络状态（4G 场景下感知信号强度与连接类型）"""
        return NetworkStatusChecker.check(device)
