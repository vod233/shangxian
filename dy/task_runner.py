import time
import re
import random
import logging
import datetime
import os
import yaml

from .main_controller import ScoutTaskRunner
from .actions.navigation import (
    EnterSearchAction, ApplyFiltersAction,
    EnterFirstVideoAction, SwipeNextVideoAction, ResetToSearchAction
)
from .actions.interaction import (
    DoubleClickLikeAction, FollowAuthorAction, GetCurrentVideoLinkAction
)
from .actions.commenting import (
    PostCommentAction, OpenCommentSectionAction, ProcessCommentSectionAction, CommentLeadPmAction
)
from .actions.locators import TikTokLocators as L
from .ai_reply_agent import DYReplyAgent
from .db_manager import DBManager
from .anti_detection import AntiDetectionEngine, BehaviorRandomizer, HumanSleep

logger = logging.getLogger(__name__)


def _now_str():
    """当前时间字符串，用于 action_event 时间戳"""
    return datetime.datetime.now().strftime("%H:%M:%S")

class TikTokTaskFlow:
    """
    具体的业务任务流
    将原子动作串联起来，形成如"搜索 -> 筛选 -> 刷视频 -> 互动"的完整逻辑
    """
    def __init__(self, serial=None, config_path=None, status_reporter=None):
        self.runner = ScoutTaskRunner(serial=serial, config_path=config_path)
        self.config = self.runner.config
        # 保存配置文件路径，供 start() 时重新读取最新配置（解决前端保存后任务仍用旧关键词的问题）
        self.config_path = config_path
        self.db = DBManager()
        self.reply_agent = DYReplyAgent(self.config)

        # 初始化防风控引擎
        self.anti = AntiDetectionEngine(config=self.config, db_manager=self.db)

        # 状态记录，用于防重防卡死
        self.last_share_token = None
        self.last_description = None
        self.current_keyword = None
        # 视频计数器（用于前端详情展示第几个关键词的第几个视频）
        self.keyword_index = 0
        self.video_index = 0

        # 停止标识
        self.is_stopped = False
        self.is_paused = False

        # 状态上报回调：由后端注入，用于首页手机框动态展示
        # 签名：reporter(current_action=None, executed_action=None)
        self.status_reporter = status_reporter

    def _report(self, current_action=None, executed_action=None):
        """向首页上报当前动作与已执行动作；失败不影响任务流。"""
        try:
            if self.status_reporter:
                self.status_reporter(current_action=current_action, executed_action=executed_action)
        except Exception as exc:
            logger.debug(f"上报动作状态失败: {exc}")

    def _interaction_enabled(self, key, default=True):
        return bool(self.config.get('interaction', {}).get(key, default))

    def _probability_decision_enabled(self):
        """是否启用概率决策（防风控）。关闭时每个视频都执行所有已开启功能。"""
        return bool(self.config.get('anti_detection', {}).get('interaction_probability', {}).get('enabled', False))

    def _probability_allows(self, action_type):
        """概率决策门控：开关关闭时总是 True（每个视频都执行）；开启时按概率。"""
        if not self._probability_decision_enabled():
            return True
        return self.anti.should_interact(action_type)

    def stop(self):
        """通知任务流结束执行"""
        self.is_stopped = True
        logger.info("收到结束指令，准备退出任务流...")

    def pause(self):
        """通知任务流暂停"""
        self.is_paused = True
        logger.info("收到暂停指令，任务挂起...")

    def resume(self):
        """通知任务流继续"""
        self.is_paused = False
        logger.info("收到继续指令，任务恢复执行...")

    def _interruptible_sleep(self, seconds):
        """可被暂停和停止打断的休眠"""
        slept = 0
        while slept < seconds:
            self._check_stop()
            time.sleep(0.5)
            slept += 0.5

    def _check_stop(self):
        """检查是否收到了结束或暂停指令"""
        # 如果处于暂停状态，就在这里循环等待，直到取消暂停或直接结束
        while self.is_paused:
            if self.is_stopped:
                break
            time.sleep(1)

        if self.is_stopped:
            logger.info("检测到结束指令，中断当前执行！")
            raise InterruptedError("用户手动结束了任务")

    def _dismiss_video_context_menu_if_present(self):
        """关闭抖音视频长按菜单，避免误触后后续动作点在菜单上。"""
        menu_markers = ("不感兴趣", "倍速", "清屏播放", "识别图片", "添加至稍后再看")
        try:
            ui_xml = self._dump_ui()
            has_menu = any(marker in ui_xml for marker in menu_markers) if ui_xml else any(
                self.runner.device(text=marker).exists(timeout=0.4) for marker in menu_markers
            )
            if has_menu:
                logger.warning("检测到抖音视频长按菜单，执行返回关闭")
                width, height = self.runner.device.window_size()
                try:
                    self.anti.human_click(self.runner.device, int(width * 0.5), int(height * 0.12), jitter_range=4)
                    self._interruptible_sleep(0.4)
                except Exception:
                    pass
                ui_xml_after = self._dump_ui()
                if any(marker in ui_xml_after for marker in menu_markers):
                    self.runner.device.press("back")
                    self._interruptible_sleep(0.5)
                return True
        except Exception as e:
            logger.debug(f"检测/关闭视频长按菜单失败: {e}")
        return False

    def _selected_feature_chain_enabled(self):
        """当前是否启用了会连续改变页面状态的功能链路。"""
        keys = (
            "enable_like",
            "enable_author_follow",
            "enable_video_comment",
            "enable_comment_lead",
            "enable_comment_lead_pm",
        )
        return any(self._interaction_enabled(key, False) for key in keys)

    def _xpath_exists(self, xpath, timeout=0.1):
        try:
            return self.runner.device.xpath(xpath).exists(timeout=timeout)
        except TypeError:
            try:
                return bool(self.runner.device.xpath(xpath).exists)
            except Exception:
                return False
        except Exception:
            return False

    def _resource_exists(self, resource_id, timeout=0.1):
        try:
            return self.runner.device(resourceId=resource_id).exists(timeout=timeout)
        except TypeError:
            try:
                return bool(self.runner.device(resourceId=resource_id).exists)
            except Exception:
                return False
        except Exception:
            return False

    def _dump_ui(self):
        try:
            return self.runner.device.dump_hierarchy(compressed=True) or ""
        except Exception as exc:
            logger.debug(f"dump UI 失败: {exc}")
            return ""

    def _is_video_page_ready(self, ui_xml=None):
        """确认当前是抖音全屏视频页，避免在其他页面继续坐标点击。"""
        try:
            if ui_xml is None:
                ui_xml = self._dump_ui()
            if ui_xml:
                # FIX-B: 原代码用 "分享" in ui_xml and "按钮" in ui_xml 字符串子串搜索，
                # 任意位置的"分享"和"按钮"字符都会命中（假阳性）。
                # 改为对 content-desc 属性做正则匹配，要求同一属性同时包含目标关键词。
                features = {
                    "share": bool(re.search(r'content-desc="[^"]*分享[^"]*按钮[^"]*"', ui_xml)),
                    "comment": bool(re.search(r'content-desc="[^"]*评论[^"]*按钮[^"]*"', ui_xml)),
                    "bottom_nav": all(label in ui_xml for label in ("首页", "消息", "我")),
                    "video_container": "视频" in ui_xml,
                }
                score = sum(1 for present in features.values() if present)
                logger.debug(f"视频页特征: {features}, score={score}")
                return score >= 3

            features = {
                "share": self._xpath_exists(L.SHARE_BTN_DYNAMIC, timeout=0.5),
                "comment": self._xpath_exists(L.COMMENT_BTN_DYNAMIC, timeout=0.5),
                "bottom_nav": any(
                    self.runner.device(descriptionContains=label).exists(timeout=0.2)
                    for label in ("首页", "朋友", "消息", "我")
                ),
                "video_container": self.runner.device(description="视频").exists(timeout=0.2),
            }
            score = sum(1 for present in features.values() if present)
            logger.debug(f"视频页特征: {features}, score={score}")
            return score >= 3
        except Exception as exc:
            logger.debug(f"识别视频页失败: {exc}")
        return False

    def _detect_page_state(self):
        """返回当前页面的粗粒度状态，用于动作前后日志和恢复决策。"""
        device = self.runner.device
        try:
            ui_xml = self._dump_ui()
            if ui_xml:
                if any(marker in ui_xml for marker in ("不感兴趣", "倍速", "清屏播放", "识别图片", "添加至稍后再看")):
                    return "context_menu"

                if L.SHARE_PANEL_CONTAINER in ui_xml or "复制链接" in ui_xml or "分享链接" in ui_xml:
                    return "share_panel"

                if L.COMMENT_LIST_CONTAINER in ui_xml or L.COMMENT_CARD_CONTAINER_ID in ui_xml or "暂时没有更多了" in ui_xml:
                    return "comment_panel"

                if re.search(r'class="android\.widget\.EditText"[^>]*focused="true"', ui_xml):
                    return "input_or_chat"
                # FIX-03: 键盘已弹出但 EditText 失焦时，focused=true 检测会漏判。
                # 增加可见 EditText 兜底检测，避免误判为 video_page 导致键盘残留。
                if re.search(r'class="android\.widget\.EditText"[^>]*visible="true"', ui_xml):
                    return "input_or_chat"

                if any(marker in ui_xml for marker in ("分享名片", "发私信", "设置备注", "特别关注", "取消关注", "不让他(她)看")):
                    return "profile_sheet"

                if self._is_video_page_ready(ui_xml):
                    return "video_page"

                if any(marker in ui_xml for marker in ("粉丝", "获赞", "作品")):
                    return "profile_page"

                if "首页" in ui_xml or "搜索" in ui_xml:
                    return "home_or_search"

            menu_markers = ("不感兴趣", "倍速", "清屏播放", "识别图片", "添加至稍后再看")
            if any(device(text=marker).exists(timeout=0.3) for marker in menu_markers):
                return "context_menu"

            if self._resource_exists(L.SHARE_PANEL_CONTAINER) or self._xpath_exists(L.COPY_LINK_BTN):
                return "share_panel"

            if self._resource_exists(L.COMMENT_LIST_CONTAINER) or self._resource_exists(L.COMMENT_CARD_CONTAINER_ID) or self._xpath_exists(L.COMMENT_NO_MORE_TEXT):
                return "comment_panel"

            if self._xpath_exists(L.COMMENT_EDIT_TEXT_XPATH):
                return "input_or_chat"

            profile_sheet_markers = ("分享名片", "发私信", "设置备注", "特别关注", "取消关注", "不让他(她)看")
            if any(device(text=marker).exists(timeout=0.2) for marker in profile_sheet_markers):
                return "profile_sheet"

            if self._is_video_page_ready():
                return "video_page"

            profile_markers = ("粉丝", "获赞", "作品", "关注")
            if any(device(text=marker).exists(timeout=0.1) for marker in profile_markers):
                return "profile_page"

            if device(text=L.HOME_TAB_TEXT).exists(timeout=0.1) or self._xpath_exists(L.SEARCH_BTN_DESC):
                return "home_or_search"
        except Exception as exc:
            logger.debug(f"检测页面状态失败: {exc}")
        return "unknown"

    def _recover_to_video_page(self, reason, max_back=5):
        """
        受控恢复到全屏视频页。
        不做盲目连续返回；每次 back 后都重新确认状态。
        """
        for attempt in range(max_back + 1):
            self._check_stop()
            state = self._detect_page_state()
            logger.info(f"状态检查[{reason}] 第 {attempt + 1}/{max_back + 1} 次: {state}")
            if state == "video_page":
                return True

            if attempt >= max_back:
                logger.warning(f"恢复视频页失败[{reason}]，最终状态: {state}")
                return False

            logger.info(f"尝试关闭/返回当前状态[{state}] -> 视频页")
            try:
                if state == "context_menu":
                    self._dismiss_video_context_menu_if_present()
                else:
                    self.runner.device.press("back")
            except Exception as exc:
                logger.warning(f"执行返回键失败[{reason}]: {exc}")
                return False
            self._interruptible_sleep(0.8)

        return False

    def _run_feature_safely(self, feature_name, callback):
        """
        为执行功能选择中的每个动作建立硬边界。
        动作前必须在视频页，动作后必须恢复到视频页。
        """
        before_state = self._detect_page_state()
        logger.info(f"功能前状态[{feature_name}]: {before_state}")
        if not self._recover_to_video_page(f"{feature_name}-执行前"):
            logger.warning(f"跳过功能[{feature_name}]：执行前无法确认视频页")
            return False, None

        result = None
        try:
            result = callback()
            self._dismiss_video_context_menu_if_present()
        except InterruptedError:
            raise
        except Exception as exc:
            logger.error(f"功能[{feature_name}]执行异常: {exc}")
            result = None

        after_state = self._detect_page_state()
        logger.info(f"功能后状态[{feature_name}]: {after_state}")
        recovered = self._recover_to_video_page(f"{feature_name}-执行后")
        if not recovered:
            logger.warning(f"功能[{feature_name}]后恢复失败，跳过当前视频剩余功能")
            return False, result
        return True, result

    def _run_comment_lead_safely(self, video_title, keyword, enable_lead_pm=False):
        """评论区截流 + 楼中楼私信评论者（B.4 + B.5）。
        当 enable_lead_pm=True 时，B.4 发现意向评论后不关闭评论区，直接在评论区打开状态下执行 B.5。
        返回 dict: {"recovered": bool, "lead_reply_sent": bool, "lead_pm_sent": bool, "lead_pm_reason": str}
        """
        feature_name = "评论区AI截流/楼中楼回复"
        before_state = self._detect_page_state()
        logger.info(f"功能前状态[{feature_name}]: {before_state}")
        if not self._recover_to_video_page(f"{feature_name}-执行前"):
            logger.warning(f"跳过功能[{feature_name}]：执行前无法确认视频页")
            return {"recovered": False, "lead_reply_sent": False, "lead_pm_sent": False, "lead_pm_reason": "pre_recover_failed"}

        lead_reply_sent = False
        lead_pm_sent = False
        lead_pm_reason = "skipped"
        comment_section_open = False  # 跟踪评论区是否仍打开（B.5 需要在此状态下执行）
        pm_executed = False  # FIX-02: 标记 B.5 是否执行过，决定关闭评论区的方式
        action_instance = None
        try:
            opened = self.runner.run_action(OpenCommentSectionAction)
            self._dismiss_video_context_menu_if_present()
            opened_state = self._detect_page_state()
            logger.info(f"功能中状态[打开评论区后]: {opened_state}")
            if not opened or opened_state not in ("comment_panel", "input_or_chat"):
                # 第二层兜底：_detect_page_state 可能因 rlp 资源ID 变动而误判，
                # 但 OpenCommentSectionAction 已确认评论区打开。直接检查关键容器。
                if opened and (self._resource_exists(L.COMMENT_CARD_CONTAINER_ID, timeout=0.5)
                               or self._resource_exists(L.COMMENT_LIST_CONTAINER, timeout=0.5)):
                    logger.info("评论区已打开（直接容器检测通过，忽略 _detect_page_state 误判）")
                else:
                    logger.warning(f"评论区未可靠打开，当前状态: {opened_state}")
                    recovered = self._recover_to_video_page(f"{feature_name}-打开失败后")
                    return {"recovered": recovered, "lead_reply_sent": False, "lead_pm_sent": False, "lead_pm_reason": "open_failed"}

            self._check_stop()
            # 手动实例化 ProcessCommentSectionAction，以便读取 lead_comment_node 供 B.5 使用
            action_instance = ProcessCommentSectionAction(
                u2_device=self.runner.device,
                app_manager=self.runner.app_mgr,
                config=self.config,
                video_title=video_title,
                keyword=keyword,
                check_stop_callback=self._check_stop,
                keep_open_after_lead=enable_lead_pm,  # B.5 启用时不关闭评论区
            )
            action_instance.perform()
            # 读取意向评论节点信息
            lead_comment_node = getattr(action_instance, 'lead_comment_node', None)
            lead_reply_sent = bool(getattr(action_instance, 'lead_reply_sent', False))
            # FIX-05: 同时读取意向评论文本，供 B.5 重新定位节点
            lead_comment_text = getattr(action_instance, 'lead_comment_text', '') or ''

            if enable_lead_pm and lead_comment_node is not None:
                comment_section_open = True  # keep_open_after_lead=True 时评论区仍打开
            if lead_comment_node is not None:
                logger.info("B.4 已保存意向评论节点，可供 B.5 私信评论者使用")

            # B.5 楼中楼私信评论者（在评论区仍打开的状态下执行）
            if enable_lead_pm and lead_reply_sent and lead_comment_node is not None:
                logger.info("B.5 开始执行楼中楼私信评论者（评论区仍打开状态）")
                pm_action = CommentLeadPmAction(
                    u2_device=self.runner.device,
                    app_manager=self.runner.app_mgr,
                    config=self.config,
                    lead_comment_node=lead_comment_node,
                    lead_comment_text=lead_comment_text,  # FIX-05: 传文本以便重新定位节点
                )
                pm_executed = True  # FIX-02: 标记 B.5 已执行
                try:
                    pm_result = pm_action.perform()
                except Exception as exc:
                    logger.error(f"B.5 执行异常: {exc}")
                    pm_result = {"pm_sent": False, "reason": "exception"}
                if isinstance(pm_result, dict):
                    lead_pm_sent = pm_result.get("pm_sent", False)
                    lead_pm_reason = pm_result.get("reason", "unknown")
                comment_section_open = True  # B.5 可能修改了页面状态，需要关闭评论区
            elif enable_lead_pm and not lead_reply_sent:
                lead_pm_reason = "lead_reply_not_sent"
        except InterruptedError:
            raise
        except Exception as exc:
            logger.error(f"功能[{feature_name}]执行异常: {exc}")

        # FIX-02: B.5 执行后页面在评论者私信聊天页，调用 _close_comment_section 路径不匹配，
        # 改为直接用 _recover_to_video_page 由状态机统一处理 chat→profile→comment_panel→video 多层返回。
        # 仅当未执行 B.5 且评论区仍打开时，才用 _close_comment_section 关闭评论区。
        if comment_section_open:
            if pm_executed:
                logger.info("B.5 已执行，页面可能在聊天页，用状态机恢复到视频页")
                self._recover_to_video_page(f"{feature_name}-B.5私信后恢复", max_back=6)
            else:
                try:
                    if action_instance is not None:
                        action_instance._close_comment_section()
                    else:
                        self._recover_to_video_page(f"{feature_name}-关闭评论区")
                except Exception as exc:
                    logger.warning(f"关闭评论区异常: {exc}")

        after_state = self._detect_page_state()
        logger.info(f"功能后状态[{feature_name}]: {after_state}")
        recovered = self._recover_to_video_page(f"{feature_name}-执行后")
        if not recovered:
            logger.warning(f"功能[{feature_name}]后恢复失败，跳过当前视频剩余功能")
        return {"recovered": recovered, "lead_reply_sent": lead_reply_sent, "lead_pm_sent": lead_pm_sent, "lead_pm_reason": lead_pm_reason}

    def start(self):
        """开始执行完整的采集与互动任务"""
        logger.info("=== 任务流开始 ===")
        self._report(current_action="正在加载 AI 自动化运营引擎...", executed_action="启动任务")

        # 夜间静默时段检查
        self.anti.check_night_mode(check_callback=self._check_stop)

        # 打印当前已有的统计数据
        stats = self.db.get_daily_stats()
        logger.info(f"📊 今日已处理视频: {stats['videos']} 个 | 点赞: {stats['likes']} 次 | 评论: {stats['comments']} 次 | 关注: {stats['follows']} 人")

        # 检查每日全局上限
        max_daily_videos = self.config.get('crawler', {}).get('max_daily_videos', 100)
        if stats['videos'] >= max_daily_videos:
            logger.info(f"🛑 今日处理视频总数({stats['videos']})已达到设置的最高上限({max_daily_videos})，任务终止！")
            self._report(current_action="已触发策略风控保护，今日作业安全闭环")
            return

        # 检查每日互动限额
        if self.anti.daily_limit.check_all_limits():
            logger.info("🛑 今日所有互动类型均已达到上限，建议休息，任务终止！")
            self._report(current_action="达到当日安全互动阈值，执行风控自适应挂起")
            return

        self._check_stop()
        # 1. 确保抖音处于可用状态
        self.runner.launch_app()
        self._report(current_action="正在配置 AI 专属全域云环境...", executed_action="拉起抖音")

        # 清理设备痕迹
        if self.config.get('anti_detection', {}).get('device_cleanup', {}).get('enabled', True):
            try:
                self.anti.cleanup_device(self.runner.device)
                logger.info("🧹 已清理设备自动化痕迹")
            except Exception as e:
                logger.warning(f"清理设备痕迹失败: {e}")

        # 2. 读取关键词列表
        # 修复：每次任务启动时重新从配置文件读取最新关键词，
        # 而非使用初始化时缓存到内存的旧配置，确保前端保存的关键词能立即生效。
        keywords = self._reload_search_keywords()

        if not keywords:
            logger.error("未在配置中找到 search.keywords，任务无法执行")
            return

        try:
            for keyword in keywords:
                self._check_stop()
                logger.info(f"\n>>> 开始处理关键词: {keyword} <<<")
                self._process_single_keyword(keyword)

            logger.info("所有关键词任务处理完毕！")
            self._report(current_action="目标意向词网检索任务已全部达成")
        except KeyboardInterrupt:
            logger.warning("用户手动停止了任务")
            self._report(current_action="接收到人工指令，作业流安全挂起")
        except Exception as e:
            logger.error(f"任务流执行异常: {e}")
            self._report(current_action="触发自适应风控隔离，系统正在智能重试...")
        finally:
            self.runner.shutdown()

    def _reload_search_keywords(self):
        """从配置文件重新读取最新的搜索关键词列表。
        解决前端保存关键词后，任务实例仍使用初始化时缓存的旧关键词的问题。
        同时同步更新 self.config，使后续 B.1-B.4 等环节也能用到最新配置。
        """
        keywords = []
        config_path = self.config_path
        if config_path and os.path.isfile(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    fresh_config = yaml.safe_load(f) or {}
                search_cfg = fresh_config.get('search', {}) or {}
                keywords = search_cfg.get('keywords', []) or []
                # 兼容旧配置格式
                if not keywords and search_cfg.get('keyword'):
                    keywords = [search_cfg['keyword']]
                # 同步更新内存配置，使后续环节也能用到最新配置
                if keywords:
                    self.config['search'] = search_cfg
                    logger.info(f"已从配置文件重新加载关键词: {keywords}")
            except Exception as exc:
                logger.warning(f"重新读取配置文件失败，使用内存中的旧配置: {exc}")
        # 兜底：使用内存中的旧配置
        if not keywords:
            keywords = self.config.get('search', {}).get('keywords', [])
            if not keywords:
                old_keyword = self.config.get('search', {}).get('keyword')
                if old_keyword:
                    keywords = [old_keyword]
        return keywords

    def _process_single_keyword(self, keyword):
        """处理单个关键词的完整流程"""
        # 重置防重状态
        self.last_share_token = None
        self.last_description = None
        self.current_keyword = keyword
        self.keyword_index += 1
        self.video_index = 0
        self._report(current_action=f"正在检索核心客群意向词：【{keyword}】", executed_action=f"开始关键词：{keyword}")

        # 1. 搜索
        self._check_stop()
        if not self.runner.run_action(EnterSearchAction, keyword):
            logger.warning(f"关键词 '{keyword}' 搜索失败，跳过当前关键词")
            self.runner.run_action(ResetToSearchAction)
            return
        self._report(executed_action=f"搜索关键词：{keyword}")

        # 2. 筛选（固定使用最新发布排序）
        self._check_stop()
        sort_mode = "latest"
        if not self.runner.run_action(ApplyFiltersAction, sort_mode=sort_mode):
            logger.warning("筛选未成功应用，继续使用当前搜索结果")
        self._report(current_action=f"正在根据【{sort_mode}】精确洗量过滤...", executed_action="应用筛选条件")

        # 3. 进入第一个视频
        self._check_stop()
        success = self.runner.run_action(EnterFirstVideoAction)
        if not success:
            logger.warning(f"未能进入关键词 '{keyword}' 的视频流，跳过")
            self.runner.run_action(ResetToSearchAction)
            return
        self._report(current_action="正在检索目标公域流量池...", executed_action="进入视频流")

        self._interruptible_sleep(3)

        # 4. 开始循环刷视频
        self._video_loop()

        # 5. 当前关键词处理完毕，退回到搜索页，准备下一个
        self.runner.run_action(ResetToSearchAction)
        self._report(executed_action=f"完成关键词：{keyword}")

    def _reset_and_reenter_video_flow(self, reason):
        """状态恢复失败时重置当前关键词的视频流，避免单个视频异常终止整个关键词。"""
        if not self.current_keyword:
            return False

        logger.warning(f"尝试重置并重进视频流: {reason}")
        try:
            self.runner.run_action(ResetToSearchAction)
            self._interruptible_sleep(1)
            if not self.runner.run_action(EnterSearchAction, self.current_keyword):
                return False
            sort_mode = "latest"
            self.runner.run_action(ApplyFiltersAction, sort_mode=sort_mode)
            if not self.runner.run_action(EnterFirstVideoAction):
                return False
            self._interruptible_sleep(2)
            return self._recover_to_video_page(f"{reason}-重进后确认", max_back=2)
        except InterruptedError:
            raise
        except Exception as exc:
            logger.warning(f"重置并重进视频流失败[{reason}]: {exc}")
            return False

    def _video_processing_timed_out(self, started_at):
        max_seconds = float(self.config.get('crawler', {}).get('max_seconds_per_video', 90))
        if time.time() - started_at > max_seconds:
            logger.warning(f"当前视频处理超过 {max_seconds:.0f}s，跳过当前视频")
            return True
        return False

    def _video_loop(self):
        """核心的边刷边互动循环"""
        video_count = 0
        max_videos = self.config.get('crawler', {}).get('max_videos_per_keyword', 10) # 默认刷10个测试
        max_daily_videos = self.config.get('crawler', {}).get('max_daily_videos', 100)
        recovery_failures = 0

        while video_count < max_videos:
            self._check_stop()
            video_started_at = time.time()

            # 每次刷视频前检查一次全局今日上限
            stats = self.db.get_daily_stats()
            if stats['videos'] >= max_daily_videos:
                logger.info(f"🛑 今日处理视频总数({stats['videos']})已达到最高上限({max_daily_videos})，即将退出循环！")
                self.stop() # 触发自动结束
                break

            video_count += 1
            logger.info(f"\n--- 正在处理第 {video_count}/{max_videos} 个视频 ---")
            self._report(current_action=f"高潜线索漏斗筛选中：[{video_count}/{max_videos}]")
            self._dismiss_video_context_menu_if_present()

            # A. 提取信息与防重卡死检测
            self._check_stop()
            if not self._recover_to_video_page("提取视频信息前", max_back=3):
                recovery_failures += 1
                if recovery_failures >= 3 or not self._reset_and_reenter_video_flow("提取视频信息前恢复失败"):
                    logger.warning("当前不在视频页，连续恢复失败，停止当前关键词的视频循环")
                    break
                continue

            stable, link_info = self._run_feature_safely(
                "提取视频信息/分享链接",
                lambda: self.runner.run_action(GetCurrentVideoLinkAction),
            )
            self._report(current_action="AI 正在多维分析目标客群画像...", executed_action="提取视频信息")
            if not stable:
                recovery_failures += 1
                if recovery_failures >= 3 or not self._reset_and_reenter_video_flow("提取视频信息后恢复失败"):
                    logger.warning("提取视频信息后连续恢复失败，停止当前关键词的视频循环")
                    break
                continue
            recovery_failures = 0

            if link_info:
                url, share_token, description = link_info

                # 防重判断：如果连续刷到相同的视频（或已经滑到底了）
                is_duplicate = False
                if share_token and self.last_share_token and share_token == self.last_share_token:
                    logger.warning(f"检测到视频重复 (token一致)，可能已滑到底部")
                    is_duplicate = True
                elif description and self.last_description and description == self.last_description:
                    logger.warning(f"检测到视频重复 (文案一致)，可能已滑到底部")
                    is_duplicate = True

                if is_duplicate:
                    logger.info("结束当前关键词的视频循环")
                    break

                self.last_share_token = share_token
                self.last_description = description

                # B. 执行视频级互动
                video_id = share_token if share_token else str(hash(description))

                # 提取视频标题用于AI生成评论
                video_title = self._extract_title_from_description(description)

                # B.0 记录视频入库，如果已处理过则跳过
                is_new = self.db.record_video(video_id, self.current_keyword, url, note_title=video_title)
                if not is_new:
                    logger.info("⏭️ 视频今日已处理过，跳过互动环节")
                    self.db.update_video_detail(
                        video_id,
                        keyword_index=self.keyword_index,
                        process_status="skipped",
                        skip_reason="duplicate",
                        action_event={"t": _now_str(), "phase": "B.0", "msg": "视频今日已处理过"},
                    )
                else:
                    self.video_index += 1
                    logger.info("🎬 开始对新视频执行互动...")
                    logger.info(f"📝 当前视频标题: {video_title}")
                    skip_remaining_features = False
                    # 初始化本视频详细记录
                    self.db.update_video_detail(
                        video_id,
                        keyword_index=self.keyword_index,
                        video_index=self.video_index,
                        process_status="processing",
                        action_event={"t": _now_str(), "phase": "B.0", "msg": f"开始处理: {video_title}"},
                    )

                    # B.1 点赞（功能开关为确定性指令，仍保留每日限额与概率决策）
                    if self._interaction_enabled("enable_like"):
                        self._check_stop()
                        if self.anti.can_do('like') and self._probability_allows('like'):
                            self._report(current_action="执行 AI 智能算法加权互动")
                            stable, liked = self._run_feature_safely(
                                "点赞",
                                lambda: self.runner.run_action(DoubleClickLikeAction),
                            )
                            if liked:
                                self.db.update_interaction(video_id, "like")
                                self._report(executed_action="点赞")
                                self.db.update_video_detail(video_id, action_event={"t": _now_str(), "phase": "B.1", "msg": "点赞成功"})
                            # FIX-11: 仅"页面不稳定"(stable=False) 才级联跳过后续功能；
                            # "功能执行失败"(liked=False) 但页面稳定时不阻断 B.2/B.3/B.4。
                            if not stable:
                                skip_remaining_features = True
                                self.db.update_video_detail(video_id, action_event={"t": _now_str(), "phase": "B.1", "msg": "点赞失败(页面不稳定)"})
                            elif not liked:
                                logger.info("点赞未成功但页面稳定，继续执行后续功能")
                                self.db.update_video_detail(video_id, action_event={"t": _now_str(), "phase": "B.1", "msg": "点赞未成功(页面稳定,不阻断)"})
                        else:
                            logger.info("限额/概率决策: 跳过点赞")
                            self.db.update_video_detail(video_id, action_event={"t": _now_str(), "phase": "B.1", "msg": "跳过点赞(限额/概率)"})
                        self._interruptible_sleep(random.uniform(0.8, 2.0))
                    else:
                        logger.info("已关闭功能: 点赞，跳过")
                        self.db.update_video_detail(video_id, action_event={"t": _now_str(), "phase": "B.1", "msg": "功能关闭:点赞"})

                    # B.2 作者主页链路：粉丝数判断 -> 关注 -> 私信（功能开关为确定性指令，仍保留每日限额）
                    if self._video_processing_timed_out(video_started_at):
                        skip_remaining_features = True
                    if skip_remaining_features:
                        logger.warning("页面恢复失败，跳过当前视频剩余功能")
                        self.db.update_video_detail(video_id, action_event={"t": _now_str(), "phase": "B.2", "msg": "跳过(页面恢复失败)"})
                    elif self._interaction_enabled("enable_author_follow"):
                        self._check_stop()
                        if self.anti.can_do('follow') and self._probability_allows('follow'):
                            private_message_allowed = (
                                self._interaction_enabled("enable_private_message", False)
                                and self.anti.can_do('private_message')
                                and self._probability_allows('private_message')
                            )
                            self._report(current_action="锁定高潜客户，执行 AI 私域线索破冰")
                            stable, follow_result = self._run_feature_safely(
                                "作者主页/关注/私信",
                                lambda: self.runner.run_action(
                                    FollowAuthorAction,
                                    private_message_allowed=private_message_allowed,
                                ),
                            )
                            if isinstance(follow_result, dict):
                                if follow_result.get("followed"):
                                    self.db.update_interaction(video_id, "follow")
                                    self._report(executed_action="关注作者")
                                    self.db.update_video_detail(video_id, action_event={"t": _now_str(), "phase": "B.2", "msg": "关注成功"})
                                if follow_result.get("private_message_sent"):
                                    self.db.update_interaction(video_id, "private_message")
                                    self._report(executed_action="发送私信")
                                    self.db.update_video_detail(video_id, pm_sent=1, action_event={"t": _now_str(), "phase": "B.2", "msg": "私信发送成功"})
                                # 记录粉丝数（如返回）
                                follower_count = follow_result.get("follower_count") or ""
                                if follower_count:
                                    self.db.update_video_detail(video_id, follower_count=str(follower_count))
                            elif follow_result:
                                self.db.update_interaction(video_id, "follow")
                                self._report(executed_action="关注作者")
                                self.db.update_video_detail(video_id, action_event={"t": _now_str(), "phase": "B.2", "msg": "关注成功(无私信)"})
                            if not stable:
                                skip_remaining_features = True
                                self.db.update_video_detail(video_id, action_event={"t": _now_str(), "phase": "B.2", "msg": "关注/私信失败(页面不稳定)"})
                        else:
                            logger.info("限额/概率决策: 跳过关注/私信")
                            self.db.update_video_detail(video_id, action_event={"t": _now_str(), "phase": "B.2", "msg": "跳过关注/私信(限额/概率)"})
                        self._interruptible_sleep(random.uniform(1.0, 2.5))
                    else:
                        logger.info("已关闭功能: 作者主页/关注/私信，跳过")
                        self.db.update_video_detail(video_id, action_event={"t": _now_str(), "phase": "B.2", "msg": "功能关闭:关注/私信"})

                    # B.3 发送视频评论（功能开关为确定性指令，仍保留每日限额）
                    if self._video_processing_timed_out(video_started_at):
                        skip_remaining_features = True
                    if skip_remaining_features:
                        logger.warning("页面恢复失败，跳过当前视频剩余功能")
                        self.db.update_video_detail(video_id, action_event={"t": _now_str(), "phase": "B.3", "msg": "跳过(页面恢复失败)"})
                    elif self._interaction_enabled("enable_video_comment"):
                        self._check_stop()
                        if self.anti.can_do('comment') and self._probability_allows('comment'):
                            self._report(current_action="AI 正在根据垂直行业知识库生成精准评论")
                            comment_text = self.reply_agent.generate_reply(
                                title=video_title,
                                keyword=self.current_keyword or ""
                            ) or ""

                            if comment_text:
                                if self.reply_agent.is_enabled():
                                    logger.info(f"🤖 AI 生成回复: {comment_text}")
                                self.db.save_ai_reply(
                                    video_id,
                                    note_title=video_title,
                                    ai_reply=comment_text,
                                )
                                stable, commented = self._run_feature_safely(
                                    "AI视频评论",
                                    lambda: self.runner.run_action(PostCommentAction, comment_text),
                                )
                                if commented:
                                    self.db.update_interaction(video_id, "comment")
                                    self._report(executed_action="发布视频评论")
                                    self.db.update_video_detail(video_id, action_event={"t": _now_str(), "phase": "B.3", "msg": f"评论已发布: {comment_text[:30]}"})
                                if not stable:
                                    skip_remaining_features = True
                                    self.db.update_video_detail(video_id, action_event={"t": _now_str(), "phase": "B.3", "msg": "评论失败(页面不稳定)"})
                            else:
                                self.db.save_ai_reply(
                                    video_id,
                                    note_title=video_title,
                                    ai_reply="",
                                )
                                logger.info("未生成可发布的回复，跳过评论环节。")
                                self.db.update_video_detail(video_id, action_event={"t": _now_str(), "phase": "B.3", "msg": "AI未生成评论"})
                        else:
                            logger.info("限额/概率决策: 跳过评论")
                            self.db.update_video_detail(video_id, action_event={"t": _now_str(), "phase": "B.3", "msg": "跳过评论(限额/概率)"})
                    else:
                        logger.info("已关闭功能: AI 视频评论，跳过")
                        self.db.update_video_detail(video_id, action_event={"t": _now_str(), "phase": "B.3", "msg": "功能关闭:视频评论"})

                    # FIX-08: V→C 之间增加间隔延迟，让 UI 充分 settle，避免 B.4 打开评论区时键盘残留或 UI 未就绪。
                    # 与 B.1 后的 0.8~2.0s、B.2 后的 1.0~2.5s 保持一致。
                    self._interruptible_sleep(random.uniform(0.8, 2.0))

                    # B.4 处理评论区 + B.5 楼中楼私信评论者（B.5 合并到 _run_comment_lead_safely 内部执行）
                    lead_result = None
                    if self._video_processing_timed_out(video_started_at):
                        skip_remaining_features = True
                    if skip_remaining_features:
                        logger.warning("页面恢复失败，跳过当前视频剩余功能")
                        self.db.update_video_detail(video_id, action_event={"t": _now_str(), "phase": "B.4", "msg": "跳过(页面恢复失败)"})
                    elif self._interaction_enabled("enable_comment_lead"):
                        self._check_stop()
                        # FIX-04 + FIX-13: B.4 与 B.3 共享 comment 配额，B.4 前必须检查配额，
                        # 避免配额耗尽后 B.4 仍执行楼中楼回复导致超限。
                        if self.anti.can_do('comment') and self._probability_allows('comment_lead'):
                            self._report(current_action="正在对评论区意向线索进行精准拦截")
                            # B.5 是否启用（影响 B.4 是否关闭评论区）
                            enable_lead_pm = self._interaction_enabled("enable_comment_lead_pm")
                            # B.5 限额/概率检查（在传入 _run_comment_lead_safely 之前做，避免不必要地保留评论区打开）
                            if enable_lead_pm:
                                if not self.anti.can_do('lead_pm'):
                                    enable_lead_pm = False
                                    logger.info("B.5 跳过：lead_pm 限额已满")
                                    self.db.update_video_detail(video_id, action_event={"t": _now_str(), "phase": "B.5", "msg": "跳过(lead_pm限额)"})
                                elif not self._probability_allows('lead_pm'):
                                    enable_lead_pm = False
                                    logger.info("B.5 跳过：概率决策")
                                    self.db.update_video_detail(video_id, action_event={"t": _now_str(), "phase": "B.5", "msg": "跳过(概率)"})
                            lead_result = self._run_comment_lead_safely(video_title, self.current_keyword or "", enable_lead_pm=enable_lead_pm)
                            if not lead_result.get("recovered"):
                                skip_remaining_features = True
                                self.db.update_video_detail(video_id, action_event={"t": _now_str(), "phase": "B.4", "msg": "评论区截流失败"})
                            else:
                                self._report(executed_action="评论区AI截流")
                                if lead_result.get("lead_reply_sent"):
                                    self.db.update_interaction(video_id, "comment")
                                    self.db.update_video_detail(video_id, lead_sent=1, action_event={"t": _now_str(), "phase": "B.4", "msg": "楼中楼回复已发送"})
                                else:
                                    self.db.update_video_detail(video_id, action_event={"t": _now_str(), "phase": "B.4", "msg": "评论区截流完成(未发送回复)"})
                            # 记录 B.5 结果
                            if lead_result.get("lead_pm_sent"):
                                self.db.update_interaction(video_id, "lead_pm")
                                self._report(executed_action="楼中楼私信评论者")
                                self.db.update_video_detail(video_id, lead_pm_sent=1, action_event={"t": _now_str(), "phase": "B.5", "msg": "楼中楼私信已发送"})
                            else:
                                reason = lead_result.get("lead_pm_reason", "unknown")
                                # lead_reply_not_sent / skipped 是正常跳过（未发现意向评论或未启用 B.5），不算失败
                                if reason in ("skipped", "lead_reply_not_sent"):
                                    logger.info(f"B.5 跳过: {reason}")
                                    self.db.update_video_detail(video_id, action_event={"t": _now_str(), "phase": "B.5", "msg": f"跳过({reason})"})
                                else:
                                    logger.warning(f"B.5 楼中楼私信失败: {reason}")
                                    self.db.update_video_detail(video_id, action_event={"t": _now_str(), "phase": "B.5", "msg": f"私信失败({reason})"})
                        else:
                            logger.info("限额/概率决策: 跳过评论区截流")
                            self.db.update_video_detail(video_id, action_event={"t": _now_str(), "phase": "B.4", "msg": "跳过截流(comment限额/概率)"})
                    else:
                        logger.info("已关闭功能: 评论区 AI 截流/楼中楼回复，跳过")
                        self.db.update_video_detail(video_id, action_event={"t": _now_str(), "phase": "B.4", "msg": "功能关闭:评论区截流"})

                    # 标记本视频处理完成
                    final_status = "error" if skip_remaining_features else "completed"
                    self.db.update_video_detail(video_id, process_status=final_status)

            else:
                logger.warning("无法提取当前视频信息，跳过互动环节")

            # 打印实时进度
            stats = self.db.get_daily_stats()
            logger.info(f"📊 实时数据 -> 视频:{stats['videos']} | 赞:{stats['likes']} | 评:{stats['comments']} | 关:{stats['follows']}")

            # C. 划到下一个视频
            self._check_stop()
            if not self._recover_to_video_page("滑动下一个视频前", max_back=4):
                recovery_failures += 1
                if recovery_failures >= 3 or not self._reset_and_reenter_video_flow("滑动前恢复失败"):
                    logger.warning("滑动前连续恢复失败，停止当前关键词的视频循环")
                    break
                continue
            recovery_failures = 0

            # 随机行为模拟：小概率快速划过（不执行互动）
            if not BehaviorRandomizer.maybe_fast_scroll(self.runner.device):
                # 正常滑动到下一个视频
                self._report(current_action="智能流转至下一个高潜流量节点")
                self.runner.run_action(SwipeNextVideoAction)

            if self._selected_feature_chain_enabled():
                logger.debug("执行功能选择已启用，跳过回看/首页推荐流随机行为")
            else:
                # 随机行为模拟：小概率回看上一个视频
                BehaviorRandomizer.maybe_rewind(self.runner.device)

                # 随机行为模拟：小概率切到首页推荐流浏览
                BehaviorRandomizer.maybe_browse_home_feed(self.runner.device)

            # 随机行为模拟：小概率长停顿（模拟走神）
            BehaviorRandomizer.maybe_pause_and_think()

            # 随机停留（使用配置的防风控参数）
            min_stay = self.config.get('crawler', {}).get('min_video_stay', 5)
            max_stay = self.config.get('crawler', {}).get('max_video_stay', 12)
            stay_time = random.uniform(min_stay, max_stay)
            long_watch_triggered = 0

            # 15% 概率长停留（模拟看完整个视频）— 受概率决策总开关控制
            if self._probability_allows('long_watch'):
                stay_time += random.uniform(5.0, 15.0)
                long_watch_triggered = 1
                logger.info(f"📺 长停留模式: 预计停留 {stay_time:.1f} 秒")

            logger.info(f"等待 {stay_time:.1f} 秒后处理下一个视频...")
            self._interruptible_sleep(stay_time)

            # 记录本视频停留时长与长停留标记到数据库
            try:
                self.db.update_video_detail(
                    video_id,
                    stay_duration=round(stay_time, 1),
                    long_watch=long_watch_triggered,
                    action_event={"t": _now_str(), "phase": "C", "msg": f"停留 {stay_time:.1f}s{'(长停留)' if long_watch_triggered else ''}"},
                )
            except Exception:
                pass

    def _extract_title_from_description(self, description):
        """从视频描述中提取标题"""
        if not description:
            return self.current_keyword or "当前视频"

        lines = []
        for raw_line in str(description).splitlines():
            line = raw_line.strip()
            if not line:
                continue
            line = re.sub(r"http[s]?://\S+", "", line).strip()
            if 6 <= len(line) <= 60:
                lines.append(line)

        return lines[0] if lines else (self.current_keyword or "当前视频")
