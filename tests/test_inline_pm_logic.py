"""
内联私信（inline PM）逻辑单元测试
目标：验证 ProcessCommentSectionAction.execute 在默认配置和 max_intent_comments>1 时的状态流转，
以及 task_runner 中 B.5 的跳过逻辑，不依赖真实 Android 设备。
"""
import sys
import os
import unittest
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dy.actions.commenting import ProcessCommentSectionAction


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
    """
    重载与 UI/AI 相关的真实调用，仅保留核心状态机。
    """
    def __init__(self, config, comments=None, intent_indices=None, pm_success=True, pm_return_ok=True, pm_results=None):
        self.d = FakeDevice()
        self.app = None
        self.config = config
        self.comments = comments or []
        # 哪些索引的评论会被 AI 判为意向评论
        self.intent_indices = set(intent_indices or [])
        # 模拟私信成功/失败：支持单一布尔值或按调用次数的列表
        self.pm_results = pm_results
        self.pm_success = pm_success
        self.pm_return_ok = pm_return_ok
        self._pm_called_count = 0
        self._closed = False

    def _process_current_screen_comments(self, processed_comments, ai_agent, video_title, keyword, remaining_reviews, custom_keywords=None):
        for idx, text in enumerate(self.comments):
            if idx in processed_comments:
                continue
            processed_comments.add(idx)
            if idx in self.intent_indices:
                node = FakeNode(text=text)
                sent = True  # 模拟回复成功
                return True, idx + 1, True, {"node": node, "text": text, "sent": sent}
            if idx >= remaining_reviews - 1:
                break
        return False, len(self.comments), False, None

    def _swipe_up_comments(self):
        # 允许一次滑动，让第二条意向评论有机会被扫描到
        if getattr(self, '_swipe_count', 0) < 1:
            self._swipe_count = getattr(self, '_swipe_count', 0) + 1
            return True
        return False

    def _try_inline_pm_for_intent(self, comment_node, comment_text):
        self._pm_called_count += 1
        if self.pm_results is not None:
            idx = self._pm_called_count - 1
            if idx < len(self.pm_results):
                return self.pm_results[idx]
            return False
        if self.pm_success:
            return True
        return False

    def _return_from_profile_to_comments(self, max_back=3):
        return self.pm_return_ok

    def _close_comment_section(self):
        self._closed = True
        return True

    def _comment_panel_open(self):
        return not self._closed


class TestInlinePMLogic(unittest.TestCase):
    def _base_config(self, max_intent=1, enable_lead_pm=True):
        return {
            "interaction": {
                "max_comment_swipes": 2,
                "max_ai_comment_reviews": 20,
                "max_intent_comments_per_video": max_intent,
                "enable_comment_lead_pm": enable_lead_pm,
                "fallback_top_comment_count": 5,
                "lead_pm_message_list": ["你好"],
            }
        }

    def test_default_config_no_inline_pm(self):
        """默认 max_intent=1 不应触发内联私信，保留 lead 状态给 B.5。"""
        config = self._base_config(max_intent=1, enable_lead_pm=True)
        action = MockedProcessCommentSectionAction(
            config,
            comments=["这条评论想买"],
            intent_indices=[0],
            pm_success=True,
        )
        action.enable_lead_pm = True
        action.keep_open_after_lead = True
        result = action.execute()

        self.assertEqual(action._pm_called_count, 0, "默认配置不应调用内联私信")
        self.assertIsNotNone(action.lead_comment_node, "应保留 lead 节点给 B.5")
        self.assertTrue(action.lead_reply_sent)
        self.assertFalse(action.inline_pm_completed)
        self.assertTrue(result)

    def test_multi_intent_inline_pm_twice_and_skip_b5(self):
        """max_intent=2 且有两条意向评论，应触发 2 次内联私信并跳过 B.5。"""
        config = self._base_config(max_intent=2, enable_lead_pm=True)
        action = MockedProcessCommentSectionAction(
            config,
            comments=["想买", "怎么买", "路人评论"],
            intent_indices=[0, 1],
            pm_success=True,
        )
        action.enable_lead_pm = True
        action.keep_open_after_lead = True
        result = action.execute()

        self.assertEqual(action._pm_called_count, 2, "应调用 2 次内联私信")
        self.assertEqual(action.intent_processed_count, 2)
        self.assertTrue(action.inline_pm_completed)
        self.assertIsNone(action.lead_comment_node, "内联完成后应重置 lead 节点")
        self.assertTrue(result)

    def test_multi_intent_but_pm_disabled(self):
        """max_intent>1 但私信未启用，不应触发内联私信。"""
        config = self._base_config(max_intent=2, enable_lead_pm=False)
        action = MockedProcessCommentSectionAction(
            config,
            comments=["想买", "怎么买"],
            intent_indices=[0, 1],
            pm_success=True,
        )
        action.enable_lead_pm = False
        action.keep_open_after_lead = False
        result = action.execute()

        self.assertEqual(action._pm_called_count, 0, "私信未启用时不应调用内联私信")
        self.assertEqual(action.intent_processed_count, 0)
        self.assertFalse(action.inline_pm_completed)
        # 找到第一条意向后 should_break=True 会停止扫描
        self.assertIsNotNone(action.lead_comment_node)

    def test_inline_pm_failure_returns_to_comments(self):
        """内联私信失败后应返回评论区并保留 lead 给 B.5 兜底。"""
        config = self._base_config(max_intent=2, enable_lead_pm=True)
        action = MockedProcessCommentSectionAction(
            config,
            comments=["想买"],
            intent_indices=[0],
            pm_success=False,
            pm_return_ok=True,
        )
        action.enable_lead_pm = True
        action.keep_open_after_lead = True
        result = action.execute()

        self.assertEqual(action._pm_called_count, 1)
        self.assertFalse(action.inline_pm_completed)
        self.assertIsNotNone(action.lead_comment_node, "失败后应保留 lead 节点给 B.5")
        self.assertTrue(result)

    def test_no_intent_fallback_triggered(self):
        """无意向评论时应触发路人兜底。"""
        config = self._base_config(max_intent=1, enable_lead_pm=True)

        # 需要模拟 _fallback_reply_and_dm_top_comments
        fallback_called = {"called": False}

        class ActionWithFallback(MockedProcessCommentSectionAction):
            def _fallback_reply_and_dm_top_comments(self, ai_agent, video_title, keyword, max_count=5, do_dm=False):
                fallback_called["called"] = True
                fallback_called["do_dm"] = do_dm
                self.lead_reply_fallback_count = 1
                return 1

        action = ActionWithFallback(
            config,
            comments=["路人评论1", "路人评论2"],
            intent_indices=[],
        )
        action.enable_lead_pm = True
        action.keep_open_after_lead = True
        result = action.execute()

        self.assertTrue(fallback_called["called"], "无意向评论时应触发兜底")
        self.assertTrue(fallback_called["do_dm"], "私信启用时兜底应发私信")
        self.assertEqual(action.lead_comment_text, "fallback")

    def test_no_fallback_after_inline_pm(self):
        """内联私信成功后不应再触发路人兜底。"""
        config = self._base_config(max_intent=2, enable_lead_pm=True)

        fallback_called = {"called": False}

        class ActionWithFallback(MockedProcessCommentSectionAction):
            def _fallback_reply_and_dm_top_comments(self, ai_agent, video_title, keyword, max_count=5, do_dm=False):
                fallback_called["called"] = True
                return 0

        action = ActionWithFallback(
            config,
            comments=["想买", "怎么买", "路人评论"],
            intent_indices=[0, 1],
            pm_success=True,
        )
        action.enable_lead_pm = True
        action.keep_open_after_lead = True
        result = action.execute()

        self.assertFalse(fallback_called["called"], "内联成功后不应触发路人兜底")
        self.assertEqual(action.intent_processed_count, 2)

    def test_partial_inline_pm_failure_keeps_lead_for_b5(self):
        """第一条内联成功、第二条失败时，应保留第二条 lead 供 B.5 兜底。"""
        config = self._base_config(max_intent=2, enable_lead_pm=True)
        action = MockedProcessCommentSectionAction(
            config,
            comments=["想买", "怎么买"],
            intent_indices=[0, 1],
            pm_results=[True, False],  # 第一次成功，第二次失败
        )
        action.enable_lead_pm = True
        action.keep_open_after_lead = True
        result = action.execute()

        self.assertEqual(action._pm_called_count, 2)
        self.assertEqual(action.intent_processed_count, 1)
        self.assertTrue(action.inline_pm_completed)
        self.assertIsNotNone(action.lead_comment_node, "第二次失败的 lead 节点应保留给 B.5")
        self.assertEqual(action.lead_comment_text, "怎么买")


if __name__ == "__main__":
    unittest.main()
