import time
import logging
from .base_action import BaseAction
from .locators import TikTokLocators as L

logger = logging.getLogger(__name__)

class EnsureHomeAction(BaseAction):
    """确保抖音已打开并处于可以搜索的状态 (包含处理青少年模式弹窗)"""
    _VIDEO_CONTEXT_MENU_MARKERS = ("不感兴趣", "倍速", "清屏播放", "识别图片", "添加至稍后再看")
    _CLOSABLE_OVERLAY_MARKERS = ("关闭", "分享名片", "发私信", "设置备注", "特别关注", "取消关注")

    def _dismiss_video_context_menu_if_present(self):
        if any(self.d(text=marker).exists(timeout=0.4) for marker in self._VIDEO_CONTEXT_MENU_MARKERS):
            logger.warning("检测到抖音视频长按菜单，执行返回关闭")
            try:
                width, height = self.d.window_size()
                self.human_click(int(width * 0.5), int(height * 0.12), jitter_range=4)
                self.human_sleep('fast')
            except Exception:
                pass
            if any(self.d(text=marker).exists(timeout=0.2) for marker in self._VIDEO_CONTEXT_MENU_MARKERS):
                self.d.press("back")
            self.human_sleep('fast')
            return True
        return False

    def execute(self):
        for i in range(10):
            if self._dismiss_video_context_menu_if_present():
                continue

            if any(self.d(text=marker).exists(timeout=0.2) for marker in self._CLOSABLE_OVERLAY_MARKERS):
                logger.warning("检测到可关闭浮层，执行返回关闭")
                self.d.press("back")
                self.human_sleep('fast')
                continue

            if self.d(text=L.HOME_TAB_TEXT).exists(timeout=0.5) or self.d.xpath(L.SEARCH_BTN_DESC).exists:
                logger.info("✅ 抖音首页加载成功")
                self.human_sleep('normal')
                return True
            
            if self.d(text=L.YOUTH_MODE_CLOSE_TEXT).exists(timeout=0.5):
                self.d(text=L.YOUTH_MODE_CLOSE_TEXT).click()
                logger.info("已跳过青少年模式弹窗")
                
            logger.info(f"等待首页加载中... ({i+1}/10)")
            self.human_sleep('normal')
        return False

class EnterSearchAction(BaseAction):
    """进入搜索框并输入关键词，随后切换到视频页签"""
    def execute(self, keyword):
        logger.info(f"正在搜索关键词: {keyword}")
        
        # 1. 多级兜底点击搜索按钮
        try:
            if self.d.xpath(L.SEARCH_BTN_DESC).click_exists(timeout=5):
                logger.info("通过 XPath 成功点击搜索按钮")
                self.human_sleep('normal')
            else:
                search_btn_id = self.d(resourceId=L.SEARCH_BTN_ID)
                if search_btn_id.exists(timeout=3):
                    search_btn_id.click()
                    logger.info("通过 ID 兜底点击成功")
                    self.human_sleep('normal')
                else:
                    search_desc = self.d(description=L.SEARCH_BTN_DESC_FALLBACK)
                    if search_desc.exists(timeout=2):
                        search_desc.click()
                        logger.info("通过 Description 兜底点击成功")
                        self.human_sleep('normal')
                    else:
                        logger.warning("所有点击方式均告失败，尝试坐标点击兜底")
                        sw, sh = self.d.window_size()
                        self.human_click(sw - 80, 80)
                        self.human_sleep('normal')
        except Exception as e:
            logger.error(f"点击搜索按钮异常: {e}")
            sw, sh = self.d.window_size()
            self.human_click(sw - 80, 80)
            self.human_sleep('normal')

        # 2. 输入搜索内容
        self.d.set_fastinput_ime(True)
        try:
            self.d.clear_text()
        except Exception as e:
            logger.warning(f"clear_text() 发生异常 ({e})，尝试发送删除按键兜底")
            for _ in range(20):
                self.d.press("del")
        
        self.d.send_keys(keyword)
        self.d.set_fastinput_ime(False)
        self.human_sleep('fast')
        
        confirm_btn = self.d.xpath(L.SEARCH_CONFIRM_BTN)
        if confirm_btn.wait(timeout=5):
            confirm_btn.click()
            self.human_sleep('page_load')
        else:
            self.d.send_action("search")
            self.human_sleep('page_load')

        # 3. 切换到视频页签
        video_tab = self.d.xpath(L.VIDEO_TAB)
        if video_tab.wait(timeout=5):
            video_tab.click()
            logger.info("成功切换到'视频'页签")
            self.human_sleep('normal')
            return True
        else:
            logger.warning("未找到'视频'页签按钮")
            return False

class ApplyFiltersAction(BaseAction):
    """打开并应用搜索结果的筛选条件"""

    def _is_option_selected(self, xpath_node) -> bool:
        try:
            info = xpath_node.info
            desc = info.get('contentDescription', '') or info.get('content-desc', '')
            return desc.startswith('已选中，')
        except Exception:
            return False

    def _click_filter_option(self, option_text: str, wait_timeout: float = 2.5) -> bool:
        container_xpath = L.filter_option_xpath(option_text)
        target = self.d.xpath(container_xpath)

        if not target.wait(timeout=wait_timeout):
            logger.warning(f"筛选选项[{option_text}]容器未出现，尝试文本节点兜底")
            text_node = self.d.xpath(f'//*[@text="{option_text}"]')
            if text_node.wait(timeout=1):
                try:
                    text_node.click()
                    self.human_sleep('fast')
                    logger.info(f"已通过文本节点点击筛选选项: {option_text}")
                    return True
                except Exception as exc:
                    logger.warning(f"文本节点点击[{option_text}]失败: {exc}")
            return False

        if self._is_option_selected(target):
            logger.info(f"筛选选项[{option_text}]已经是选中状态，跳过点击")
            return True

        try:
            target.click()
            logger.info(f"已点击筛选选项容器: {option_text}")
        except Exception as exc:
            logger.warning(f"点击筛选选项容器[{option_text}]异常: {exc}")
            return False

        self.human_sleep('fast')

        selected_confirmed = False
        for _ in range(8):
            self.human_sleep('fast')
            if self._is_option_selected(self.d.xpath(container_xpath)):
                selected_confirmed = True
                break
        if selected_confirmed:
            logger.info(f"✓ 已确认选中: {option_text}")
        else:
            logger.warning(f"⚠️ 点击后未能确认[{option_text}]选中状态")
        return selected_confirmed

    def execute(self, sort_mode: str = "latest"):
        sort_text = "最多点赞" if sort_mode == "most_liked" else "最新发布"
        logger.info(f">>> 自动化配对成功：模式[{sort_mode}] -> 点击按钮[{sort_text}] <<<")

        filter_btn = self.d.xpath(L.FILTER_PANEL_BTN)
        if not filter_btn.wait(timeout=4):
            logger.warning("未找到筛选按钮，无法设置排序工作流")
            return False

        bounds = filter_btn.info['bounds']
        cx = int((bounds['left'] + bounds['right']) / 2)
        cy = int((bounds['top'] + bounds['bottom']) / 2)

        for attempt in range(2):
            self.human_click(cx, cy)
            self.human_sleep('normal')
            if self.d.xpath(L.filter_option_xpath(sort_text)).wait(timeout=1.5):
                logger.info("筛选面板已打开")
                break
            if self.d.xpath(L.FILTER_SORT_PANEL_INDICATOR).wait(timeout=1):
                logger.info("筛选面板已打开（通过排序指示器确认）")
                break
            logger.info(f"等待筛选面板打开... (尝试 {attempt+1}/2)")
        else:
            logger.warning("筛选面板未能打开，尝试继续")

        sort_clicked = self._click_filter_option(sort_text)

        unseen_btn_xpath = L.FILTER_UNSEEN_BTN
        unseen_container = self.d.xpath(unseen_btn_xpath)
        if unseen_container.wait(timeout=1.5):
            if not self._is_option_selected(unseen_container):
                try:
                    unseen_container.click()
                    self.human_sleep('fast')
                    logger.info("已点击选择: 还未看过")
                except Exception as exc:
                    logger.warning(f"点击[还未看过]异常: {exc}")
            else:
                logger.info("[还未看过]已是选中状态，跳过")
        else:
            unseen_text = self.d.xpath('//*[@text="还未看过"]')
            if unseen_text.wait(timeout=1):
                try:
                    unseen_text.click()
                    self.human_sleep('fast')
                    logger.info("已通过文本节点点击: 还未看过")
                except Exception:
                    pass

        self.human_sleep('normal')

        if self.d.xpath(L.FILTER_SORT_PANEL_INDICATOR).exists:
            logger.info("面板仍打开，点击外部区域收起")
            w, h = self.d.window_size()
            self.human_click(int(w * 0.5), int(h * 0.3), jitter_range=10)
            self.human_sleep('normal')

        start_wait = time.time()
        while time.time() - start_wait < 5:
            if not self.d.xpath(L.FILTER_SORT_PANEL_INDICATOR).exists:
                break
            self.human_click(cx, cy)
            self.human_sleep('fast')

        if self.d.xpath(L.VIDEO_TAB).wait(timeout=1):
            pass

        self.human_sleep('normal')
        if sort_clicked:
            logger.info(f"--- 工作流切换完全执行：{sort_text} ---")
        else:
            logger.warning(f"--- 工作流切换未完成：{sort_text} 未被点击 ---")
        return sort_clicked

class EnterFirstVideoAction(BaseAction):
    """进入第一个全屏视频"""
    def execute(self):
        logger.info("正在定位第一个视频...")
        start_wait = time.time()
        while time.time() - start_wait < 8:
            nodes = self.d.xpath(L.VIDEO_DESC_TEXT_VIEW).all()
            for node in nodes:
                text = node.text
                if text and (len(text) > 10 or "#" in text):
                    logger.info(f"识别到视频文案: {text[:20]}...")
                    node.click()
                    self.human_sleep('normal')
                    return True
            self.human_sleep('fast')
                
        logger.warning("未找到特征文案，尝试点击默认视频位置")
        w, h = self.d.window_size()
        self.human_click(int(w * 0.3), int(h * 0.4), jitter_range=15)
        self.human_sleep('normal')
        return len(self.d.xpath(L.SHARE_BTN_DYNAMIC).all()) > 0 or len(self.d.xpath(L.COMMENT_BTN_DYNAMIC).all()) > 0

class SwipeNextVideoAction(BaseAction):
    """全屏模式下向下滑动到下一个视频（贝塞尔曲线人性化滑动）"""
    def execute(self):
        width, height = self.d.window_size()
        # 使用贝塞尔曲线滑动，起止点带随机偏移
        sx = width // 2 + __import__('random').randint(-20, 20)
        sy = int(height * 0.8) + __import__('random').randint(-10, 10)
        ex = width // 2 + __import__('random').randint(-20, 20)
        ey = int(height * 0.2) + __import__('random').randint(-10, 10)
        self.human_swipe_curve(sx, sy, ex, ey)
        self.human_sleep('fast')
        return True

class ResetToSearchAction(BaseAction):
    """返回 5 次以重置到首页状态"""
    def execute(self):
        logger.info("执行 5 次返回以重置到首页状态...")
        for i in range(5):
            self.d.press("back")
            self.human_sleep('fast', custom_range=(0.8, 1.8))
        return True
