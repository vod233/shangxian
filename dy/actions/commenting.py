import time
import re
import random
import logging
from .base_action import BaseAction
from .locators import TikTokLocators as L
from ..ai_reply_agent import DYReplyAgent
from ..anti_detection import HumanSleep

logger = logging.getLogger(__name__)


def _bounds_bottom(node):
    return node.info.get("bounds", {}).get("bottom", 0)


def _click_node_center(d, node):
    bounds = node.info.get("bounds", {}) or {}
    if not bounds:
        node.click()
        return
    x = int((bounds.get("left", 0) + bounds.get("right", 0)) / 2)
    y = int((bounds.get("top", 0) + bounds.get("bottom", 0)) / 2)
    d.click(x, y)


def _is_visible_enabled(node):
    """严格判断节点是否真正可见且可用。

    FIX-C: uiautomator2 的 info 字典键名是 `visibleToUser`（驼峰），不是 `visible`。
    原代码 `info.get("visible", True)` 总是命中默认值 True，导致隐藏的 EditText
    被误判为可见，进而触发 FIX-10 的 press back 误关闭评论区。
    可见性缺失时默认 False（安全失败），避免误判。
    """
    info = node.info
    # 优先 visibleToUser；老版本兼容 visible；缺失时默认 False
    visible = info.get("visibleToUser", info.get("visible", False))
    enabled = info.get("enabled", False)
    return bool(visible) and bool(enabled)


def _is_in_bottom_half(d, node, min_top_ratio=0.3):
    """判断节点顶部是否在屏幕中下部以下（过滤掉位于顶部的搜索框等）。

    FIX-C': 评论输入框通常在屏幕底部，搜索框在屏幕顶部。
    min_top_ratio=0.3 表示节点 top 坐标需 >= 屏幕高度的 30%，
    这样可过滤掉位于顶部的搜索框（top 通常 < 10% 屏高）。
    """
    try:
        bounds = node.info.get("bounds", {}) or {}
        top = bounds.get("top", 0)
        _, screen_h = d.window_size()
        return top >= int(screen_h * min_top_ratio)
    except Exception:
        return True  # 无法判断时不阻断，但 _is_visible_enabled 已严格化


def _xpath_exists(d, xpath, timeout=0.1):
    try:
        return d.xpath(xpath).exists(timeout=timeout)
    except TypeError:
        try:
            return bool(d.xpath(xpath).exists)
        except Exception:
            return False
    except Exception:
        return False


def _find_bottom_edit_text(d, timeout=3):
    """Find the visible, enabled edit box closest to the bottom of the screen.

    FIX-C': 在原 COMMENT_EDIT_TEXT_XPATH 基础上增加可见性 + 屏幕底部范围双重过滤，
    避免搜索框、广告位等位于屏幕顶部的隐藏 EditText 被误判为评论输入框残留，
    进而在 OpenCommentSectionAction 中误触发 press back 关闭评论区。
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        edit_nodes = d.xpath(L.COMMENT_EDIT_TEXT_XPATH).all()
        candidates = [
            node for node in edit_nodes
            if _is_visible_enabled(node) and _is_in_bottom_half(d, node)
        ]
        if candidates:
            return sorted(candidates, key=_bounds_bottom)[-1]
        HumanSleep.sleep(custom_range=(0.3, 0.3))
    return None


def _find_clickable_send_button(d):
    # 策略1：标准 XPath（视频页主路径，要求 clickable=true）
    send_nodes = d.xpath(L.COMMENT_SEND_BTN_XPATH).all()
    candidates = [
        node for node in send_nodes
        if node.info.get("clickable", False) and _is_visible_enabled(node)
    ]
    if candidates:
        return sorted(candidates, key=_bounds_bottom)[-1]

    # 策略2：resource-id 列表
    for resource_id in L.COMMENT_SEND_BTN_IDS:
        btn = d(resourceId=resource_id)
        if btn.exists(timeout=0.3):
            if btn.info.get("clickable", False) and _is_visible_enabled(btn):
                return btn

    # 策略3：楼中楼专用 — 放宽 clickable 限制（抖音楼中楼发送按钮可能 clickable=false 但可点）
    loose_candidates = [node for node in send_nodes if _is_visible_enabled(node)]
    if loose_candidates:
        logger.info("[CS4]使用宽松策略定位楼中楼发送按钮")
        return sorted(loose_candidates, key=_bounds_bottom)[-1]

    # 策略4：楼中楼坐标兜底 — EditText 右边界往左 60px
    edit_text = _find_bottom_edit_text(d, timeout=0.5)
    if edit_text:
        eb = edit_text.info.get('bounds', {}) or {}
        if eb:
            x = int(eb.get('right', 0)) - 60
            y = int((eb.get('top', 0) + eb.get('bottom', 0)) / 2)
            logger.info(f"[CS4]坐标兜底点击发送区域: ({x}, {y})")

            class _CoordButton:
                def __init__(self, d, x, y):
                    self._d = d
                    self._x = x
                    self._y = y

                def click(self):
                    self._d.click(self._x, self._y)

                @property
                def info(self):
                    return {
                        "clickable": True,
                        "visible": True,
                        "enabled": True,
                        "bounds": {
                            "left": self._x - 30, "right": self._x + 30,
                            "top": self._y - 30, "bottom": self._y + 30,
                        },
                    }

            return _CoordButton(d, x, y)

    return None


def _message_visible(d, text, timeout=2):
    if not text:
        return False
    deadline = time.time() + timeout
    while time.time() < deadline:
        nodes = d.xpath(L.COMMENT_TEXT_XPATH).all()
        bottom_nodes = sorted(nodes, key=_bounds_bottom)[-8:]
        for node in bottom_nodes:
            node_text = str(node.info.get("text", "") or "")
            if text in node_text:
                return True
        HumanSleep.sleep(custom_range=(0.3, 0.3))
    return False


def _set_text_to_input(d, edit_text, text):
    edit_text.click()
    HumanSleep.sleep(custom_range=(0.15, 0.3))
    resource_id = edit_text.info.get("resourceId") or edit_text.info.get("resourceName")
    if resource_id:
        try:
            input_selector = d(resourceId=resource_id)
            if input_selector.exists(timeout=0.5):
                input_selector.set_text(text)
                return True
        except Exception as e:
            logger.info(f"resource-id 输入失败，改用 fastinput: {e}")

    try:
        d.set_fastinput_ime(True)
        try:
            d.clear_text()
        except Exception:
            for _ in range(30):
                d.press("del")
        d.send_keys(text)
        return True
    finally:
        try:
            d.set_fastinput_ime(False)
        except Exception:
            pass


def _input_still_contains(d, text):
    edit_text = _find_bottom_edit_text(d, timeout=0.8)
    if not edit_text:
        return False
    current_text = str(edit_text.info.get("text", "") or "").strip()
    return bool(current_text and text in current_text)


def _input_found_and_cleared(d, text):
    """仅当【确实找到输入框且其中不再包含待发文本】时才判定为已清空。

    FIX(发送假阳性): 旧判定 `not _input_still_contains(...)` 在键盘收起/页面切走、
    输入框查不到时返回 True，把"找不到输入框"误当成"已发送"。
    这里把"找不到输入框"显式视为【无法确认清空】(返回 False)，发送成功只能由
    评论气泡可见(_message_visible)或"输入框存在且已清空"两条正向证据之一来确认。
    """
    edit_text = _find_bottom_edit_text(d, timeout=0.8)
    if not edit_text:
        return False
    current_text = str(edit_text.info.get("text", "") or "").strip()
    return not (current_text and text in current_text)


def _close_comment_input_if_open(d, text=""):
    """关闭评论输入态，避免键盘或输入框覆盖后续评论区入口。"""
    edit_text = _find_bottom_edit_text(d, timeout=0.8)
    if not edit_text:
        return True

    current_text = str(edit_text.info.get("text", "") or "").strip()
    if text and current_text and text not in current_text:
        return True

    # FIX-09: 评论区面板打开时 press back 会误关评论区，改为点击顶部空白区域收起键盘。
    comment_panel_open = False
    try:
        if d(resourceId=L.COMMENT_LIST_CONTAINER).exists(timeout=0.2):
            comment_panel_open = True
    except Exception:
        pass

    if comment_panel_open:
        logger.info("评论区面板已打开，点击顶部空白区域收起键盘（避免 press back 误关评论区）")
        try:
            w, h = d.window_size()
            d.click(int(w * 0.5), int(h * 0.12))
            HumanSleep.sleep(custom_range=(0.4, 0.8))
        except Exception:
            pass
    else:
        logger.info("检测到评论输入框仍处于打开状态，执行返回关闭")
        d.press("back")
        HumanSleep.sleep(custom_range=(0.5, 1.0))
    return _find_bottom_edit_text(d, timeout=0.5) is None


def _run_guard(stop_check):
    """执行可选的停止/超时守卫回调；回调可抛 InterruptedError 立即中断。"""
    if stop_check is not None:
        stop_check()


def _send_text_from_focused_input(d, text, log_label, stop_check=None):
    _run_guard(stop_check)
    edit_text = _find_bottom_edit_text(d, timeout=3)
    if not edit_text:
        logger.warning(f"{log_label}: 未找到可用输入框")
        return False

    if not _set_text_to_input(d, edit_text, text):
        return False
    HumanSleep.sleep(custom_range=(0.5, 1.2))

    for attempt in range(3):
        _run_guard(stop_check)
        send_btn = _find_clickable_send_button(d)
        if send_btn:
            _click_node_center(d, send_btn)
            logger.info(f"{log_label}: 已点击发送按钮")
            HumanSleep.sleep(custom_range=(1.0, 2.0))
            # FIX(假阳性): 成功必须有正向证据——评论气泡可见 或 输入框存在且已清空。
            if _message_visible(d, text) or _input_found_and_cleared(d, text):
                return True
            logger.info(f"{log_label}: 点击发送后文本仍在输入框，继续重试")
        logger.info(f"{log_label}: 发送按钮未就绪，重试 {attempt + 1}/3")
        HumanSleep.sleep(custom_range=(0.5, 1.2))

    _run_guard(stop_check)
    logger.info(f"{log_label}: 尝试回车键发送")
    d.press("enter")
    HumanSleep.sleep(custom_range=(1.0, 2.0))
    return _message_visible(d, text) or _input_found_and_cleared(d, text)


class PostCommentAction(BaseAction):
    """发布一条普通视频评论"""
    def execute(self, comment_text):
        if not comment_text:
            return False

        logger.info(f"准备发布视频评论: {comment_text}")
        try:
            edit_text = _find_bottom_edit_text(self.d, timeout=1)
            if not edit_text:
                hints = [
                    L.COMMENT_INPUT_HINT_1, L.COMMENT_INPUT_HINT_2,
                    L.COMMENT_INPUT_HINT_3, L.COMMENT_INPUT_HINT_4
                ]
                found_input = False
                for hint in hints:
                    node = self.d(text=hint)
                    if node.exists(timeout=1):
                        node.click()
                        self.human_sleep('fast', custom_range=(0.5, 1.5))
                        found_input = True
                        break

                if not found_input:
                    logger.warning("未找到视频页底部的评论输入框")
                    return False

            sent = _send_text_from_focused_input(self.d, comment_text, "视频评论")
            _close_comment_input_if_open(self.d, comment_text)
            return sent

        except Exception as e:
            logger.error(f"评论流程出现异常: {e}")
            _close_comment_input_if_open(self.d, comment_text)
            return False

class OpenCommentSectionAction(BaseAction):
    """打开评论区（根据规律寻找主评论区按钮）"""
    def execute(self):
        # FIX-10 + FIX-C: 打开评论区前关闭可能残留的评论输入框。
        # 注意：_find_bottom_edit_text 已严格化（visibleToUser + 屏幕底部范围），
        # 不会再误判隐藏的搜索框/广告位 EditText，避免在纯净视频页误触发 press back。
        # FIX-KEYBOARD: 用顶部点击收起键盘替代 press("back")，避免 back 改变页面状态
        # 导致 COMMENT_BTN_DYNAMIC 匹配不到评论按钮（实测 B.3 成功后 back 会让按钮从 accessibility tree 消失）。
        try:
            if _find_bottom_edit_text(self.d, timeout=0.5):
                logger.info("检测到残留评论输入框，点击视频中央区域收起键盘（避免 back 影响按钮检测）")
                w_dev, h_dev = self.d.window_size()
                self.d.click(int(w_dev * 0.5), int(h_dev * 0.5))
                self.human_sleep('fast', custom_range=(0.5, 1.0))
        except Exception:
            pass

        logger.info("正在通过 content-desc 规律寻找主评论区按钮...")
        all_nodes = self.d.xpath(L.COMMENT_BTN_DYNAMIC).all()

        candidates = []
        for node in all_nodes:
            desc = node.info.get('contentDescription', '') or node.info.get('content-desc', '')
            if desc and re.match(r'^评论(评论|[\d万wWkK.]+.*)，按钮$', desc):
                candidates.append(node)

        if len(candidates) >= 2:
            candidates.sort(key=lambda x: x.info['bounds']['top'])
            target_node = candidates[1]
            target_desc = target_node.info.get('contentDescription', '') or target_node.info.get('content-desc', '')

            if "评论评论" in target_desc:
                logger.info("当前视频可能为 0 评论")
            else:
                logger.info(f"成功锁定评论区入口，当前评论数标识: {target_desc}")

            target_node.click()
            self.human_sleep('normal', custom_range=(1.5, 3.0))
            return True

        # FIX-D: 候选不足时的安全兜底链路（不再 return True 造假）
        logger.warning(f"未找到足够的评论按钮候选目标 (找到 {len(candidates)} 个)。尝试兜底定位...")
        fallback_btn = self.d.xpath(L.COMMENT_BTN_FALLBACK)
        if fallback_btn.wait(timeout=2):
            try:
                fallback_btn.click()
                self.human_sleep('normal')
                # 验证评论区是否真的打开
                if self._comment_panel_opened():
                    logger.info("兜底 XPath 点击后评论区已打开")
                    return True
                logger.warning("兜底 XPath 点击后评论区未打开")
                return False
            except Exception as exc:
                logger.warning(f"兜底 XPath 点击异常: {exc}")
                return False

        # FIX-CMTBTN: 新版抖音评论按钮 content-desc 格式可能不带"按钮"后缀，
        # 尝试用更宽泛的 XPath + 位置过滤（右侧底部区域的评论相关元素）
        logger.info("尝试宽泛匹配右侧评论区域元素...")
        try:
            wide_nodes = self.d.xpath('//*[contains(@content-desc, "评论")]').all()
            if not wide_nodes:
                wide_nodes = self.d.xpath('//*[contains(@text, "评论")]').all()
            # 过滤：取屏幕右侧 (x > 70% 宽度) 且可点击的节点
            w_dev, h_dev = self.d.window_size()
            right_btns = []
            for n in wide_nodes:
                try:
                    b = n.info.get('bounds', {}) or {}
                    if b.get('left', 0) >= w_dev * 0.65 and n.info.get('clickable', False):
                        right_btns.append(n)
                except Exception:
                    continue
            if right_btns:
                right_btns.sort(key=lambda n: n.info.get('bounds', {}).get('top', 0))
                target = right_btns[0]  # 取最上方的一个（评论区按钮通常在最上）
                target.click()
                self.human_sleep('normal', custom_range=(1.5, 3.0))
                if self._comment_panel_opened():
                    logger.info("宽泛匹配点击后评论区已打开")
                    return True
                logger.warning("宽泛匹配点击后评论区未打开")
        except Exception as exc:
            logger.warning(f"宽泛匹配异常: {exc}")

        # 最后坐标兜底：必须验证状态，失败返回 False，让上层 _run_comment_lead_safely 走 open_failed 分支
        w, h = self.d.window_size()
        logger.warning("XPath 兜底失败，尝试点击评论按钮常见区域坐标（安全模式）")
        self.human_click(int(w * 0.92), int(h * 0.63))
        self.human_sleep('normal', custom_range=(1.0, 2.0))
        if self._comment_panel_opened():
            logger.info("坐标兜底点击后评论区已打开")
            return True
        logger.warning("坐标兜底点击后评论区仍未打开，返回 False（不再造假）")
        return False

    def _comment_panel_opened(self, timeout=2.0):
        """验证评论区面板是否真的打开（必须看到评论区容器，避免误判）。
        EditText 不再作为独立判定条件，因为视频页底部也有评论输入框会造成假阳性。
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                # 主评论区容器（新版 Douyin 可能已变更 rlp → 其他 ID）
                if self.d(resourceId=L.COMMENT_LIST_CONTAINER).exists(timeout=0.3):
                    return True
                # 评论卡片容器 k4x（直接检测评论卡片存在）
                if self.d(resourceId=L.COMMENT_CARD_CONTAINER_ID).exists(timeout=0.3):
                    return True
                # 底部提示文本
                if _xpath_exists(self.d, L.COMMENT_NO_MORE_TEXT, timeout=0.3):
                    return True
            except Exception:
                pass
            HumanSleep.sleep(custom_range=(0.2, 0.2))
        return False

class ProcessCommentSectionAction(BaseAction):
    """处理评论区内容逻辑 (滑动并解析评论)"""
    def execute(self):
        logger.info("开始处理评论区内容...")
        ai_agent = DYReplyAgent(self.config)
        video_title = getattr(self, 'video_title', "")
        keyword = getattr(self, 'keyword', "")

        interaction_config = self.config.get('interaction', {})
        max_swipes = int(interaction_config.get('max_comment_swipes', 2))
        max_reviews = int(interaction_config.get('max_ai_comment_reviews', 20))
        custom_keywords = interaction_config.get('intent_keywords', [])
        processed_comments = set()
        swipe_count = 0
        reviewed_count = 0

        # 保存意向评论信息（供 B.5 楼中楼私信评论者复用）
        self.lead_comment_node = None
        self.lead_comment_text = ""
        self.lead_reply_sent = False
        # keep_open_after_lead=True 时，发现意向评论后不关闭评论区（供 B.5 在评论区打开状态下操作）
        keep_open_after_lead = bool(getattr(self, 'keep_open_after_lead', False))

        deadline = getattr(self, 'deadline_ts', None)
        while swipe_count < max_swipes and reviewed_count < max_reviews:
            if hasattr(self, 'check_stop_callback'):
                self.check_stop_callback()

            # FIX(单视频卡死): 评论区扫描循环纳入单视频时间预算，超时立即收尾，
            # 不再让最耗时的楼中楼/私信链路游离在 max_seconds_per_video 之外。
            if deadline is not None and time.time() > deadline:
                logger.warning("评论区扫描已超过单视频时间预算，停止扫描")
                break

            found_target, reviewed_now, should_break, lead_info = self._process_current_screen_comments(
                processed_comments,
                ai_agent,
                video_title,
                keyword,
                max_reviews - reviewed_count,
                custom_keywords,
            )
            reviewed_count += reviewed_now
            logger.info(f"AI 已识别评论 {reviewed_count}/{max_reviews} 条")

            if found_target and lead_info:
                # 保存意向评论节点和文本，供后续 B.5 私信评论者使用
                self.lead_comment_node = lead_info.get("node")
                self.lead_comment_text = lead_info.get("text", "")
                self.lead_reply_sent = lead_info.get("sent", False)
                logger.info("发现目标客户，完成互动，准备退出评论区")
                break

            # 守卫：识别到意向评论但发送失败时，必须停止扫描，避免 EditText 状态污染导致后续重复失败
            if should_break:
                logger.warning("已尝试楼中楼回复但发送失败，停止扫描避免状态污染")
                break

            if reviewed_count >= max_reviews:
                logger.info("已达到 AI 评论识别上限，停止继续扫描评论区")
                break

            if _xpath_exists(self.d, L.COMMENT_NO_MORE_TEXT):
                logger.info("已滑到底部，没有更多评论")
                break

            if not self._swipe_up_comments():
                logger.warning("滑动评论区失败")
                break

            swipe_count += 1
            HumanSleep.sleep(custom_range=(1.0, 2.0))

        # keep_open_after_lead=True 且已发现意向评论时，保留评论区打开状态（供 B.5 使用）
        if keep_open_after_lead and self.lead_comment_node is not None:
            logger.info("keep_open_after_lead=True，保留评论区打开状态供 B.5 使用")
            return True

        # === 无意向客户兜底策略：回复并私信前 N 条评论 ===
        # 规则：评论区非空但没有命中意向关键词时，取前 5 条有效评论逐一回复+私信，
        # 确保私信功能被客户感知。"宁愿错杀也不放过"。
        if self.lead_comment_node is None:
            fallback_count = self._fallback_reply_and_dm_top_comments(
                processed_comments, ai_agent, video_title, keyword, max_count=5,
                do_dm=keep_open_after_lead,  # 复用 task_runner 已做好的配额/概率检查
            )
            if fallback_count > 0:
                # 兜底已处理（含私信导航），评论区可能已关闭；交给上层恢复
                logger.info(f"兜底策略完成：已回复+私信 {fallback_count} 条评论")
                # 标记供 B.4/B.5 统计：lead_reply_sent=True + lead_pm_sent_count 已在方法内设置
                self.lead_reply_sent = True
                self.lead_comment_text = "fallback"  # 非空标记，区分"真无意向兜底"与"有意向但失败"
                return True

        logger.info("评论区处理完毕，关闭面板")
        return self._close_comment_section()

    def _process_current_screen_comments(self, processed_comments, ai_agent, video_title, keyword, remaining_reviews, custom_keywords=None):
        logger.info("正在解析当前屏幕可见评论...")
        # FIX-XPATH: 只匹配评论卡片容器(k4x)内的 TextView，而非全页面 //android.widget.TextView。
        # 全页面匹配会捕获用户名、时间戳、点赞数、导航栏等大量非评论节点，
        # 导致第一个匹配到的可能是不可交互的 TextView，CS1 点击失败。
        xpath = f'//*[@resource-id="{L.COMMENT_CARD_CONTAINER_ID}"]//android.widget.TextView'
        text_nodes = self.d.xpath(xpath).all()
        if not text_nodes:
            # 兜底：k4x container ID 变动时的降级方案
            text_nodes = self.d.xpath(L.COMMENT_TEXT_XPATH).all()
        custom_keywords = custom_keywords or []

        found_target = False
        should_break = False  # 守卫：发送失败也必须 break，避免状态污染后继续扫描
        reviewed_count = 0
        lead_info = None  # 保存意向评论的节点和文本（供 B.5 私信评论者使用）
        for node in text_nodes:
            text = node.info.get('text', '')
            if not text:
                continue
            # FIX(去重漏洞): 旧实现仅以"评论文本"为去重键，不同用户发相同短句(如"怎么买")
            # 会被误当成同一条而漏掉。改为 (评论者用户名 + 文本) 复合键，
            # 取不到用户名时回退到文本，至少不弱于原行为。
            dedup_key = self._comment_dedup_key(node, text)
            if dedup_key not in processed_comments:
                processed_comments.add(dedup_key)
                if not self._is_reviewable_comment(text):
                    continue
                reviewed_count += 1
                if ai_agent.is_intent_comment(text, video_title=video_title, keyword=keyword, custom_keywords=custom_keywords):
                    logger.info(f"🎯 AI 识别到意向评论: {text}")
                    sent = self._interact_with_potential_customer(node, text, ai_agent, video_title, keyword)
                    # 无论 sent 真假，识别到意向评论后都停止扫描：
                    #   sent=True：任务完成
                    #   sent=False：发送失败，EditText 可能已乱，继续扫描只会重复失败
                    should_break = True
                    found_target = sent
                    lead_info = {"node": node, "text": text, "sent": sent}
                    break
                if reviewed_count >= remaining_reviews:
                    break
        return found_target, reviewed_count, should_break, lead_info

    def _comment_dedup_key(self, node, text):
        """构造评论去重键：优先 (同卡片用户名 + 文本)，回退到纯文本。

        抖音评论卡片 k4x 内，username 节点(resource-id=title) 与评论 content 是兄弟节点。
        借助底层 lxml 在同卡片子树内取 title 文本即可区分"不同用户的相同短句"。
        """
        author = ""
        try:
            elem = getattr(node, 'elem', None)
            hops = 0
            while elem is not None and hops < 6:
                if elem.attrib.get('resource-id', '') == L.COMMENT_CARD_CONTAINER_ID:
                    for sub in elem.iter():
                        if sub.attrib.get('resource-id', '').endswith('/title'):
                            author = str(sub.attrib.get('text', '') or '').strip()
                            break
                    break
                elem = elem.getparent()
                hops += 1
        except Exception:
            author = ""
        return f"{author}{text}" if author else text

    def _is_reviewable_comment(self, text):
        if not text:
            return False
        clean = str(text).strip()
        if len(clean) < 4:
            return False
        ignored = {"作者", "置顶", "回复", "展开", "查看更多回复", "赞", "分享"}
        return clean not in ignored

    def _interact_with_potential_customer(self, comment_node, comment_text, ai_agent, video_title, keyword):
        comment_to_send = ai_agent.generate_lead_reply(
            comment_text,
            video_title=video_title,
            keyword=keyword,
        )
        if not comment_to_send:
            logger.warning("未能生成楼中楼回复，跳过本条意向评论")
            return False
        sent = self._send_comment_workflow(comment_node, comment_to_send)
        _close_comment_input_if_open(self.d, comment_to_send)
        self.human_sleep('normal')
        return sent

    def _do_cs1_click(self, comment_node):
        """CS1 第一步：用坐标点击 + 短按兜底，让评论的"回复"UI 出现。
        返回 True 表示 UI 已出现。"""
        try:
            _click_node_center(self.d, comment_node)
            self.human_sleep('fast', custom_range=(0.8, 1.5))
        except Exception as exc:
            logger.warning(f"[CS1]坐标点击评论节点失败: {exc}")
            return False
        return self._verify_cs1_reply_ui()

    def _verify_cs1_reply_ui(self):
        """验证评论的"回复"UI 是否已出现（回复提示词 或 底部 EditText）。"""
        has_reply_hint = any(
            self.d(text=hint).exists(timeout=0.3)
            for hint in ("回复", "回复评论", "举报", "不感兴趣")
        )
        has_edit_text = _find_bottom_edit_text(self.d, timeout=0.8) is not None
        if has_reply_hint:
            logger.info("[CS1]检测到回复提示词，UI 已就绪")
        if has_edit_text:
            logger.info("[CS1]检测到底部 EditText，输入框已就绪")
        return has_reply_hint or has_edit_text

    def _send_comment_workflow(self, comment_node, text):
        """楼中楼回复 — 按 CS0→CS6 闭环实现，每阶段出口必须自证成功"""
        logger.info(f"回复内容: {text}")

        # === CS0 选中态守卫：节点 bounds 必须可获取 ===
        bounds = comment_node.info.get('bounds') if comment_node else None
        if not bounds:
            logger.warning("[CS0]评论节点无 bounds，跳过楼中楼回复")
            return False

        # === CS1 触发态：坐标点击 + 父容器兜底，click 后必须出现回复提示词或 EditText ===
        # 原代码 comment_node.click() 使用 accessibility click，对非 clickable 节点静默失败。
        # 改为 _click_node_center 做原始坐标点击，再加父容器兜底。
        cs1_ok = self._do_cs1_click(comment_node)
        if not cs1_ok:
            # 兜底：尝试点击评论节点的父容器（comment card container 通常是 clickable 的）
            logger.info("[CS1]直接点击评论文本失败，尝试点击父容器")
            parent = comment_node.parent
            if callable(parent): parent = parent()
            if parent is not None:
                try:
                    _click_node_center(self.d, parent)
                    self.human_sleep('fast', custom_range=(0.8, 1.5))
                    cs1_ok = self._verify_cs1_reply_ui()
                except Exception as exc:
                    logger.warning(f"[CS1]父容器点击异常: {exc}")
            if not cs1_ok:
                # 最后兜底：长按评论节点（部分版本需长按弹出菜单）
                logger.info("[CS1]父容器兜底也失败，尝试长按评论节点")
                try:
                    bounds = comment_node.info.get('bounds') if comment_node else None
                    if bounds:
                        x = int((bounds.get('left', 0) + bounds.get('right', 0)) / 2)
                        y = int((bounds.get('top', 0) + bounds.get('bottom', 0)) / 2)
                        self.d.long_click(x, y, duration=0.6)
                        self.human_sleep('normal', custom_range=(1.0, 2.0))
                        cs1_ok = self._verify_cs1_reply_ui()
                except Exception as exc:
                    logger.warning(f"[CS1]长按兜底异常: {exc}")
        if not cs1_ok:
            logger.warning("[CS1]所有点击方案均未触发回复界面或输入框，状态未闭环")
            return False

        # === CS2 聚焦态：必须验证 EditText 真的出现 ===
        has_edit_text = _find_bottom_edit_text(self.d, timeout=0.8) is not None
        if not has_edit_text:
            if not self._focus_reply_input_verified():
                logger.warning("[CS2]未能聚焦楼中楼回复输入框")
                return False

        # === CS3 输入态：必须验证文本真的进了框 ===
        if not self._set_text_verified(text):
            logger.warning("[CS3]文本未可靠进入输入框")
            return False

        # === CS4 发送态 + CS5 验证态（由 _send_text_from_focused_input 内部完成） ===
        # FIX(停止无响应): 把停止/超时守卫透传进发送重试循环，避免点"停止"后仍卡在 6 次重试里。
        return _send_text_from_focused_input(
            self.d, text, "楼中楼回复", stop_check=self._guard
        )

    def _guard(self):
        """统一的停止 + 单视频超时守卫；任一触发即抛 InterruptedError/超时中断。"""
        cb = getattr(self, 'check_stop_callback', None)
        if cb is not None:
            cb()
        deadline = getattr(self, 'deadline_ts', None)
        if deadline is not None and time.time() > deadline:
            raise TimeoutError("评论区处理超过单视频时间预算，主动中断楼中楼链路")

    def _focus_reply_input_verified(self):
        """CS2 守卫：点击回复提示词后必须验证 EditText 真的出现"""
        hints = [
            "回复", "回复评论", "善语结善缘", "发条评论",
            L.COMMENT_INPUT_HINT_1, L.COMMENT_INPUT_HINT_2,
            L.COMMENT_INPUT_HINT_3, L.COMMENT_INPUT_HINT_4
        ]
        for hint in hints:
            node = self.d(text=hint)
            if node.exists(timeout=0.5):
                try:
                    node.click()
                except Exception:
                    continue
                self.human_sleep('fast', custom_range=(0.5, 1.0))
                # CS2 出口守卫
                if _find_bottom_edit_text(self.d, timeout=1.0) is not None:
                    return True
        # 兜底：直接检测 EditText 是否已存在
        return _find_bottom_edit_text(self.d, timeout=1.0) is not None

    def _set_text_verified(self, text):
        """CS3 守卫：输入文本后必须验证文本真的在框内"""
        edit_text = _find_bottom_edit_text(self.d, timeout=2)
        if not edit_text:
            return False
        if not _set_text_to_input(self.d, edit_text, text):
            return False
        HumanSleep.sleep(custom_range=(0.5, 1.0))
        # CS3 出口守卫：文本必须真的在输入框内
        return _input_still_contains(self.d, text)

    def _swipe_up_comments(self):
        """人性化滑动评论区（贝塞尔曲线）"""
        try:
            container = self.d(resourceId=L.COMMENT_LIST_CONTAINER)
            if container.exists:
                bounds = container.info['bounds']
                cx = (bounds['left'] + bounds['right']) // 2
                sy = int(bounds['bottom'] * 0.8) + random.randint(-5, 5)
                ey = int(bounds['top'] + (bounds['bottom'] - bounds['top']) * 0.2) + random.randint(-5, 5)
                self.human_swipe_curve(cx, sy, cx, ey)
                return True
            else:
                w, h = self.d.window_size()
                self.human_swipe_curve(
                    w // 2 + random.randint(-10, 10), int(h * 0.7),
                    w // 2 + random.randint(-10, 10), int(h * 0.3)
                )
                return True
        except Exception as e:
            logger.error(f"滑动异常: {e}")
            return False

    def _comment_panel_open(self):
        try:
            if self.d(resourceId=L.COMMENT_LIST_CONTAINER).exists(timeout=0.2):
                return True
        except TypeError:
            if self.d(resourceId=L.COMMENT_LIST_CONTAINER).exists:
                return True
        except Exception:
            pass

        # 新版 Douyin 评论区容器可能只有 k4x 卡片，rlp 已不存在
        try:
            if self.d(resourceId=L.COMMENT_CARD_CONTAINER_ID).exists(timeout=0.2):
                return True
        except Exception:
            pass

        return _xpath_exists(self.d, L.COMMENT_NO_MORE_TEXT, timeout=0.2)

    def _get_visible_comment_nodes(self):
        """获取当前屏幕可见的评论卡片内容节点（只在 k4x 容器内查找）。"""
        xpath = f'//*[@resource-id="{L.COMMENT_CARD_CONTAINER_ID}"]//android.widget.TextView'
        nodes = self.d.xpath(xpath).all()
        if not nodes:
            nodes = self.d.xpath(L.COMMENT_TEXT_XPATH).all()
        return nodes

    def _fallback_reply_and_dm_top_comments(self, processed_comments, ai_agent, video_title, keyword, max_count=5, do_dm=False):
        """无意向客户兜底：取前 N 条有效评论，先全部回复，再逐个私信。
        先回复后私信的顺序是因为私信会导航离开评论区导致节点引用失效。
        do_dm 由上层 _run_comment_lead_safely 传入，已包含 enable_comment_lead_pm + lead_pm 配额 + 概率检查。
        返回实际处理条数。
        """
        if not do_dm:
            logger.info("兜底策略：私信未启用或配额/概率限制，仅回复不私信")
        lead_pm_messages = self.config.get('interaction', {}).get('lead_pm_message_list', [])
        if do_dm and not lead_pm_messages:
            logger.warning("兜底私信: lead_pm_message_list 为空，仅回复不私信")

        text_nodes = self._get_visible_comment_nodes()
        if not text_nodes:
            logger.warning("兜底策略：当前屏幕无可见评论节点")
            return 0

        # 阶段1: 收集前 N 条有效评论（节点+文本）
        targets = []  # [(node, text), ...]
        for node in text_nodes:
            text = str(node.info.get('text', '') or '').strip()
            if not text or text in processed_comments:
                continue
            if not self._is_reviewable_comment(text):
                continue
            if len(targets) >= max_count:
                break
            targets.append((node, text))
            processed_comments.add(text)

        if not targets:
            logger.warning("兜底策略：当前屏幕无符合条件的评论")
            return 0

        # 阶段2: 在评论区仍打开状态下，先逐一回复所有目标评论
        logger.info(f"兜底阶段1: 回复前 {len(targets)} 条评论")
        for i, (node, text) in enumerate(targets):
            deadline = getattr(self, 'deadline_ts', None)
            if deadline is not None and time.time() > deadline:
                logger.warning("兜底阶段1：超过单视频时间预算，提前结束回复")
                targets = targets[:i]  # 只私信已回复的
                break
            logger.info(f"🎯 兜底回复 [{i + 1}/{len(targets)}]: {text[:30]}")
            reply = ai_agent.generate_lead_reply(text, video_title=video_title, keyword=keyword)
            if reply:
                self._send_comment_workflow(node, reply)
                _close_comment_input_if_open(self.d, reply)
                self.human_sleep('fast')
            else:
                logger.warning(f"兜底回复 [{i + 1}]: 未能生成回复，仍尝试私信")

        # 阶段3: 通过评论文本重新定位，逐一私信（每次私信后需回到评论区重新查找下一个）
        if not do_dm or not lead_pm_messages:
            return len(targets)

        self.lead_pm_sent_count = 0
        logger.info(f"兜底阶段2: 私信前 {len(targets)} 位评论者")
        for i, (_, text) in enumerate(targets):
            deadline = getattr(self, 'deadline_ts', None)
            if deadline is not None and time.time() > deadline:
                logger.warning("兜底阶段2：超过单视频时间预算，提前结束私信")
                break

            logger.info(f"📨 兜底私信 [{i + 1}/{len(targets)}]: {text[:30]}")
            try:
                # 通过文本重新定位评论节点（阶段1回复后 UI 可能已刷新）
                refound = _refind_comment_node_by_text(self.d, text)
                if refound is None:
                    logger.warning(f"兜底私信 [{i + 1}]: 无法通过文本重定位节点，跳过")
                    continue

                pm_action = CommentLeadPmAction(
                    u2_device=self.d,
                    app_manager=self.app,
                    config=self.config,
                    lead_comment_node=refound,
                    lead_comment_text=text,
                )
                pm_result = pm_action.perform()
                pm_sent = isinstance(pm_result, dict) and pm_result.get("pm_sent", False)
                if pm_sent:
                    self.lead_pm_sent_count += 1
                logger.info(f"兜底私信 [{i + 1}]: {'成功' if pm_sent else '失败'}")

                # 从私信聊天页逐层返回：chat → profile → video(+评论区 overlay)
                self.d.press("back")
                self.human_sleep('normal')
                # 验证已离开聊天页（不再有 msg_et 输入框）
                if self.d(resourceId=L.PM_EDIT_TEXT_ID).exists(timeout=0.5):
                    logger.warning(f"兜底私信 [{i + 1}]: back 后仍在聊天页，再按一次")
                    self.d.press("back")
                    self.human_sleep('fast')
                self.d.press("back")
                self.human_sleep('normal')
            except Exception as exc:
                logger.warning(f"兜底私信 [{i + 1}]: 异常: {exc}")

        return len(targets)

    def _close_comment_section(self):
        for attempt in range(3):
            _close_comment_input_if_open(self.d)
            if not self._comment_panel_open():
                logger.info("确认评论区面板已关闭")
                return True
            logger.info(f"尝试关闭评论区面板... ({attempt + 1}/3)")
            self.d.press("back")
            self.human_sleep('fast')

        closed = not self._comment_panel_open()
        if not closed:
            logger.warning("评论区面板关闭失败")
        return closed


def _escape_xpath_text(text: str) -> str:
    """为 XPath contains() 返回安全的子串（不负责引号包裹，由调用方选择引号风格）。
    策略: 取前30字符；仅含一种引号则原样返回（调用方用另一种引号包裹）；
    含两种引号则去引号做 contains 部分匹配；无有效字符返回空串。
    """
    safe = text.strip()[:30]
    if not safe:
        return ""
    if '"' not in safe:
        return safe
    if "'" not in safe:
        return safe
    # 含两种引号：去掉引号做 contains 部分匹配
    return safe.replace('"', '').replace("'", '')


def _refind_comment_node_by_text(d, text: str):
    """用评论文本在评论区重新定位到【真实节点】(XMLElement)，而非 XPathSelector。

    FIX(高危-节点定位错误):
    旧实现返回 `d.xpath(xpath)`(XPathSelector)，下游 `.parent` 语义不对；
    且 uiautomator2 3.6.0 中 DeviceXPathSelector.exists 是 property，调用
    `.exists(timeout=0.8)` 会抛 TypeError 被 `except` 吞掉，导致此函数实际恒返回 None，
    FIX-05"按文本重定位"形同虚设。
    这里改用 `.all()`（方法，安全），返回真实 DeviceXMLElement 并做文本择优匹配。
    返回 XMLElement 或 None。
    """
    safe = _escape_xpath_text(text)
    if not safe:
        return None

    full = text.strip()
    xpaths = []
    if '"' not in safe:
        xpaths.append(f'//*[contains(@text, "{safe}")]')
    else:
        xpaths.append(f"//*[contains(@text, '{safe}')]")
    short = safe[:15]
    if short and short != safe:
        if '"' not in short:
            xpaths.append(f'//*[contains(@text, "{short}")]')
        else:
            xpaths.append(f"//*[contains(@text, '{short}')]")

    for xpath in xpaths:
        try:
            nodes = d.xpath(xpath).all()
        except Exception:
            nodes = []
        if not nodes:
            continue
        # 优先选择文本完整包含原评论全文的节点，避免命中片段/无关节点
        exact = [n for n in nodes if full and full in str(n.info.get('text', '') or '')]
        chosen = exact[0] if exact else nodes[0]
        return chosen

    return None


class CommentLeadPmAction(BaseAction):
    """B.5 楼中楼回复后私信评论者
    从已识别的意向评论节点反查评论者头像，进入评论者主页发送私信。
    前置：评论区必须处于打开状态（由 _run_comment_lead_safely 保证），lead_comment_node 有效。
    """
    def _guard(self):
        """停止 + 单视频超时守卫：任一触发即抛异常中断 B.5，保证'停止'立即响应、
        且 B.5 也纳入 max_seconds_per_video 时间预算（修复链路游离在熔断之外的问题）。"""
        cb = getattr(self, 'check_stop_callback', None)
        if cb is not None:
            cb()
        deadline = getattr(self, 'deadline_ts', None)
        if deadline is not None and time.time() > deadline:
            raise TimeoutError("B.5 私信链路超过单视频时间预算，主动中断")

    def execute(self):
        # 从 self 读取 lead_comment_node（由 run_action 通过 kwargs setattr）
        lead_comment_node = getattr(self, 'lead_comment_node', None)
        if lead_comment_node is None:
            logger.warning("B.5 未提供意向评论节点，跳过楼中楼私信")
            return {"pm_sent": False, "reason": "no_lead_node"}

        self._guard()
        # ① 从意向评论节点反查头像节点（同一 k4x 父容器下的 avatar）
        avatar_node = self._find_avatar_from_comment_node(lead_comment_node)
        if avatar_node is None:
            logger.warning("B.5 未能从意向评论节点反查到头像，跳过私信")
            return {"pm_sent": False, "reason": "avatar_not_found"}

        self._guard()
        # ② 点击头像进入评论者主页
        if not self._enter_commenter_profile(avatar_node):
            logger.warning("B.5 进入评论者主页失败，跳过私信")
            return {"pm_sent": False, "reason": "enter_profile_failed"}

        self._guard()
        # ③ 在评论者主页点击"发私信"按钮进入聊天页
        if not self._click_commenter_pm_button():
            logger.warning("B.5 评论者主页未找到私信按钮（可能已关闭陌生人私信），跳过")
            return {"pm_sent": False, "reason": "pm_btn_not_found"}

        # ④ 输入并发送私信（复用 FollowAuthorAction 的输入/发送/验证链路）
        message_list = self.config.get('interaction', {}).get('lead_pm_message_list', [])
        if not message_list:
            logger.warning("B.5 lead_pm_message_list 为空，跳过私信")
            return {"pm_sent": False, "reason": "empty_message_list"}

        message = random.choice(message_list)
        logger.info(f"B.5 准备向评论者发送私信: {message}")

        from .interaction import FollowAuthorAction
        pm_helper = FollowAuthorAction(self.d, self.app, self.config)
        pm_sent = False
        try:
            # 此时已在聊天页，直接用输入/发送链路（跳过 _send_private_message 的按钮查找逻辑）
            input_edit = pm_helper._find_private_message_input(timeout=4)
            if input_edit and _set_text_to_input(self.d, input_edit, message):
                self.human_sleep('normal')
                pm_sent = pm_helper._send_private_message_from_input(input_edit, message)
            else:
                logger.warning("B.5 未找到私信输入框或输入失败")
                pm_sent = False
        except Exception as exc:
            logger.error(f"B.5 私信评论者异常: {exc}")
            pm_sent = False

        if pm_sent:
            logger.info("B.5 楼中楼私信评论者成功")
        else:
            logger.warning("B.5 楼中楼私信评论者失败")
        return {"pm_sent": pm_sent, "reason": "ok" if pm_sent else "send_failed"}

    def _find_avatar_from_comment_node(self, comment_node):
        """从意向评论 content 节点反查【同一评论卡片 k4x】内的头像节点。

        FIX(发错人根因, 高危):
        旧实现 `parent.child(resourceId=...)` 在 uiautomator2 3.6.0 必抛 AttributeError
        （XMLElement 根本没有 child 方法），且 `_refind_comment_node_by_text` 返回的是
        XPathSelector 而非真实节点，`.parent` 语义也不对——两处都被 `except` 吞掉后，
        代码每次都跌入"全局取屏幕最底部 avatar"的兜底，于是私信发给了屏幕最下面那个人。

        重写策略（全部基于稳定可用的能力，杜绝"猜最底部头像"）：
          ① 用评论文本重新定位到【真实节点】(XMLElement，非 selector)。
          ② 沿底层 lxml 向上找到该评论所属的 k4x 卡片。
          ③ 仅在该卡片子树内取 clickable 头像（avatar）。
          ④ 卡片内无头像（典型：楼中楼子评论没有独立头像）或定位不到卡片时，
             用"几何就近"在评论文本左上方匹配头像，并要求足够接近；仍不确定则返回 None
             （宁可这条不私信，也绝不发错人）。
        """
        lead_comment_text = getattr(self, 'lead_comment_text', '') or ''
        fresh_node = comment_node
        if lead_comment_text:
            try:
                refound = self._refind_comment_node_by_text(lead_comment_text)
                if refound is not None:
                    fresh_node = refound
                    logger.info(f"B.5 通过文本重新定位到意向评论节点: {lead_comment_text[:20]}")
            except Exception as exc:
                logger.debug(f"B.5 文本反查节点失败，使用原节点: {exc}")

        if fresh_node is None:
            return None

        # ① + ② + ③ 卡片内精确取头像
        card_elem = self._find_card_elem(fresh_node)
        if card_elem is not None:
            avatar = self._find_clickable_avatar_in(card_elem)
            if avatar is not None:
                logger.info("B.5 已在意向评论所属卡片内定位到头像")
                return avatar
            logger.warning("B.5 意向评论所属卡片内无可点击头像（可能是楼中楼子评论），改用几何就近匹配")

        # ④ 几何就近兜底（严格：必须在文本左上方且足够接近）
        avatar = self._find_avatar_by_geometry(fresh_node)
        if avatar is not None:
            logger.info("B.5 通过几何就近匹配定位到意向评论头像")
            return avatar

        logger.warning("B.5 未能稳妥定位意向评论头像，跳过私信（已废弃'取屏幕最底部头像'兜底，避免发错人）")
        return None

    @staticmethod
    def _elem_of(node):
        """取 XMLElement/DeviceXMLElement 底层 lxml 元素；非此类型返回 None。"""
        return getattr(node, 'elem', None)

    def _wrap_elem(self, elem):
        """把底层 lxml 元素包成可读 .info（含 bounds）的节点对象，供点击使用。"""
        try:
            from uiautomator2.xpath import XMLElement
            return XMLElement(elem)
        except Exception:
            return None

    def _find_card_elem(self, node):
        """沿底层 lxml 向上查找评论卡片 k4x 元素；找不到返回 None。"""
        elem = self._elem_of(node)
        hops = 0
        while elem is not None and hops < 6:
            try:
                if elem.attrib.get('resource-id', '') == L.COMMENT_CARD_CONTAINER_ID:
                    return elem
                elem = elem.getparent()
            except Exception:
                return None
            hops += 1
        return None

    def _find_clickable_avatar_in(self, card_elem):
        """在卡片子树内查找 clickable 头像，返回可读 .info 的节点对象；无则 None。"""
        try:
            for sub in card_elem.iter():
                if (sub.attrib.get('resource-id', '') == L.COMMENTER_AVATAR_ID
                        and sub.attrib.get('clickable') == 'true'):
                    return self._wrap_elem(sub)
        except Exception as exc:
            logger.debug(f"B.5 卡片内查找头像失败: {exc}")
        return None

    def _find_avatar_by_geometry(self, node):
        """按几何关系匹配头像：头像应位于评论文本的【左侧且不低于文本太多】，
        取垂直最接近的一个，且要求在同卡片量级的距离内（<=260px），否则放弃。
        """
        try:
            cb = node.info.get('bounds', {}) or {}
        except Exception:
            cb = {}
        c_top = cb.get('top')
        c_left = cb.get('left')
        if c_top is None:
            return None
        try:
            avatars = self.d.xpath(L.COMMENTER_AVATAR_XPATH).all()
        except Exception:
            avatars = []
        best = None
        best_gap = None
        for a in avatars:
            ab = a.info.get('bounds', {}) or {}
            a_top = ab.get('top', 0)
            a_left = ab.get('left', 0)
            # 头像在评论下方明显处（>40px）排除；头像应在文本左侧
            if c_top - a_top < -40:
                continue
            if c_left is not None and a_left > c_left:
                continue
            gap = abs(c_top - a_top)
            if best_gap is None or gap < best_gap:
                best_gap = gap
                best = a
        if best is not None and best_gap is not None and best_gap <= 260:
            return best
        return None

    @staticmethod
    def _escape_xpath_text(text: str) -> str:
        """[已废弃] 请改用模块级 _escape_xpath_text(text)。"""
        return _escape_xpath_text(text)

    def _refind_comment_node_by_text(self, text: str):
        """[已废弃] 请改用模块级 _refind_comment_node_by_text(d, text)。"""
        return _refind_comment_node_by_text(self.d, text)

    def _enter_commenter_profile(self, avatar_node):
        """点击头像进入评论者主页，并验证已进入 UserProfileActivity。"""
        try:
            bounds = avatar_node.info.get('bounds') if avatar_node else None
            if not bounds:
                # 头像节点统一以 bounds 坐标点击（卡片内取到的是普通 XMLElement，无 .click()）。
                logger.warning("B.5 头像节点缺少 bounds，跳过私信避免误点")
                return False
            x = int((bounds.get('left', 0) + bounds.get('right', 0)) / 2)
            y = int((bounds.get('top', 0) + bounds.get('bottom', 0)) / 2)
            self.human_click(x, y, jitter_range=4)
            self.human_sleep('slow', custom_range=(2.5, 3.5))
        except Exception as exc:
            logger.warning(f"B.5 点击头像异常: {exc}")
            return False

        try:
            has_fans = (
                self.d(text="粉丝").exists(timeout=1.0)
                or self.d(text="获赞").exists(timeout=0.5)
                or self.d(text="作品").exists(timeout=0.5)
            )
            if has_fans:
                logger.info("B.5 已进入评论者主页")
                return True
            logger.warning("B.5 未检测到评论者主页特征（粉丝/获赞/作品）")
            return False
        except Exception as exc:
            logger.warning(f"B.5 验证评论者主页异常: {exc}")
            return False

    def _click_commenter_pm_button(self):
        """在评论者主页点击"发私信"按钮进入聊天页。
        dump 实测：可点击父容器 resource-id=zbl，图标本体 zbk 不可点击。
        优先用 COMMENTER_PM_BTN_XPATH（zbl），兜底用图标 content-desc 取父。
        """
        # 优先定位可点击父容器 zbl
        # FIX(私信整体失效, 高危): 旧代码对 self.d.xpath(...) 的【selector】调用 .exists(timeout=)，
        # 但 uiautomator2 3.6.0 中 DeviceXPathSelector.exists 是 property，带参调用必抛 TypeError，
        # 被 except 吞掉后 pm_btn 恒为 None -> 本函数每次返回 False -> 私信按钮永远点不到，
        # B.5 私信评论区用户功能整体失效。改用 .wait(timeout=)（真正的方法，返回 bool）。
        pm_btn = None
        try:
            btn = self.d.xpath(L.COMMENTER_PM_BTN_XPATH)
            if btn.wait(timeout=1.0):
                pm_btn = btn
                logger.info("B.5 通过 zbl 定位到评论者主页私信按钮")
        except Exception:
            pass

        # 兜底：通过图标 content-desc="私信" 取其可点击父容器
        if pm_btn is None:
            try:
                btn_parent = self.d.xpath(L.COMMENTER_PM_BTN_PARENT_XPATH)
                if btn_parent.wait(timeout=0.5):
                    pm_btn = btn_parent
                    logger.info("B.5 通过 zbk 父容器定位到评论者主页私信按钮")
            except Exception:
                pass

        # 最终兜底：直接用 PM_BTN_DESC（命中图标，靠 bounds 点击）
        if pm_btn is None:
            try:
                btn_desc = self.d.xpath(L.PM_BTN_DESC)
                if btn_desc.wait(timeout=0.5):
                    pm_btn = btn_desc
                    logger.info("B.5 通过 PM_BTN_DESC 兜底定位到私信图标")
            except Exception:
                pass

        if pm_btn is None:
            return False

        try:
            pm_btn.click()
            self.human_sleep('slow', custom_range=(2.0, 3.0))
        except Exception as exc:
            logger.warning(f"B.5 点击私信按钮异常: {exc}")
            return False

        # 验证已进入聊天页（检测 msg_et 输入框）
        try:
            if self.d(resourceId=L.PM_EDIT_TEXT_ID).exists(timeout=2.0):
                logger.info("B.5 已进入评论者私信聊天页")
                return True
            # 兜底：检测 EditText（同上，xpath selector 必须用 .wait 而非 .exists(timeout=)）
            if self.d.xpath(f'//{L.PM_EDIT_TEXT_CLASS}').wait(timeout=1.0):
                logger.info("B.5 已进入评论者私信聊天页（EditText 兜底）")
                return True
            logger.warning("B.5 点击私信按钮后未检测到聊天页")
            return False
        except Exception as exc:
            logger.warning(f"B.5 验证聊天页异常: {exc}")
            return False
