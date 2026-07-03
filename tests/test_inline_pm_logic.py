"""
MVP 两阶段架构单元测试（Phase A 扫描收集 + Phase B 逐条回复）
目标：验证 ProcessCommentSectionAction.execute 在 MVP 改造后：
  1) 默认 max_intent=1 时向后兼容（reply → lead → B.5）
  2) max_intent>1 时先收集全部再全部回复，0 次离开评论区
  3) 回复失败时不中断后续回复
  4) 无意向评论时正确触发兜底
"""
import sys
import os
import unittest
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dy.actions.commenting import ProcessCommentSectionAction


# ── Phase 3 helpers for testing ────────────────────────────
# These are module-level functions imported for unit testing
from dy.actions.commenting import _refind_comment_node_by_text, _escape_xpath_text


class FakeNode:
    """模拟一个 UI 节点。"""
    def __init__(self, text="", bounds=None):
        self.text = text
        self._bounds = bounds or {"left": 0, "top": 0, "right": 100, "bottom": 100}

    @property
    def info(self):
        return {
            "text": self.text,
            "bounds": self._bounds,
            "visibleToUser": True,
            "enabled": True,
            "clickable": True,
        }

    def click(self):
        pass

    def parent(self):
        return None


class FakeDevice:
    """最小化的设备 mock，只响应用到的属性。"""
    def __init__(self):
        self._window_size = (1080, 1920)

    def window_size(self):
        return self._window_size

    def press(self, key):
        pass

    def click(self, x, y):
        pass

    def xpath(self, xp):
        return FakeXPathSelector(self, xp)

    def __call__(self, **kwargs):
        return FakeSelector(self, kwargs)


class FakeXPathSelector:
    def __init__(self, d, xp):
        self.d = d
        self.xp = xp
        self._all = []

    def all(self):
        return self._all

    def wait(self, timeout=0):
        return False

    def exists(self, timeout=0):
        return False


class FakeSelector:
    def __init__(self, d, kwargs):
        self.d = d
        self.kwargs = kwargs

    def exists(self, timeout=0):
        return False


class MockedProcessCommentSectionAction(ProcessCommentSectionAction):
    """重载 Phase A/B 核心方法，仅保留状态机。"""

    def __init__(self, config, comments=None, intent_indices=None, reply_success=True):
        self.d = FakeDevice()
        self.app = None
        self.config = config
        self.comments = comments or []
        self.intent_indices = set(intent_indices or [])
        self.reply_success = reply_success
        self._swipe_count_internal = 0
        self._closed = False

    # ── Phase A ──────────────────────────────────────────────
    def _collect_intent_comments(self, processed_comments, ai_agent, video_title,
                                  keyword, remaining_reviews, custom_keywords=None,
                                  max_to_collect=1, self_nick="",
                                  skip_first_comment=False):
        items = []
        reviewed = 0
        for idx, text in enumerate(self.comments):
            author = f"user_{idx}"
            dedup_key = f"{author}\x01{text}" if author else text
            if dedup_key in processed_comments:
                continue
            processed_comments.add(dedup_key)
            reviewed += 1
            if idx in self.intent_indices:
                items.append({
                    "text": text,
                    "author": author,
                    "reply_text": f"回复: {text}",
                })
                if len(items) >= max_to_collect:
                    break
            if reviewed >= remaining_reviews:
                break
        return items, reviewed

    # ── Phase B ──────────────────────────────────────────────
    def _send_comment_workflow(self, comment_node, text):
        return self.reply_success

    # ── Scrolling / UI ───────────────────────────────────────
    def _swipe_up_comments(self):
        if self._swipe_count_internal < 1:
            self._swipe_count_internal += 1
            return True
        return False

    def _close_comment_section(self):
        self._closed = True
        return True

    def _comment_panel_open(self):
        return not self._closed

    # ── Guard override: no-op (no real deadline in tests) ───
    def _guard(self):
        pass

    def human_sleep(self, sleep_type='normal', custom_range=None):
        pass  # no-op in tests


def _make_fake_node_for(text):
    """Return a FakeNode if text is in comments list, else None."""
    def _finder(d, t):
        return FakeNode(text=t)
    return _finder


class TestMvpTwoPhase(unittest.TestCase):
    def _base_config(self, max_intent=1):
        return {
            "interaction": {
                "max_comment_swipes": 2,
                "max_ai_comment_reviews": 20,
                "max_intent_comments_per_video": max_intent,
                "fallback_top_comment_count": 5,
                "lead_pm_message_list": ["你好"],
            }
        }

    # ── 1. 默认 max_intent=1：向后兼容，回复第一条 → B.5 私信第一条 ──
    @patch('dy.actions.commenting._refind_comment_node_by_text')
    def test_default_max_intent_1(self, mock_refind):
        """max_intent=1 收集 1 条 → 回复 1 条 → lead 指向第一条，供 B.5。

        Issue 1 后：execute() 恒返回 False 且关闭评论区；lead_* 状态在关闭前已设置，
        供 task_runner 的 Phase 2 私信循环使用。
        """
        config = self._base_config(max_intent=1)
        action = MockedProcessCommentSectionAction(
            config,
            comments=["这条评论想买"],
            intent_indices=[0],
            reply_success=True,
        )
        mock_refind.return_value = FakeNode(text="这条评论想买")
        action.keep_open_after_lead = True  # Issue 1 后即使设 True 也不再保留评论区
        result = action.execute()

        self.assertTrue(action.lead_reply_sent)
        self.assertIsNotNone(action.lead_comment_node)
        self.assertEqual(action.lead_comment_text, "这条评论想买")
        self.assertEqual(action.lead_reply_text, "回复: 这条评论想买")
        self.assertEqual(action.intent_processed_count, 1)
        self.assertFalse(action.inline_pm_completed)  # MVP 不使用内联私信
        self.assertFalse(result)                      # Issue 1: 恒返回 False
        self.assertTrue(action._closed)               # Issue 1: 关闭评论区

    # ── 2. max_intent>1：收集全部意向 → 全部回复 ──
    @patch('dy.actions.commenting._refind_comment_node_by_text')
    def test_multi_intent_collects_and_replies_all(self, mock_refind):
        """max_intent=3 扫描收集 3 条 → 逐条回复 3 条。"""
        config = self._base_config(max_intent=3)
        action = MockedProcessCommentSectionAction(
            config,
            comments=["想买", "怎么买", "价格多少", "路人评论"],
            intent_indices=[0, 1, 2],
            reply_success=True,
        )
        mock_refind.return_value = FakeNode(text="mock")
        action.keep_open_after_lead = True
        action.execute()

        self.assertEqual(action.intent_processed_count, 3)
        self.assertTrue(action.lead_reply_sent)
        # lead 指向第一条成功回复
        self.assertEqual(action.lead_comment_text, "想买")

    # ── 3. max_intent>1：lead 始终指向第一条成功回复 ──
    @patch('dy.actions.commenting._refind_comment_node_by_text')
    def test_first_lead_preserved_for_b5(self, mock_refind):
        """多条意向回复中，lead_* 来自第一条成功回复。"""
        config = self._base_config(max_intent=3)
        action = MockedProcessCommentSectionAction(
            config,
            comments=["A-comment", "B-comment", "C-comment"],
            intent_indices=[0, 1, 2],
            reply_success=True,
        )
        mock_refind.return_value = FakeNode(text="mock")
        action.keep_open_after_lead = True
        action.execute()

        self.assertEqual(action.lead_comment_text, "A-comment")
        self.assertEqual(action.lead_reply_text, "回复: A-comment")
        self.assertEqual(action.intent_processed_count, 3)

    # ── 4. 部分回复失败：失败的跳过，成功的继续，lead 取第一条成功 ──
    @patch('dy.actions.commenting._refind_comment_node_by_text')
    def test_reply_failure_skips_and_continues(self, mock_refind):
        """第一条回复失败、第二条成功时，lead 来自第二条。"""
        config = self._base_config(max_intent=3)
        # reply_success=False → 所有回复都失败
        # 我们需要更精细的控制。改为子类重写 _send_comment_workflow
        class ActionWithSelectiveFail(MockedProcessCommentSectionAction):
            def _send_comment_workflow(self, node, text):
                # 第一条失败，其余成功
                if "first-fail" in text:
                    return False
                return True

        action = ActionWithSelectiveFail(
            config,
            comments=["first-fail-item", "second-ok-item", "third-ok-item"],
            intent_indices=[0, 1, 2],
        )
        mock_refind.return_value = FakeNode(text="mock")
        action.keep_open_after_lead = True
        action.execute()

        # 第一条失败，第二条和第三条成功 → lead 来自第二条
        self.assertEqual(action.intent_processed_count, 2)
        self.assertEqual(action.lead_comment_text, "second-ok-item")
        self.assertTrue(action.lead_reply_sent)

    # ── 5. 全部回复失败：lead 为 None → 触发兜底 ──
    @patch('dy.actions.commenting._refind_comment_node_by_text')
    def test_all_replies_fail_fallback_triggers(self, mock_refind):
        """全部意图回复都失败 → lead_comment_node=None → 兜底。"""
        config = self._base_config(max_intent=2)

        fallback_called = {"called": False}

        class ActionAllFail(MockedProcessCommentSectionAction):
            def _send_comment_workflow(self, node, text):
                return False

            def _fallback_reply_and_dm_top_comments(self, ai_agent, video_title, keyword, max_count=5, do_dm=False):
                fallback_called["called"] = True
                self.lead_reply_fallback_count = 1
                return 1

        action = ActionAllFail(
            config,
            comments=["买一个", "怎么卖"],
            intent_indices=[0, 1],
        )
        mock_refind.return_value = FakeNode(text="mock")
        action.keep_open_after_lead = True
        action.execute()

        self.assertEqual(action.intent_processed_count, 0)
        self.assertIsNone(action.lead_comment_node)
        self.assertTrue(fallback_called["called"])

    # ── 6. 无意向评论 → 兜底 ──
    def test_no_intent_triggers_fallback(self):
        """评论列表中无意向评论 → 兜底触发。"""
        config = self._base_config(max_intent=2)

        fallback_called = {"called": False}

        class ActionNoIntent(MockedProcessCommentSectionAction):
            def _fallback_reply_and_dm_top_comments(self, ai_agent, video_title, keyword, max_count=5, do_dm=False):
                fallback_called["called"] = True
                fallback_called["do_dm"] = do_dm
                self.lead_reply_fallback_count = 1
                return 1

        action = ActionNoIntent(
            config,
            comments=["路人1", "路人2"],
            intent_indices=[],  # 无意向
        )
        action.keep_open_after_lead = True
        action.execute()

        self.assertTrue(fallback_called["called"])
        self.assertTrue(fallback_called["do_dm"])
        self.assertEqual(action.lead_comment_text, "fallback")

    # ── 7. 有意向评论并成功回复 → 不触发兜底 ──
    @patch('dy.actions.commenting._refind_comment_node_by_text')
    def test_no_fallback_after_successful_replies(self, mock_refind):
        """收集并回复意向后，不应触发兜底。"""
        config = self._base_config(max_intent=2)

        fallback_called = {"called": False}

        class ActionWithFallback(MockedProcessCommentSectionAction):
            def _fallback_reply_and_dm_top_comments(self, ai_agent, video_title, keyword, max_count=5, do_dm=False):
                fallback_called["called"] = True
                return 0

        action = ActionWithFallback(
            config,
            comments=["想买", "怎么买"],
            intent_indices=[0, 1],
        )
        mock_refind.return_value = FakeNode(text="mock")
        action.keep_open_after_lead = True
        action.execute()

        self.assertFalse(fallback_called["called"])
        self.assertEqual(action.intent_processed_count, 2)

    # ── 8. 文本重定位失败 → 跳过该条，继续后续 ──
    @patch('dy.actions.commenting._refind_comment_node_by_text')
    def test_node_not_found_skipped(self, mock_refind):
        """_refind_comment_node_by_text 返回 None → 跳过，后续继续。"""
        config = self._base_config(max_intent=3)

        # 第一条找不到节点，第二、三条正常
        call_count = [0]

        def selective_refind(d, text, author=""):
            call_count[0] += 1
            if call_count[0] == 1:
                return None  # 第一条找不到
            return FakeNode(text=text)

        mock_refind.side_effect = selective_refind

        action = MockedProcessCommentSectionAction(
            config,
            comments=["消失的评论", "可见评论B", "可见评论C"],
            intent_indices=[0, 1, 2],
            reply_success=True,
        )
        action.keep_open_after_lead = True
        action.execute()

        # 第一条跳过（节点不可见），第二条和第三条成功
        self.assertEqual(action.intent_processed_count, 2)
        # lead 来自第一条成功回复（即第二条）
        self.assertEqual(action.lead_comment_text, "可见评论B")

    # ── 9. max_intent=1 + 回复失败 → lead_* 全空 → 兜底 ──
    @patch('dy.actions.commenting._refind_comment_node_by_text')
    def test_max_intent_1_reply_failure(self, mock_refind):
        """max_intent=1 回复失败 → lead 为空 → 兜底。"""
        config = self._base_config(max_intent=1)

        fallback_called = {"called": False}

        class ActionFail(MockedProcessCommentSectionAction):
            def _send_comment_workflow(self, node, text):
                return False

            def _fallback_reply_and_dm_top_comments(self, ai_agent, video_title, keyword, max_count=5, do_dm=False):
                fallback_called["called"] = True
                self.lead_reply_fallback_count = 1
                return 1

        action = ActionFail(
            config,
            comments=["想买"],
            intent_indices=[0],
        )
        mock_refind.return_value = FakeNode(text="想买")
        action.keep_open_after_lead = True
        action.execute()

        self.assertEqual(action.intent_processed_count, 0)
        self.assertIsNone(action.lead_comment_node)
        self.assertTrue(action.lead_reply_sent)  # fallback 触发后会置为 True
        self.assertTrue(fallback_called["called"])

    # ── 10. 停止检查粒度：_collect_intent_comments 每条意向后应过 _guard() ──
    @patch('dy.actions.commenting.DYReplyAgent')
    @patch('dy.actions.commenting._refind_comment_node_by_text')
    def test_stop_check_granularity_in_collect(self, mock_refind, MockAgent):
        """真实 _collect_intent_comments 在每条评论后必须调用 _guard()。
        直接继承 ProcessCommentSectionAction（不经过 MockedProcessCommentSectionAction），
        以确保使用真实的 _collect_intent_comments 实现。
        """
        config = self._base_config(max_intent=3)

        # Mock AI agent：所有评论都判为意向
        mock_ai = MagicMock()
        mock_ai.is_intent_comment.return_value = True
        mock_ai.generate_lead_reply.return_value = "回复文本"
        MockAgent.return_value = mock_ai

        guard_calls = []

        class ActionRealCollect(ProcessCommentSectionAction):
            """直接继承真实类，使用真实的 _collect_intent_comments。"""
            def __init__(self):
                self.d = FakeDevice()
                self.app = None
                self.config = config
                self._closed = False

            def _guard(self):
                guard_calls.append("guard")

            def _send_comment_workflow(self, node, text):
                return True

            def _swipe_up_comments(self):
                return False  # 不需要滑动

            def _close_comment_section(self):
                self._closed = True
                return True

            def _comment_panel_open(self):
                return not self._closed

            def human_sleep(self, *args, **kwargs):
                pass

        action = ActionRealCollect()
        action.keep_open_after_lead = True
        mock_refind.return_value = FakeNode(text="mock")

        # 构造 FakeNode 列表模拟 xpath.all()
        fake_nodes = [FakeNode(text=f"想买{i}") for i in range(5)]

        class FakeXPathWithNodes:
            def __init__(self, nodes):
                self._nodes = nodes
            def all(self):
                return self._nodes

        action.d.xpath = MagicMock(return_value=FakeXPathWithNodes(fake_nodes))

        action.execute()

        # 5 条评论，max_intent=3 → 收集 3 条，每条之后调 _guard()
        # 加上 Phase B 的 _guard() 调用，总数应 ≥ 3
        self.assertGreaterEqual(
            len(guard_calls), 3,
            f"_collect_intent_comments 应在每条评论的 AI 判断后调用 _guard()，"
            f"实际调用 {len(guard_calls)} 次"
        )

    # ── 11. processed_comments 使用字符串去重键格式 ──
    def test_processed_comments_use_string_dedup_keys(self):
        """验证 mock 的 processed_comments 使用与真实代码一致的 f"{author}\\x01{text}" 格式。"""
        config = self._base_config(max_intent=3)

        action = MockedProcessCommentSectionAction(
            config,
            comments=["想买", "怎么买", "路人"],
            intent_indices=[0, 1],
            reply_success=True,
        )
        action.keep_open_after_lead = True

        with patch('dy.actions.commenting._refind_comment_node_by_text',
                   return_value=FakeNode(text="mock")):
            action.execute()

        # Mock 的 _collect_intent_comments 现在使用字符串去重键
        # 验证（间接：通过 execute 不抛异常间接确认键格式正确）
        self.assertEqual(action.intent_processed_count, 2,
            "使用字符串去重键不应影响意向评论收集和回复的正确性")

    # ═══════════════════════════════════════════════════════════════
    # Phase 2 tests — intent_items 暴露 + 多私信循环
    # ═══════════════════════════════════════════════════════════════

    # ── 12. intent_items 暴露给 task_runner ──
    @patch('dy.actions.commenting._refind_comment_node_by_text')
    def test_intent_items_exposed_after_execute(self, mock_refind):
        """execute() 完成后 self.intent_items 应包含所有收集到的意向评论。"""
        config = self._base_config(max_intent=3)
        action = MockedProcessCommentSectionAction(
            config,
            comments=["A-想买", "B-怎么买", "C-价格多少", "路人"],
            intent_indices=[0, 1, 2],
            reply_success=True,
        )
        mock_refind.return_value = FakeNode(text="mock")
        action.keep_open_after_lead = True
        action.execute()

        items = getattr(action, 'intent_items', None)
        self.assertIsNotNone(items, "execute() 应设置 self.intent_items 供 task_runner 使用")
        self.assertEqual(len(items), 3)
        self.assertEqual(items[0]["text"], "A-想买")
        self.assertEqual(items[1]["text"], "B-怎么买")
        self.assertEqual(items[2]["text"], "C-价格多少")
        # 验证每条包含必要字段
        for item in items:
            self.assertIn("text", item)
            self.assertIn("author", item)
            self.assertIn("reply_text", item)

    # ── 13. intent_items 为空列表（无意向评论） ──
    def test_intent_items_empty_when_no_intents(self):
        """无意向评论时 intent_items 应为空列表，非 None。"""
        config = self._base_config(max_intent=3)

        fallback_called = {"called": False}

        class ActionNoIntents(MockedProcessCommentSectionAction):
            def _fallback_reply_and_dm_top_comments(self, *args, **kwargs):
                fallback_called["called"] = True
                self.lead_reply_fallback_count = 1
                return 1

        action = ActionNoIntents(
            config,
            comments=["路人1", "路人2"],
            intent_indices=[],  # 无意向
        )
        action.keep_open_after_lead = True
        action.execute()

        items = getattr(action, 'intent_items', None)
        self.assertIsNotNone(items, "即使无意向，intent_items 也应为空列表（非 None）")
        self.assertEqual(len(items), 0)
        self.assertTrue(fallback_called["called"])

    # ── 14. intent_items 在回复失败后仍保留 ──
    @patch('dy.actions.commenting._refind_comment_node_by_text')
    def test_intent_items_preserved_after_reply_failure(self, mock_refind):
        """即使部分或全部回复失败，intent_items 仍保留完整收集列表。"""
        config = self._base_config(max_intent=3)

        class ActionSomeFail(MockedProcessCommentSectionAction):
            def _send_comment_workflow(self, node, text):
                # 第一条失败，其余成功
                return "A" not in text

        action = ActionSomeFail(
            config,
            comments=["A-失败", "B-成功", "C-成功"],
            intent_indices=[0, 1, 2],
        )
        mock_refind.return_value = FakeNode(text="mock")
        action.keep_open_after_lead = True
        action.execute()

        items = getattr(action, 'intent_items', None)
        self.assertIsNotNone(items)
        # 收集到的 3 条应全部保留，不受回复成败影响
        self.assertEqual(len(items), 3)
        self.assertEqual(action.intent_processed_count, 2)

    # ═══════════════════════════════════════════════════════════════
    # Phase 3 tests — 文本重定位精度增强 + 全链路可观测
    # ═══════════════════════════════════════════════════════════════

    # ── 15. _refind_comment_node_by_text 添加 author 参数 ──
    def test_refind_by_text_accepts_author_parameter(self):
        """_refind_comment_node_by_text 应接受可选 author 参数用于交叉验证。"""
        import inspect
        sig = inspect.signature(_refind_comment_node_by_text)
        params = list(sig.parameters.keys())
        self.assertIn("author", params,
            f"_refind_comment_node_by_text 应支持 author 参数用于卡片级验证，"
            f"当前参数: {params}")

    # ── 16. Phase B 完成后滚动评论区到顶部 ──
    @patch('dy.actions.commenting._refind_comment_node_by_text')
    def test_phase_b_scrolls_comments_to_top(self, mock_refind):
        """Phase B 回复完成后应统一滑动评论区回顶部，为 Phase 2 私信提供一致起始位置。"""
        config = self._base_config(max_intent=2)

        scroll_calls = []

        class ActionTrackScroll(MockedProcessCommentSectionAction):
            def _scroll_comments_to_top(self):
                scroll_calls.append("scrolled")

        action = ActionTrackScroll(
            config,
            comments=["想买", "怎么买"],
            intent_indices=[0, 1],
            reply_success=True,
        )
        mock_refind.return_value = FakeNode(text="mock")
        action.keep_open_after_lead = True
        action.execute()

        self.assertGreaterEqual(len(scroll_calls), 1,
            "Phase B 完成后应调用 _scroll_comments_to_top() 复位评论区位置")

    # ── 17. 全链路可观测：Phase A/B 耗时日志 ──
    @patch('dy.actions.commenting._refind_comment_node_by_text')
    def test_metrics_timing_logged(self, mock_refind):
        """各阶段应输出 [metrics] 耗时和成功率日志。"""
        config = self._base_config(max_intent=2)

        import logging
        from dy.actions.commenting import ProcessCommentSectionAction as PCA

        action = MockedProcessCommentSectionAction(
            config,
            comments=["A-想买", "B-怎么买"],
            intent_indices=[0, 1],
            reply_success=True,
        )
        mock_refind.return_value = FakeNode(text="mock")
        action.keep_open_after_lead = True

        with self.assertLogs(logger='dy.actions.commenting', level='INFO') as log_ctx:
            action.execute()

        # 检查 [metrics] 日志行
        metrics_lines = [r for r in log_ctx.output if '[metrics]' in r]
        self.assertGreaterEqual(len(metrics_lines), 2,
            f"应至少输出 Phase A 和 Phase B 的 [metrics] 日志，"
            f"实际 metrics 行数: {len(metrics_lines)}")
        # 验证 Phase A 指标
        phase_a_lines = [l for l in metrics_lines if 'Phase A' in l]
        self.assertGreaterEqual(len(phase_a_lines), 1,
            "应包含 Phase A 收集耗时和数量指标")
        # 验证 Phase B 指标
        phase_b_lines = [l for l in metrics_lines if 'Phase B' in l]
        self.assertGreaterEqual(len(phase_b_lines), 1,
            "应包含 Phase B 回复成功/失败指标")

    # ═══════════════════════════════════════════════════════════════
    # 回归测试 — 自己的评论不能作为意向评论
    # ═══════════════════════════════════════════════════════════════

    # ── 18. 自己的评论被 _collect_intent_comments 排除 ──
    @patch('dy.actions.commenting._xpath_exists', return_value=False)
    def test_self_comment_excluded_from_intent_collection(self, _mock_xp):
        """自己的评论不应被 _collect_intent_comments 收集为意向评论。

        复现条件：
        - B.3 先发了自己的评论（如"有兴趣私信我"）
        - B.4 Phase A 扫描时自己的评论仍在列表中
        - 自己的评论可能命中意向关键词（如"私信"）
        - 期望：自己的评论被 self_nickname 过滤排除
        """
        config = {
            "interaction": {
                "self_nickname": "我的账号",
                "max_comment_swipes": 2,
                "max_ai_comment_reviews": 20,
                "max_intent_comments_per_video": 3,
                "fallback_top_comment_count": 5,
            }
        }

        # 使用真实 _collect_intent_comments，仅 mock 设备依赖
        class RealCollectAction(ProcessCommentSectionAction):
            """保留真实 _collect_intent_comments，仅 mock 设备层。"""
            def __init__(self):
                self.d = FakeDevice()
                self.app = None
                self.config = config
                self.video_title = "测试视频"
                self.keyword = "测试"
                self._card_elem_cache = None

            def _get_comment_author_from_node(self, node):
                return getattr(node, '_test_author', '')

            def _get_card_elem_from_text_node(self, node):
                return getattr(node, '_test_card_elem', None)

            def _card_is_pinned_or_author(self, card_elem):
                return bool(card_elem)

            def _guard(self):
                pass

        action = RealCollectAction()

        # 构造评论节点：第 0 条 = 自己的评论，第 1 条 = 真实意向评论
        self_node = FakeNode(text="有兴趣私信我了解")
        self_node._test_author = "我的账号"
        self_node._test_card_elem = {"badge": "作者"}  # 带"作者"标记

        other_node = FakeNode(text="怎么买 多少钱")
        other_node._test_author = "路人甲"
        other_node._test_card_elem = None

        # Mock xpath 返回这两个节点
        original_xpath = action.d.xpath

        class PatchedDevice(FakeDevice):
            def xpath(self_d, xp):
                sel = FakeXPathSelector(self_d, xp)
                if 'k4x' in xp or 'COMMENT_CARD' in xp or 'TextView' in xp:
                    sel._all = [self_node, other_node]
                return sel

        action.d = PatchedDevice()

        # Mock AI agent
        ai = MagicMock()
        ai.is_intent_comment.return_value = True
        ai.generate_lead_reply.return_value = "请查看主页了解详情"

        items, reviewed = action._collect_intent_comments(
            set(), ai, "视频标题", "关键词", 20, [], 3
        )

        # 断言：自己的评论被排除，只收集到路人甲的评论
        self.assertEqual(len(items), 1,
            f"应排除自己的评论，实际收集了 {len(items)} 条: {[i['text'] for i in items]}")
        self.assertEqual(items[0]["text"], "怎么买 多少钱")
        self.assertEqual(items[0]["author"], "路人甲")
        self.assertGreaterEqual(reviewed, 1, "至少路人甲的评论被评审过（自己的评论在评审前就被排除）")

    # ── 19. Phase B 兜底自过滤：即使 Phase A 漏过，Phase B 也要拦截 ──
    @patch('dy.actions.commenting._refind_comment_node_by_text')
    def test_phase_b_defensive_filter_blocks_own_comment(self, mock_refind):
        """Phase B 在回复前检查 item.author == self_nick，拦截自己的评论。
        模拟 Phase A 自过滤失效（self_nick=""），Phase B 仍能兜底拦截。
        """
        config = self._base_config(max_intent=3)
        # 不配置 self_nickname → Phase A 自过滤不生效
        # 但 Phase B 兜底过滤应该拦截

        class ActionBypassPhaseA(MockedProcessCommentSectionAction):
            """模拟 Phase A 自过滤被绕过的场景。"""
            def _collect_intent_comments(self, processed_comments, ai_agent, video_title,
                                          keyword, remaining_reviews, custom_keywords=None,
                                          max_to_collect=1, self_nick="",
                                          skip_first_comment=False):
                # 模拟 Phase A Bug：自己的评论被收集了
                items = []
                for idx, text in enumerate(self.comments):
                    author = f"user_{idx}"
                    # 故意把 idx=0 标记为 self（即使 Phase A 没过滤掉）
                    if idx == 0:
                        author = "我的账号"  # 模拟自己的账号名
                    if idx in self.intent_indices:
                        items.append({
                            "text": text,
                            "author": author,
                            "reply_text": f"回复: {text}",
                        })
                        if len(items) >= max_to_collect:
                            break
                return items, len(self.comments)

        # Mock _resolve_self_nickname 返回 "我的账号"
        class ActionWithSelfNick(ActionBypassPhaseA):
            def _resolve_self_nickname(self):
                return "我的账号"

        action = ActionWithSelfNick(
            config,
            comments=["我的主评（自己发的）", "路人-想买"],
            intent_indices=[0, 1],  # 自己的评论被 AI 判为意向
            reply_success=True,
        )
        mock_refind.return_value = FakeNode(text="mock")
        action.keep_open_after_lead = True
        action.execute()

        # 自己的评论(id=0)被 Phase B 拦截，只回复了路人的评论
        self.assertEqual(action.intent_processed_count, 1,
            "Phase B 应拦截自己的评论，只处理路人评论")
        self.assertEqual(action.lead_comment_text, "路人-想买",
            "lead 应指向路人评论，而非自己的评论")

    # ── 20. _resolve_self_nickname 从 config 读取 ──
    def test_resolve_self_nickname_from_config(self):
        """_resolve_self_nickname 优先从 interaction.self_nickname 读取。"""
        config = {"interaction": {"self_nickname": "测试账号123"}}
        action = MockedProcessCommentSectionAction(config, comments=[], intent_indices=[])
        nick = action._resolve_self_nickname()
        self.assertEqual(nick, "测试账号123")

    # ── 21. _resolve_self_nickname 返回空字符串（config + UI 都无） ──
    def test_resolve_self_nickname_returns_empty(self):
        """_resolve_self_nickname 无 config 且 UI 检测失败时返回 ""。"""
        config = {"interaction": {}}  # 无 self_nickname
        action = MockedProcessCommentSectionAction(config, comments=[], intent_indices=[])
        nick = action._resolve_self_nickname()
        self.assertEqual(nick, "")


class TestPhase2Resilience(unittest.TestCase):
    """Phase 2 多私信循环容错性 — 单条 PM 失败不应放弃后续意向评论。"""

    @patch('dy.task_runner.ProcessCommentSectionAction')
    def test_recovery_failure_continues_loop(self, mock_process_action):
        """Phase 2: 第 2 条私信失败时，第 3 条仍应被尝试。

        复现场景（Issue 2 独立 PM 循环）：
        - intent_items = [评论1, 评论2, 评论3]
        - 评论1 PM 成功 → _recover_after_comment_pm 恢复
        - 评论2 PM 失败 (pm_btn_not_found) → _recover_after_comment_pm 仍恢复
        - 期望: 评论3 仍然被尝试（而非 break 丢弃）
        """
        import dy.task_runner as tr
        from dy.actions.commenting import OpenCommentSectionAction, CommentLeadPmAction

        intent_items = [
            {"text": "意向评论1", "author": "u1"},
            {"text": "意向评论2", "author": "u2"},
            {"text": "意向评论3", "author": "u3"},
        ]

        # Mock ProcessCommentSectionAction: succeed B.4, provide intent_items
        mock_action_inst = MagicMock()
        mock_action_inst.lead_reply_sent = True
        mock_action_inst.lead_comment_text = "comment1"
        mock_action_inst.lead_reply_text = "reply1"
        mock_action_inst.lead_comment_node = "node"
        mock_action_inst.intent_items = intent_items
        mock_action_inst.inline_pm_completed = False
        mock_action_inst.lead_pm_sent_count = 0
        mock_action_inst.lead_reply_fallback_count = 0
        mock_action_inst.perform = MagicMock(return_value=True)
        mock_process_action.return_value = mock_action_inst

        # runner.run_action 派发：OpenCommentSectionAction 总成功；
        # CommentLeadPmAction 第 2 条失败，其余成功
        pm_calls = []

        def run_action_side_effect(action_cls, **kwargs):
            if action_cls is OpenCommentSectionAction:
                return True
            if action_cls is CommentLeadPmAction:
                text = kwargs.get("lead_comment_text", "")
                pm_calls.append(text)
                if text == "意向评论2":
                    return {"pm_sent": False, "reason": "pm_btn_not_found"}
                return {"pm_sent": True, "reason": "ok"}
            return False

        # Build minimal TikTokTaskFlow
        tf = tr.TikTokTaskFlow.__new__(tr.TikTokTaskFlow)
        tf.is_stopped = False
        tf.is_paused = False
        tf.config = {
            "interaction": {
                "lead_pm_message_list": ["test msg"],
                "max_intent_comments_per_video": 3,
                "fallback_top_comment_count": 5,
            },
            "crawler": {"max_seconds_per_video": 90},
        }
        tf.runner = MagicMock()
        tf.runner.device = MagicMock()
        tf.runner.app_mgr = MagicMock()
        tf.runner.run_action = MagicMock(side_effect=run_action_side_effect)
        tf._check_stop = MagicMock()
        tf._recover_to_video_page = MagicMock(return_value=True)
        tf._dismiss_video_context_menu_if_present = MagicMock()
        tf._resource_exists = MagicMock(return_value=False)
        tf._detect_page_state = MagicMock(return_value="video_page")
        tf._is_video_page_ready = MagicMock(return_value=True)
        tf._reset_and_reenter_video_flow = MagicMock(return_value=True)
        tf.db = MagicMock()
        tf.reply_agent = MagicMock()
        tf.anti = MagicMock()

        # Execute
        tr.TikTokTaskFlow._run_comment_lead_safely(
            tf, "title", "keyword",
            enable_lead_pm=True,
            video_started_at=None,
            already_open=True,
        )

        # Assert: all 3 PM actions were attempted
        self.assertEqual(len(pm_calls), 3,
            f"Phase 2 应处理全部 3 条意向评论，实际只调用了 {len(pm_calls)} 条"
            f" 的 run_action(CommentLeadPmAction)。如果 break → 第 3 条丢失。")
        self.assertEqual(pm_calls, ["意向评论1", "意向评论2", "意向评论3"],
            f"应按顺序处理 3 条意向，实际 {pm_calls}")


# ═══════════════════════════════════════════════════════════════
# Issue 1: keep_open_after_lead=False — Phase B 后总是关闭评论区
# ═══════════════════════════════════════════════════════════════
class TestIssue1CloseAfterPhaseB(unittest.TestCase):
    """Issue 1: execute() 在 Phase B 完成后总是关闭评论区并恒返回 False。"""

    def _base_config(self, max_intent=1):
        return {
            "interaction": {
                "max_comment_swipes": 2,
                "max_ai_comment_reviews": 20,
                "max_intent_comments_per_video": max_intent,
                "fallback_top_comment_count": 5,
                "lead_pm_message_list": ["你好"],
            }
        }

    @patch('dy.actions.commenting._refind_comment_node_by_text')
    def test_execute_closes_panel_and_returns_false_when_lead_succeeds(self, mock_refind):
        """有成功回复时，execute() 仍关闭评论区且返回 False（不再 keep_open）。"""
        config = self._base_config(max_intent=1)
        action = MockedProcessCommentSectionAction(
            config,
            comments=["这条评论想买"],
            intent_indices=[0],
            reply_success=True,
        )
        mock_refind.return_value = FakeNode(text="这条评论想买")
        # 即使显式设 True，Issue 1 后也不再保留评论区
        action.keep_open_after_lead = True
        result = action.execute()

        self.assertTrue(action._closed, "Phase B 后应关闭评论区")
        self.assertFalse(result, "execute() 应恒返回 False")
        self.assertTrue(action.lead_reply_sent, "lead_reply_sent 仍应被设置")

    def test_execute_returns_false_and_closes_when_fallback_triggers(self):
        """无意向 → 兜底触发时，execute() 也关闭评论区并返回 False。"""
        config = self._base_config(max_intent=2)

        class ActionNoIntent(MockedProcessCommentSectionAction):
            def _fallback_reply_and_dm_top_comments(self, *args, **kwargs):
                self.lead_reply_fallback_count = 1
                return 1

        action = ActionNoIntent(config, comments=["路人1", "路人2"], intent_indices=[])
        action.keep_open_after_lead = True
        result = action.execute()

        self.assertTrue(action._closed, "兜底后应关闭评论区")
        self.assertFalse(result, "兜底路径 execute() 应返回 False")
        self.assertTrue(action.lead_reply_sent, "fallback 应设置 lead_reply_sent")


class TestIssue1TaskRunnerPassesFalse(unittest.TestCase):
    """Issue 1: task_runner 始终传 keep_open_after_lead=False（即使 enable_lead_pm=True）。"""

    @patch('dy.task_runner.CommentLeadPmAction')
    @patch('dy.task_runner.ProcessCommentSectionAction')
    @patch('dy.task_runner.OpenCommentSectionAction')
    def test_task_runner_always_passes_keep_open_false(self, mock_open_action, mock_process_action, mock_pm_class):
        """enable_lead_pm=True 时，ProcessCommentSectionAction 仍收到 keep_open_after_lead=False。"""
        import dy.task_runner as tr

        mock_action_inst = MagicMock()
        mock_action_inst.lead_reply_sent = True
        mock_action_inst.lead_comment_node = "node"
        mock_action_inst.lead_comment_text = "t"
        mock_action_inst.lead_reply_text = "r"
        mock_action_inst.intent_items = []  # 空 → 不进 Phase 2 循环
        mock_action_inst.inline_pm_completed = False
        mock_action_inst.lead_pm_sent_count = 0
        mock_action_inst.lead_reply_fallback_count = 0
        mock_action_inst.perform = MagicMock(return_value=True)
        mock_process_action.return_value = mock_action_inst

        tf = tr.TikTokTaskFlow.__new__(tr.TikTokTaskFlow)
        tf.is_stopped = False
        tf.is_paused = False
        tf.config = {
            "interaction": {"lead_pm_message_list": ["m"], "max_intent_comments_per_video": 1},
            "crawler": {"max_seconds_per_video": 90},
        }
        tf.runner = MagicMock()
        tf.runner.device = MagicMock()
        tf.runner.app_mgr = MagicMock()
        tf.runner.run_action = MagicMock(return_value=False)
        tf._check_stop = MagicMock()
        tf._recover_to_video_page = MagicMock(return_value=True)
        tf._dismiss_video_context_menu_if_present = MagicMock()
        tf._resource_exists = MagicMock(return_value=False)
        tf._detect_page_state = MagicMock(return_value="video_page")
        tf.db = MagicMock()
        tf.reply_agent = MagicMock()
        tf.anti = MagicMock()

        tr.TikTokTaskFlow._run_comment_lead_safely(
            tf, "title", "keyword",
            enable_lead_pm=True,
            video_started_at=None,
            already_open=True,
        )

        _, kwargs = mock_process_action.call_args
        self.assertEqual(kwargs.get("keep_open_after_lead"), False,
            "Issue 1: task_runner 应始终传 keep_open_after_lead=False")


# ═══════════════════════════════════════════════════════════════
# Issue 2: Phase 2 独立私信循环（每条 PM 独立 open→PM→recover_to_video_page）
# ═══════════════════════════════════════════════════════════════
class TestIssue2Phase2IndependentLoop(unittest.TestCase):
    """Issue 2: Phase 2 每条 PM 独立打开→私信→恢复到视频页。"""

    def _make_tf(self, intent_items, run_action_side_effect):
        """构造最小 TikTokTaskFlow，runner.run_action 按 side_effect 派发。"""
        import dy.task_runner as tr
        tf = tr.TikTokTaskFlow.__new__(tr.TikTokTaskFlow)
        tf.is_stopped = False
        tf.is_paused = False
        tf.config = {
            "interaction": {"lead_pm_message_list": ["m"], "max_intent_comments_per_video": 3},
            "crawler": {"max_seconds_per_video": 90},
        }
        tf.runner = MagicMock()
        tf.runner.device = MagicMock()
        tf.runner.app_mgr = MagicMock()
        tf.runner.run_action = MagicMock(side_effect=run_action_side_effect)
        tf._check_stop = MagicMock()
        tf._recover_to_video_page = MagicMock(return_value=True)
        tf._dismiss_video_context_menu_if_present = MagicMock()
        tf._resource_exists = MagicMock(return_value=False)
        tf._detect_page_state = MagicMock(return_value="video_page")
        tf._is_video_page_ready = MagicMock(return_value=True)
        tf._reset_and_reenter_video_flow = MagicMock(return_value=True)
        tf.db = MagicMock()
        tf.reply_agent = MagicMock()
        tf.anti = MagicMock()
        return tf

    def _mock_process_action(self, intent_items, lead_reply_sent=True):
        mock_action_inst = MagicMock()
        mock_action_inst.lead_reply_sent = lead_reply_sent
        mock_action_inst.lead_comment_node = "node" if lead_reply_sent else None
        mock_action_inst.lead_comment_text = "t"
        mock_action_inst.lead_reply_text = "r"
        mock_action_inst.intent_items = intent_items
        mock_action_inst.inline_pm_completed = False
        mock_action_inst.lead_pm_sent_count = 0
        mock_action_inst.lead_reply_fallback_count = 0
        mock_action_inst.perform = MagicMock(return_value=True)
        return mock_action_inst

    @patch('dy.task_runner.ProcessCommentSectionAction')
    def test_each_pm_independently_opens_comment_section(self, mock_process_action):
        """N 条意向 → OpenCommentSectionAction 调用 N 次（每条 PM 独立打开）。"""
        from dy.actions.commenting import OpenCommentSectionAction, CommentLeadPmAction

        intent_items = [{"text": "评论1", "author": "u1"}, {"text": "评论2", "author": "u2"}]
        mock_process_action.return_value = self._mock_process_action(intent_items)

        open_calls = []
        pm_calls = []

        def run_action_side_effect(action_cls, **kwargs):
            if action_cls is OpenCommentSectionAction:
                open_calls.append(kwargs)
                return True
            if action_cls is CommentLeadPmAction:
                pm_calls.append(kwargs.get("lead_comment_text"))
                return {"pm_sent": True, "reason": "ok"}
            return False

        tf = self._make_tf(intent_items, run_action_side_effect)

        import dy.task_runner as tr
        tr.TikTokTaskFlow._run_comment_lead_safely(
            tf, "title", "keyword",
            enable_lead_pm=True, video_started_at=None, already_open=True,
        )

        self.assertEqual(len(open_calls), 2,
            f"应独立打开评论区 2 次（每条 PM 一次），实际 {len(open_calls)}")
        self.assertEqual(pm_calls, ["评论1", "评论2"],
            f"应按顺序对每条意向执行 PM，实际 {pm_calls}")

    @patch('dy.task_runner.ProcessCommentSectionAction')
    def test_deadline_exceeded_skips_remaining_items(self, mock_process_action):
        """超时发生时剩余循环被跳过，不影响已成功计数。

        场景：3 条意向评论，但 deadline_ts 在循环开始前已过 →
        - 0 次 OpenCommentSectionAction 调用
        - 0 次 CommentLeadPmAction 调用
        - lead_pm_success_count = 0
        """
        import time as _time
        import dy.task_runner as tr
        from dy.actions.commenting import OpenCommentSectionAction, CommentLeadPmAction

        intent_items = [
            {"text": "评论1", "author": "u1"},
            {"text": "评论2", "author": "u2"},
            {"text": "评论3", "author": "u3"},
        ]
        mock_process_action.return_value = self._mock_process_action(intent_items)

        open_calls = []
        pm_calls = []

        def run_action_side_effect(action_cls, **kwargs):
            if action_cls is OpenCommentSectionAction:
                open_calls.append(kwargs)
                return True
            if action_cls is CommentLeadPmAction:
                pm_calls.append(kwargs.get("lead_comment_text"))
                return {"pm_sent": True, "reason": "ok"}
            return False

        tf = self._make_tf(intent_items, run_action_side_effect)
        # video_started_at 设为远早于现在 → deadline_ts = past + 90 仍是过去
        past_ts = _time.time() - 1000

        result = tr.TikTokTaskFlow._run_comment_lead_safely(
            tf, "title", "keyword",
            enable_lead_pm=True, video_started_at=past_ts, already_open=True,
        )

        self.assertEqual(len(open_calls), 0,
            f"超时后不应打开评论区，实际 {len(open_calls)} 次")
        self.assertEqual(len(pm_calls), 0,
            f"超时后不应执行 PM，实际 {len(pm_calls)} 次")
        self.assertEqual(result.get("lead_pm_success_count", 0), 0,
            f"超时后成功计数应为 0，实际 {result.get('lead_pm_success_count')}")

    @patch('dy.task_runner.ProcessCommentSectionAction')
    def test_recover_after_pm_called_per_item(self, mock_process_action):
        """每次 PM 后调用 _recover_after_comment_pm（N 条意向 → N 次恢复）。"""
        import dy.task_runner as tr
        from dy.actions.commenting import OpenCommentSectionAction, CommentLeadPmAction

        intent_items = [
            {"text": "评论1", "author": "u1"},
            {"text": "评论2", "author": "u2"},
            {"text": "评论3", "author": "u3"},
        ]
        mock_process_action.return_value = self._mock_process_action(intent_items)

        def run_action_side_effect(action_cls, **kwargs):
            if action_cls is OpenCommentSectionAction:
                return True
            if action_cls is CommentLeadPmAction:
                return {"pm_sent": True, "reason": "ok"}
            return False

        tf = self._make_tf(intent_items, run_action_side_effect)
        tf._recover_after_comment_pm = MagicMock(return_value=True)

        tr.TikTokTaskFlow._run_comment_lead_safely(
            tf, "title", "keyword",
            enable_lead_pm=True, video_started_at=None, already_open=True,
        )

        self.assertEqual(tf._recover_after_comment_pm.call_count, 3,
            f"3 条意向应触发 3 次 _recover_after_comment_pm，"
            f"实际 {tf._recover_after_comment_pm.call_count}")


# ═══════════════════════════════════════════════════════════════
# Issue 3: 模块级 close_comment_section 函数提取
# ═══════════════════════════════════════════════════════════════
class TestIssue3CloseCommentSectionModuleFunction(unittest.TestCase):
    """Issue 3: 模块级 close_comment_section(d, human_sleep_fn, max_back)。"""

    def _make_device(self, panel_open_states):
        """构造 FakeDevice：press("back") 后按 panel_open_states 索引返回面板状态。

        panel_open_states: list of bool，索引 = press 次数。
                          True=面板打开（容器存在），False=已关闭。
                          state[0] = 初始状态（press 之前）。
        """
        class _FakeSelector:
            def __init__(self, exists_value):
                self._v = exists_value

            def exists(self, timeout=0):
                return self._v

        class _FakeDevice:
            def __init__(self):
                self._states = list(panel_open_states)
                self.press_calls = 0

            def press(self, key):
                self.press_calls += 1

            def __call__(self, **kwargs):
                # state index = press_calls（0 = 初始 / press 之前）
                idx = min(self.press_calls, len(self._states) - 1)
                is_open = self._states[idx] if self._states else False
                return _FakeSelector(is_open)

        return _FakeDevice()

    def test_already_closed_returns_true_without_press(self):
        """评论区已关闭时立即返回 True，不调用 back。"""
        from dy.actions.commenting import close_comment_section
        d = self._make_device([False])  # 第一次检查就发现已关闭
        result = close_comment_section(d, max_back=4)
        self.assertTrue(result, "已关闭应返回 True")
        self.assertEqual(d.press_calls, 0, "已关闭不应调用 back")

    def test_open_then_closed_after_backs(self):
        """评论区打开 → 多次 back 后关闭 → 返回 True。"""
        from dy.actions.commenting import close_comment_section
        # 第一次检查 panel 开（容器存在），back 后第二次检查 panel 开，再 back 后第三次检查已关
        # 注意：close_comment_section 先 _is_comment_closed 一次（开），然后进入 back 循环
        # 每次 back 后再 _is_comment_closed
        d = self._make_device([True, True, False])
        result = close_comment_section(d, max_back=4, human_sleep_fn=lambda t: None)
        self.assertTrue(result, "back 后关闭应返回 True")
        self.assertEqual(d.press_calls, 2, "应按 back 2 次")

    def test_open_and_never_closed_returns_false(self):
        """评论区始终打开 → max_back 用完 → 返回 False。"""
        from dy.actions.commenting import close_comment_section
        # 总是返回 True（panel 永远开）
        d = self._make_device([True, True, True, True, True, True, True])
        result = close_comment_section(d, max_back=3, human_sleep_fn=lambda t: None)
        self.assertFalse(result, "始终未关闭应返回 False")
        self.assertEqual(d.press_calls, 3, "应尝试 back max_back=3 次")

    def test_idempotent_consecutive_calls(self):
        """连续调用两次不报错（幂等）。"""
        from dy.actions.commenting import close_comment_section
        d1 = self._make_device([False])
        r1 = close_comment_section(d1, max_back=4)
        d2 = self._make_device([False])
        r2 = close_comment_section(d2, max_back=4)
        self.assertTrue(r1)
        self.assertTrue(r2)


# ═══════════════════════════════════════════════════════════════
# Issue 4: Phase 2 自愈与熔断（单条 PM 异常不影响后续）
# ═══════════════════════════════════════════════════════════════
class TestIssue4Phase2SelfHealing(unittest.TestCase):
    """Issue 4: Phase 2 每步 try/except，单条失败不影响后续循环。"""

    def _make_tf(self, intent_items, run_action_side_effect, recover_side_effect=None):
        """构造最小 TikTokTaskFlow。recover_side_effect 用于模拟 _recover_after_comment_pm 行为。"""
        import dy.task_runner as tr
        tf = tr.TikTokTaskFlow.__new__(tr.TikTokTaskFlow)
        tf.is_stopped = False
        tf.is_paused = False
        tf.config = {
            "interaction": {"lead_pm_message_list": ["m"], "max_intent_comments_per_video": 3},
            "crawler": {"max_seconds_per_video": 90},
        }
        tf.runner = MagicMock()
        tf.runner.device = MagicMock()
        tf.runner.app_mgr = MagicMock()
        tf.runner.run_action = MagicMock(side_effect=run_action_side_effect)
        tf._check_stop = MagicMock()
        tf._recover_to_video_page = MagicMock(return_value=True)
        tf._dismiss_video_context_menu_if_present = MagicMock()
        tf._resource_exists = MagicMock(return_value=False)
        tf._detect_page_state = MagicMock(return_value="video_page")
        tf._is_video_page_ready = MagicMock(return_value=True)
        tf._reset_and_reenter_video_flow = MagicMock(return_value=True)
        if recover_side_effect is not None:
            tf._recover_after_comment_pm = MagicMock(side_effect=recover_side_effect)
        else:
            tf._recover_after_comment_pm = MagicMock(return_value=True)
        tf.db = MagicMock()
        tf.reply_agent = MagicMock()
        tf.anti = MagicMock()
        return tf

    def _mock_process_action(self, intent_items, lead_reply_sent=True):
        mock_action_inst = MagicMock()
        mock_action_inst.lead_reply_sent = lead_reply_sent
        mock_action_inst.lead_comment_node = "node" if lead_reply_sent else None
        mock_action_inst.lead_comment_text = "t"
        mock_action_inst.lead_reply_text = "r"
        mock_action_inst.intent_items = intent_items
        mock_action_inst.inline_pm_completed = False
        mock_action_inst.lead_pm_sent_count = 0
        mock_action_inst.lead_reply_fallback_count = 0
        mock_action_inst.perform = MagicMock(return_value=True)
        return mock_action_inst

    @patch('dy.task_runner.ProcessCommentSectionAction')
    def test_pm_exception_does_not_break_loop(self, mock_process_action):
        """单条 PM 抛异常时，后续 PM 仍被尝试，成功计数正确。"""
        import dy.task_runner as tr
        from dy.actions.commenting import OpenCommentSectionAction, CommentLeadPmAction

        intent_items = [
            {"text": "评论1", "author": "u1"},
            {"text": "评论2", "author": "u2"},
            {"text": "评论3", "author": "u3"},
        ]
        mock_process_action.return_value = self._mock_process_action(intent_items)

        pm_calls = []

        def run_action_side_effect(action_cls, **kwargs):
            if action_cls is OpenCommentSectionAction:
                return True
            if action_cls is CommentLeadPmAction:
                text = kwargs.get("lead_comment_text", "")
                pm_calls.append(text)
                if text == "评论2":
                    raise RuntimeError("PM 内部异常")
                return {"pm_sent": True, "reason": "ok"}
            return False

        tf = self._make_tf(intent_items, run_action_side_effect)

        result = tr.TikTokTaskFlow._run_comment_lead_safely(
            tf, "title", "keyword",
            enable_lead_pm=True, video_started_at=None, already_open=True,
        )

        self.assertEqual(pm_calls, ["评论1", "评论2", "评论3"],
            f"3 条都应被尝试，实际 {pm_calls}（异常中断了循环？）")
        self.assertEqual(result.get("lead_pm_success_count", 0), 2,
            f"评论1和评论3成功 → 计数 2，实际 {result.get('lead_pm_success_count')}")

    @patch('dy.task_runner.ProcessCommentSectionAction')
    def test_open_exception_does_not_break_loop(self, mock_process_action):
        """打开评论区抛异常时，后续 PM 仍被尝试。"""
        import dy.task_runner as tr
        from dy.actions.commenting import OpenCommentSectionAction, CommentLeadPmAction

        intent_items = [
            {"text": "评论1", "author": "u1"},
            {"text": "评论2", "author": "u2"},
            {"text": "评论3", "author": "u3"},
        ]
        mock_process_action.return_value = self._mock_process_action(intent_items)

        open_calls = []
        pm_calls = []

        def run_action_side_effect(action_cls, **kwargs):
            if action_cls is OpenCommentSectionAction:
                open_calls.append(len(open_calls) + 1)
                if len(open_calls) == 2:
                    raise RuntimeError("打开评论区异常")
                return True
            if action_cls is CommentLeadPmAction:
                pm_calls.append(kwargs.get("lead_comment_text", ""))
                return {"pm_sent": True, "reason": "ok"}
            return False

        tf = self._make_tf(intent_items, run_action_side_effect)

        result = tr.TikTokTaskFlow._run_comment_lead_safely(
            tf, "title", "keyword",
            enable_lead_pm=True, video_started_at=None, already_open=True,
        )

        self.assertEqual(len(open_calls), 3,
            f"3 条都应尝试打开评论区，实际 {len(open_calls)} 次")
        self.assertEqual(pm_calls, ["评论1", "评论3"],
            f"评论2 打开失败应跳过 PM，实际 PM 调用 {pm_calls}")
        self.assertEqual(result.get("lead_pm_success_count", 0), 2,
            f"评论1和评论3成功 → 计数 2，实际 {result.get('lead_pm_success_count')}")

    @patch('dy.task_runner.ProcessCommentSectionAction')
    def test_recover_exception_triggers_reset_and_continues(self, mock_process_action):
        """_recover_after_comment_pm 抛异常时，触发 _reset_and_reenter_video_flow，循环继续。"""
        import dy.task_runner as tr
        from dy.actions.commenting import OpenCommentSectionAction, CommentLeadPmAction

        intent_items = [
            {"text": "评论1", "author": "u1"},
            {"text": "评论2", "author": "u2"},
        ]
        mock_process_action.return_value = self._mock_process_action(intent_items)

        pm_calls = []
        recover_call_count = [0]

        def run_action_side_effect(action_cls, **kwargs):
            if action_cls is OpenCommentSectionAction:
                return True
            if action_cls is CommentLeadPmAction:
                pm_calls.append(kwargs.get("lead_comment_text", ""))
                return {"pm_sent": True, "reason": "ok"}
            return False

        def recover_side_effect():
            recover_call_count[0] += 1
            if recover_call_count[0] == 1:
                raise RuntimeError("恢复异常")

        tf = self._make_tf(intent_items, run_action_side_effect, recover_side_effect=recover_side_effect)

        result = tr.TikTokTaskFlow._run_comment_lead_safely(
            tf, "title", "keyword",
            enable_lead_pm=True, video_started_at=None, already_open=True,
        )

        self.assertEqual(pm_calls, ["评论1", "评论2"],
            f"恢复异常不应中断循环，实际 PM 调用 {pm_calls}")
        self.assertEqual(tf._reset_and_reenter_video_flow.call_count, 1,
            f"恢复异常应触发 1 次 _reset_and_reenter_video_flow，实际 {tf._reset_and_reenter_video_flow.call_count}")

    @patch('dy.task_runner.ProcessCommentSectionAction')
    def test_interrupted_error_propagates(self, mock_process_action):
        """用户手动停止（InterruptedError）应立即传播，不继续下一条。"""
        import dy.task_runner as tr
        from dy.actions.commenting import OpenCommentSectionAction, CommentLeadPmAction

        intent_items = [
            {"text": "评论1", "author": "u1"},
            {"text": "评论2", "author": "u2"},
            {"text": "评论3", "author": "u3"},
        ]
        mock_process_action.return_value = self._mock_process_action(intent_items)

        pm_calls = []

        def run_action_side_effect(action_cls, **kwargs):
            if action_cls is OpenCommentSectionAction:
                return True
            if action_cls is CommentLeadPmAction:
                text = kwargs.get("lead_comment_text", "")
                pm_calls.append(text)
                return {"pm_sent": True, "reason": "ok"}
            return False

        tf = self._make_tf(intent_items, run_action_side_effect)
        # _check_stop 在第 2 次调用时抛 InterruptedError
        check_stop_calls = [0]
        def check_stop_side_effect():
            check_stop_calls[0] += 1
            if check_stop_calls[0] >= 2:
                raise InterruptedError("用户手动结束了任务")
        tf._check_stop = MagicMock(side_effect=check_stop_side_effect)

        with self.assertRaises(InterruptedError):
            tr.TikTokTaskFlow._run_comment_lead_safely(
                tf, "title", "keyword",
                enable_lead_pm=True, video_started_at=None, already_open=True,
            )

        # 评论1 已处理（_check_stop 第1次通过），评论2 入口 _check_stop 抛错 → 不应处理评论3
        self.assertLessEqual(pm_calls, ["评论1", "评论2"],
            f"InterruptedError 应中断循环，实际 PM 调用 {pm_calls}")


# ═══════════════════════════════════════════════════════════════
# Issue 6: Phase 2 avatar 反查高稳定性修复
# 修复真机测试中 100% avatar_not_found 失败：
#   1) author 交叉验证未启用（lead_comment_author 从未被读取）
#   2) reopen 后目标评论不在可见区 → 需要滚动查找
#   3) 卡片内 avatar clickable=false 时应回退到坐标点击
# ═══════════════════════════════════════════════════════════════
class TestIssue6AvatarScrollToFind(unittest.TestCase):
    """Issue 6: avatar 反查高稳定性 — author 交叉验证 + 滚动查找 + 非可点击头像回退。"""

    def _make_action(self, lead_comment_text="评论内容",
                     lead_comment_author="用户A", lead_comment_node=None):
        """构造最小 CommentLeadPmAction 实例（跳过 __init__ 的 AntiDetection 注入）。"""
        from dy.actions.commenting import CommentLeadPmAction
        action = CommentLeadPmAction.__new__(CommentLeadPmAction)
        action.d = MagicMock()
        action.app = None
        action.config = {}
        action.lead_comment_text = lead_comment_text
        action.lead_comment_author = lead_comment_author
        action.lead_comment_node = lead_comment_node
        action.check_stop_callback = None
        action.deadline_ts = None
        action.human_swipe_curve = MagicMock()
        action.human_sleep = MagicMock()
        action.human_click = MagicMock()
        return action

    @patch('dy.actions.commenting._refind_comment_node_by_text')
    def test_author_passed_to_refind_for_cross_validation(self, mock_refind):
        """Layer 1: lead_comment_author 应传给 _refind_comment_node_by_text 做交叉验证。"""
        mock_node = MagicMock()
        mock_refind.return_value = mock_node
        action = self._make_action(lead_comment_text="评论X", lead_comment_author="用户B")

        # 让卡片内头像查找成功，避免走到滚动逻辑
        action._find_card_elem = MagicMock(return_value="fake_card")
        action._find_clickable_avatar_in = MagicMock(return_value="avatar_node")
        action._find_avatar_by_geometry = MagicMock()

        action._find_avatar_from_comment_node(None)

        # 验证 _refind_comment_node_by_text 被调用时传了 author
        call_args = mock_refind.call_args
        self.assertEqual(call_args[0][1], "评论X",
            f"应传评论文本，实际 {call_args[0]}")
        # 第三个位置参数或 keyword 参数 author 应为 "用户B"
        if len(call_args[0]) > 2:
            self.assertEqual(call_args[0][2], "用户B",
                f"应传 author 做交叉验证，实际 {call_args[0][2]}")
        else:
            self.assertEqual(call_args[1].get("author"), "用户B",
                f"应传 author 做交叉验证，实际 kwargs={call_args[1]}")

    @patch('dy.actions.commenting._refind_comment_node_by_text')
    def test_direct_locate_success_no_scroll(self, mock_refind):
        """直接定位成功时不滚动。"""
        mock_node = MagicMock()
        mock_refind.return_value = mock_node
        action = self._make_action()

        action._find_card_elem = MagicMock(return_value="fake_card")
        action._find_clickable_avatar_in = MagicMock(return_value="avatar_node")
        action._find_avatar_by_geometry = MagicMock()

        result = action._find_avatar_from_comment_node(None)

        self.assertIsNotNone(result, "直接定位成功应返回头像")
        self.assertEqual(action.human_swipe_curve.call_count, 0,
            "直接定位成功不应滚动")

    @patch('dy.actions.commenting._refind_comment_node_by_text')
    def test_scroll_then_locate_success(self, mock_refind):
        """直接定位失败 → 滚动后定位成功。

        模拟 reopen 后目标评论不在可见区，第 1 次 refind 返回 None，
        滚动 1 次后第 2 次 refind 返回节点。
        """
        mock_node = MagicMock()
        mock_refind.side_effect = [None, mock_node]  # 第 1 次失败, 第 2 次成功
        action = self._make_action()

        # mock 设备返回评论区容器 bounds（用于滑动坐标计算）
        action.d.window_size = MagicMock(return_value=(1080, 1920))
        action.d(resourceId=MagicMock()).exists = MagicMock(return_value=True)
        action.d(resourceId=MagicMock()).info = {
            'bounds': {'left': 0, 'top': 300, 'right': 1080, 'bottom': 1600}
        }

        # 第 2 次定位成功后，卡片内头像也找到
        action._find_card_elem = MagicMock(return_value="fake_card")
        action._find_clickable_avatar_in = MagicMock(return_value="avatar_node")
        action._find_avatar_by_geometry = MagicMock()

        result = action._find_avatar_from_comment_node(None)

        self.assertIsNotNone(result, "滚动后应定位到头像")
        self.assertEqual(mock_refind.call_count, 2,
            f"应调用 refind 2 次（1 直接 + 1 滚动后），实际 {mock_refind.call_count}")
        self.assertEqual(action.human_swipe_curve.call_count, 1,
            f"应滚动 1 次，实际 {action.human_swipe_curve.call_count}")

    @patch('dy.actions.commenting._refind_comment_node_by_text')
    def test_scroll_max_attempts_then_give_up(self, mock_refind):
        """滚动 max_scroll 次仍失败 → 返回 None。"""
        mock_refind.return_value = None  # 总是失败
        action = self._make_action()

        action.d.window_size = MagicMock(return_value=(1080, 1920))
        action.d(resourceId=MagicMock()).exists = MagicMock(return_value=True)
        action.d(resourceId=MagicMock()).info = {
            'bounds': {'left': 0, 'top': 300, 'right': 1080, 'bottom': 1600}
        }
        action._find_card_elem = MagicMock()
        action._find_clickable_avatar_in = MagicMock()
        action._find_avatar_by_geometry = MagicMock()

        result = action._find_avatar_from_comment_node(None)

        self.assertIsNone(result, "滚动 max 次后应返回 None")
        # max_scroll 默认应为 6
        self.assertLessEqual(action.human_swipe_curve.call_count, 6,
            f"滚动次数不应超过 6，实际 {action.human_swipe_curve.call_count}")
        self.assertGreaterEqual(action.human_swipe_curve.call_count, 3,
            f"应至少滚动 3 次才放弃，实际 {action.human_swipe_curve.call_count}")

    @patch('dy.actions.commenting._refind_comment_node_by_text')
    def test_guard_called_during_scroll_loop(self, mock_refind):
        """滚动循环中应调用 _guard 检查停止/超时。"""
        mock_refind.return_value = None
        action = self._make_action()

        action.d.window_size = MagicMock(return_value=(1080, 1920))
        action.d(resourceId=MagicMock()).exists = MagicMock(return_value=True)
        action.d(resourceId=MagicMock()).info = {
            'bounds': {'left': 0, 'top': 300, 'right': 1080, 'bottom': 1600}
        }
        action._find_card_elem = MagicMock()
        action._find_clickable_avatar_in = MagicMock()
        action._find_avatar_by_geometry = MagicMock()
        action._guard = MagicMock()

        action._find_avatar_from_comment_node(None)

        # _guard 应被多次调用（至少每次滚动前）
        self.assertGreater(action._guard.call_count, 1,
            f"滚动循环中应多次调用 _guard，实际 {action._guard.call_count}")

    def test_non_clickable_avatar_fallback_in_card(self):
        """Layer 3: 卡片内无 clickable=true 头像时，回退到非可点击头像（坐标点击）。"""
        from dy.actions.commenting import CommentLeadPmAction
        from lxml import etree

        # 构造卡片 XML：avatar 的 clickable="false"
        xml = '''
        <root>
            <node resource-id="com.ss.android.ugc.aweme:id/k4x">
                <node resource-id="com.ss.android.ugc.aweme:id/avatar" clickable="false"
                      bounds="[10,10,80,80]" />
                <node resource-id="com.ss.android.ugc.aweme:id/title" text="用户A" />
                <node resource-id="com.ss.android.ugc.aweme:id/content" text="评论内容" />
            </node>
        </root>
        '''
        root = etree.fromstring(xml)
        card_elem = root[0]

        action = self._make_action()
        result = action._find_clickable_avatar_in(card_elem)

        self.assertIsNotNone(result, "非可点击头像也应被找到（用于坐标点击）")


if __name__ == "__main__":
    unittest.main()
