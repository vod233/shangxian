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
    info = node.info
    return info.get("visible", True) and info.get("enabled", True)


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
    """Find the visible, enabled edit box closest to the bottom of the screen."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        edit_nodes = d.xpath(L.COMMENT_EDIT_TEXT_XPATH).all()
        candidates = [node for node in edit_nodes if _is_visible_enabled(node)]
        if candidates:
            return sorted(candidates, key=_bounds_bottom)[-1]
        HumanSleep.sleep(custom_range=(0.3, 0.3))
    return None


def _find_clickable_send_button(d):
    # 策略1：标准 XPath（视频页主路径，要求 clickable=true）
    send_nodes = d.xpath(L.COMMENT_SEND_BTN_XPATH).all()
    candidates = [
        node for node in send_nodes
        if node.info.get("clickable", False) and node.info.get("visible", True) and node.info.get("enabled", True)
    ]
    if candidates:
        return sorted(candidates, key=_bounds_bottom)[-1]

    # 策略2：resource-id 列表
    for resource_id in L.COMMENT_SEND_BTN_IDS:
        btn = d(resourceId=resource_id)
        if btn.exists(timeout=0.3):
            info = btn.info
            if info.get("clickable", False) and info.get("visible", True) and info.get("enabled", True):
                return btn

    # 策略3：楼中楼专用 — 放宽 clickable 限制（抖音楼中楼发送按钮可能 clickable=false 但可点）
    loose_candidates = [
        node for node in send_nodes
        if node.info.get("visible", True) and node.info.get("enabled", True)
    ]
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


def _close_comment_input_if_open(d, text=""):
    """关闭评论输入态，避免键盘或输入框覆盖后续评论区入口。"""
    edit_text = _find_bottom_edit_text(d, timeout=0.8)
    if not edit_text:
        return True

    current_text = str(edit_text.info.get("text", "") or "").strip()
    if text and current_text and text not in current_text:
        return True

    logger.info("检测到评论输入框仍处于打开状态，执行返回关闭")
    d.press("back")
    HumanSleep.sleep(custom_range=(0.5, 1.0))
    return _find_bottom_edit_text(d, timeout=0.5) is None


def _send_text_from_focused_input(d, text, log_label):
    edit_text = _find_bottom_edit_text(d, timeout=3)
    if not edit_text:
        logger.warning(f"{log_label}: 未找到可用输入框")
        return False

    if not _set_text_to_input(d, edit_text, text):
        return False
    HumanSleep.sleep(custom_range=(0.5, 1.2))

    for attempt in range(3):
        send_btn = _find_clickable_send_button(d)
        if send_btn:
            _click_node_center(d, send_btn)
            logger.info(f"{log_label}: 已点击发送按钮")
            HumanSleep.sleep(custom_range=(1.0, 2.0))
            if _message_visible(d, text) or not _input_still_contains(d, text):
                return True
            logger.info(f"{log_label}: 点击发送后文本仍在输入框，继续重试")
        logger.info(f"{log_label}: 发送按钮未就绪，重试 {attempt + 1}/3")
        HumanSleep.sleep(custom_range=(0.5, 1.2))

    logger.info(f"{log_label}: 尝试回车键发送")
    d.press("enter")
    HumanSleep.sleep(custom_range=(1.0, 2.0))
    return _message_visible(d, text) or not _input_still_contains(d, text)


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
        logger.info("正在通过 content-desc 规律寻找主评论区按钮...")
        all_nodes = self.d.xpath(L.COMMENT_BTN_DYNAMIC).all()

        candidates = []
        for node in all_nodes:
            desc = node.info.get('contentDescription', '') or node.info.get('content-desc', '')
            if desc and re.match(r'^评论(评论|[\d万wWkK.]+.*)，按钮$', desc):
                candidates.append(node)

        if len(candidates) < 2:
            logger.warning(f"未找到足够的评论按钮候选目标 (找到 {len(candidates)} 个)。尝试兜底定位...")
            fallback_btn = self.d.xpath(L.COMMENT_BTN_FALLBACK)
            if fallback_btn.wait(timeout=2):
                fallback_btn.click()
                self.human_sleep('normal')
                return True
            else:
                w, h = self.d.window_size()
                logger.warning("兜底定位失败，尝试点击评论按钮常见区域坐标")
                self.human_click(int(w * 0.92), int(h * 0.63))
                self.human_sleep('normal')
                return True

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

        while swipe_count < max_swipes and reviewed_count < max_reviews:
            if hasattr(self, 'check_stop_callback'):
                self.check_stop_callback()

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

        logger.info("评论区处理完毕，关闭面板")
        return self._close_comment_section()

    def _process_current_screen_comments(self, processed_comments, ai_agent, video_title, keyword, remaining_reviews, custom_keywords=None):
        logger.info("正在解析当前屏幕可见评论...")
        text_nodes = self.d.xpath(L.COMMENT_TEXT_XPATH).all()
        custom_keywords = custom_keywords or []

        found_target = False
        should_break = False  # 守卫：发送失败也必须 break，避免状态污染后继续扫描
        reviewed_count = 0
        lead_info = None  # 保存意向评论的节点和文本（供 B.5 私信评论者使用）
        for node in text_nodes:
            text = node.info.get('text', '')
            if text and text not in processed_comments:
                processed_comments.add(text)
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

    def _send_comment_workflow(self, comment_node, text):
        """楼中楼回复 — 按 CS0→CS6 闭环实现，每阶段出口必须自证成功"""
        logger.info(f"回复内容: {text}")

        # === CS0 选中态守卫：节点 bounds 必须可获取 ===
        bounds = comment_node.info.get('bounds') if comment_node else None
        if not bounds:
            logger.warning("[CS0]评论节点无 bounds，跳过楼中楼回复")
            return False

        # === CS1 触发态：click 后必须出现"回复"提示词或可见 EditText ===
        try:
            comment_node.click()
            self.human_sleep('fast', custom_range=(0.8, 1.5))
        except Exception as exc:
            logger.warning(f"[CS1]点击评论节点失败: {exc}")
            return False

        has_reply_hint = any(
            self.d(text=hint).exists(timeout=0.3)
            for hint in ("回复", "回复评论")
        )
        has_edit_text = _find_bottom_edit_text(self.d, timeout=0.8) is not None
        if not (has_reply_hint or has_edit_text):
            logger.warning("[CS1]click 后未出现回复入口或输入框，状态未闭环")
            return False

        # === CS2 聚焦态：必须验证 EditText 真的出现 ===
        if not has_edit_text:
            if not self._focus_reply_input_verified():
                logger.warning("[CS2]未能聚焦楼中楼回复输入框")
                return False

        # === CS3 输入态：必须验证文本真的进了框 ===
        if not self._set_text_verified(text):
            logger.warning("[CS3]文本未可靠进入输入框")
            return False

        # === CS4 发送态 + CS5 验证态（由 _send_text_from_focused_input 内部完成） ===
        return _send_text_from_focused_input(self.d, text, "楼中楼回复")

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

        return _xpath_exists(self.d, L.COMMENT_NO_MORE_TEXT, timeout=0.2)

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


class CommentLeadPmAction(BaseAction):
    """B.5 楼中楼回复后私信评论者
    从已识别的意向评论节点反查评论者头像，进入评论者主页发送私信。
    前置：评论区必须处于打开状态（由 _run_comment_lead_safely 保证），lead_comment_node 有效。
    """
    def execute(self):
        # 从 self 读取 lead_comment_node（由 run_action 通过 kwargs setattr）
        lead_comment_node = getattr(self, 'lead_comment_node', None)
        if lead_comment_node is None:
            logger.warning("B.5 未提供意向评论节点，跳过楼中楼私信")
            return {"pm_sent": False, "reason": "no_lead_node"}

        # ① 从意向评论节点反查头像节点（同一 k4x 父容器下的 avatar）
        avatar_node = self._find_avatar_from_comment_node(lead_comment_node)
        if avatar_node is None:
            logger.warning("B.5 未能从意向评论节点反查到头像，跳过私信")
            return {"pm_sent": False, "reason": "avatar_not_found"}

        # ② 点击头像进入评论者主页
        if not self._enter_commenter_profile(avatar_node):
            logger.warning("B.5 进入评论者主页失败，跳过私信")
            return {"pm_sent": False, "reason": "enter_profile_failed"}

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
        """从意向评论 content 节点反查同卡片内的头像节点。
        dump 实测：comment_node（content）与 avatar 同属 k4x ViewGroup，是兄弟节点。
        """
        try:
            parent = comment_node.parent
            attempts = 0
            while parent is not None and attempts < 3:
                parent_info = parent.info or {}
                parent_rid = parent_info.get('resourceName', '') or parent_info.get('resource-id', '')
                if parent_rid == L.COMMENT_CARD_CONTAINER_ID:
                    avatar = parent.child(resourceId=L.COMMENTER_AVATAR_ID)
                    if avatar is not None and avatar.exists():
                        return avatar
                    break
                parent = parent.parent
                attempts += 1
        except Exception as exc:
            logger.debug(f"B.5 通过父容器反查头像失败: {exc}")

        # 兜底：全局查找 avatar 节点
        try:
            avatar = self.d.xpath(L.COMMENTER_AVATAR_XPATH)
            if avatar.exists(timeout=0.5):
                return avatar
        except Exception as exc:
            logger.debug(f"B.5 全局查找头像失败: {exc}")
        return None

    def _enter_commenter_profile(self, avatar_node):
        """点击头像进入评论者主页，并验证已进入 UserProfileActivity。"""
        try:
            bounds = avatar_node.info.get('bounds') if avatar_node else None
            if bounds:
                x = int((bounds.get('left', 0) + bounds.get('right', 0)) / 2)
                y = int((bounds.get('top', 0) + bounds.get('bottom', 0)) / 2)
                self.human_click(x, y, jitter_range=4)
            else:
                avatar_node.click()
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
        pm_btn = None
        try:
            btn = self.d.xpath(L.COMMENTER_PM_BTN_XPATH)
            if btn.exists(timeout=1.0):
                pm_btn = btn
                logger.info("B.5 通过 zbl 定位到评论者主页私信按钮")
        except Exception:
            pass

        # 兜底：通过图标 content-desc="私信" 取其可点击父容器
        if pm_btn is None:
            try:
                btn_parent = self.d.xpath(L.COMMENTER_PM_BTN_PARENT_XPATH)
                if btn_parent.exists(timeout=0.5):
                    pm_btn = btn_parent
                    logger.info("B.5 通过 zbk 父容器定位到评论者主页私信按钮")
            except Exception:
                pass

        # 最终兜底：直接用 PM_BTN_DESC（命中图标，靠 bounds 点击）
        if pm_btn is None:
            try:
                btn_desc = self.d.xpath(L.PM_BTN_DESC)
                if btn_desc.exists(timeout=0.5):
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
            # 兜底：检测 EditText
            if self.d.xpath(f'//{L.PM_EDIT_TEXT_CLASS}').exists(timeout=1.0):
                logger.info("B.5 已进入评论者私信聊天页（EditText 兜底）")
                return True
            logger.warning("B.5 点击私信按钮后未检测到聊天页")
            return False
        except Exception as exc:
            logger.warning(f"B.5 验证聊天页异常: {exc}")
            return False
