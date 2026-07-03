"""Issue 5: Phase 2 独立私信循环端到端集成测试。

覆盖方案 C 完整链路：
  打开评论区 → Phase A 收集 → Phase B 回复 → 关闭评论区
  → Phase 2 逐条 PM → 恢复到视频页

通过 mock runner.run_action 派发 OpenCommentSectionAction / CommentLeadPmAction，
并 mock ProcessCommentSectionAction 提供 intent_items，验证调用顺序与参数。

注意：Issue 5 spec 的 Case 5 期望 _close_comment_section 在 PM 后调用，
但实际实现（Issue 2）使用 _recover_after_comment_pm（PM 后从聊天页恢复到视频页，
而非关闭评论区面板——PM 后设备在聊天页，评论区早已关闭）。
本测试按实际实现验证 _recover_after_comment_pm 调用。
"""
import sys
import os
import time as _time
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


def _make_tiktok_flow(run_action_side_effect, recover_side_effect=None,
                      check_stop_side_effect=None, video_started_at=None,
                      resource_exists_value=True):
    """构造最小 TikTokTaskFlow，runner.run_action 按 side_effect 派发。

    resource_exists_value: _resource_exists 返回值。默认 True 使 already_open=False
                           时的入口 open 验证通过（直接容器检测分支）。
    """
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
    tf._check_stop = MagicMock(side_effect=check_stop_side_effect) if check_stop_side_effect else MagicMock()
    tf._recover_to_video_page = MagicMock(return_value=True)
    tf._dismiss_video_context_menu_if_present = MagicMock()
    tf._resource_exists = MagicMock(return_value=resource_exists_value)
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


def _mock_process_action(intent_items, lead_reply_sent=True, lead_comment_text="t"):
    """Mock ProcessCommentSectionAction 实例，提供 intent_items 等。"""
    mock_action_inst = MagicMock()
    mock_action_inst.lead_reply_sent = lead_reply_sent
    mock_action_inst.lead_comment_node = "node" if lead_reply_sent else None
    mock_action_inst.lead_comment_text = lead_comment_text
    mock_action_inst.lead_reply_text = "r"
    mock_action_inst.intent_items = intent_items
    mock_action_inst.inline_pm_completed = False
    mock_action_inst.lead_pm_sent_count = 0
    mock_action_inst.lead_reply_fallback_count = 0
    mock_action_inst.perform = MagicMock(return_value=True)
    return mock_action_inst


class TestPhase2IndependentPmIntegration(unittest.TestCase):
    """Issue 5: Phase 2 独立私信循环端到端集成测试（6 cases）。"""

    # ── Case 1: 正常流程 — 2 条意向 → Phase B 回复 2 → Phase 2 PM 2 ──
    @patch('dy.task_runner.ProcessCommentSectionAction')
    def test_case1_phase2_opens_closes_comment_for_each_pm(self, mock_process_action):
        """每条 PM 独立打开→恢复到视频页。

        - OpenCommentSectionAction 调用 = 1（Phase A+B 入口）+ 2（Phase 2 每条一次）= 3
        - _recover_after_comment_pm 调用 = 2（每条 PM 后一次）
        """
        import dy.task_runner as tr
        from dy.actions.commenting import OpenCommentSectionAction, CommentLeadPmAction

        intent_items = [
            {"text": "意向1", "author": "u1"},
            {"text": "意向2", "author": "u2"},
        ]
        mock_process_action.return_value = _mock_process_action(intent_items)

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

        tf = _make_tiktok_flow(run_action_side_effect)

        tr.TikTokTaskFlow._run_comment_lead_safely(
            tf, "title", "keyword",
            enable_lead_pm=True, video_started_at=None, already_open=False,
        )

        # Phase A+B 入口打开 1 次 + Phase 2 每条 PM 打开 2 次 = 3 次
        self.assertEqual(len(open_calls), 3,
            f"应打开评论区 3 次（1 Phase A+B + 2 Phase 2），实际 {len(open_calls)}")
        # 每条 PM 后恢复 1 次 = 2 次
        self.assertEqual(tf._recover_after_comment_pm.call_count, 2,
            f"应恢复 2 次（每条 PM 后），实际 {tf._recover_after_comment_pm.call_count}")
        self.assertEqual(pm_calls, ["意向1", "意向2"],
            f"应按顺序 PM 2 条，实际 {pm_calls}")

    # ── Case 2: 超时熔断 — Phase 2 执行到一半超时 ──
    @patch('dy.task_runner.ProcessCommentSectionAction')
    def test_case2_phase2_timeout_skips_remaining_pms(self, mock_process_action):
        """注入超时：deadline 已过 → Phase 2 跳过所有 PM。"""
        import dy.task_runner as tr
        from dy.actions.commenting import OpenCommentSectionAction, CommentLeadPmAction

        intent_items = [
            {"text": "意向1", "author": "u1"},
            {"text": "意向2", "author": "u2"},
            {"text": "意向3", "author": "u3"},
        ]
        mock_process_action.return_value = _mock_process_action(intent_items)

        pm_calls = []

        def run_action_side_effect(action_cls, **kwargs):
            if action_cls is OpenCommentSectionAction:
                return True
            if action_cls is CommentLeadPmAction:
                pm_calls.append(kwargs.get("lead_comment_text"))
                return {"pm_sent": True, "reason": "ok"}
            return False

        # video_started_at 设为远早于现在 → deadline_ts = past + 90 仍为过去
        past_ts = _time.time() - 1000
        tf = _make_tiktok_flow(run_action_side_effect, video_started_at=past_ts)

        result = tr.TikTokTaskFlow._run_comment_lead_safely(
            tf, "title", "keyword",
            enable_lead_pm=True, video_started_at=past_ts, already_open=True,
        )

        self.assertEqual(len(pm_calls), 0,
            f"超时后不应执行任何 PM，实际 {len(pm_calls)}")
        self.assertEqual(result.get("lead_pm_success_count", 0), 0,
            f"超时后成功计数应为 0，实际 {result.get('lead_pm_success_count')}")

    # ── Case 3: 单条 PM 打开评论区失败 ──
    @patch('dy.task_runner.ProcessCommentSectionAction')
    def test_case3_phase2_skips_on_open_comment_failure(self, mock_process_action):
        """第 2 条评论区打开失败，应跳过继续第 3 条。"""
        import dy.task_runner as tr
        from dy.actions.commenting import OpenCommentSectionAction, CommentLeadPmAction

        intent_items = [
            {"text": "意向1", "author": "u1"},
            {"text": "意向2", "author": "u2"},
            {"text": "意向3", "author": "u3"},
        ]
        mock_process_action.return_value = _mock_process_action(intent_items)

        open_call_count = [0]
        pm_calls = []

        def run_action_side_effect(action_cls, **kwargs):
            if action_cls is OpenCommentSectionAction:
                open_call_count[0] += 1
                # Phase A+B 入口（第 1 次）成功；Phase 2 第 2 条（第 3 次 open）失败
                if open_call_count[0] == 3:
                    return False
                return True
            if action_cls is CommentLeadPmAction:
                pm_calls.append(kwargs.get("lead_comment_text"))
                return {"pm_sent": True, "reason": "ok"}
            return False

        tf = _make_tiktok_flow(run_action_side_effect)

        result = tr.TikTokTaskFlow._run_comment_lead_safely(
            tf, "title", "keyword",
            enable_lead_pm=True, video_started_at=None, already_open=False,
        )

        # 3 次 open 尝试（1 Phase A+B + 3 Phase 2）— 注意 already_open=False 时 Phase A+B 入口也调 open
        # 实际：Phase A+B 1 次 + Phase 2 3 次 = 4 次
        self.assertEqual(open_call_count[0], 4,
            f"应尝试打开 4 次（1 入口 + 3 Phase 2），实际 {open_call_count[0]}")
        # PM 只对成功的 open 执行：意向1 + 意向3（意向2 open 失败跳过）
        self.assertEqual(pm_calls, ["意向1", "意向3"],
            f"意向2 open 失败应跳过 PM，实际 PM 调用 {pm_calls}")
        self.assertEqual(result.get("lead_pm_success_count", 0), 2,
            f"意向1和意向3成功 → 计数 2，实际 {result.get('lead_pm_success_count')}")

    # ── Case 4: 用户停止 — Phase 2 中途停止 ──
    @patch('dy.task_runner.ProcessCommentSectionAction')
    def test_case4_phase2_stop_interrupts_immediately(self, mock_process_action):
        """Phase 2 循环中 is_stopped=True 时立即终止，不继续下一条。"""
        import dy.task_runner as tr
        from dy.actions.commenting import OpenCommentSectionAction, CommentLeadPmAction

        intent_items = [
            {"text": "意向1", "author": "u1"},
            {"text": "意向2", "author": "u2"},
            {"text": "意向3", "author": "u3"},
        ]
        mock_process_action.return_value = _mock_process_action(intent_items)

        pm_calls = []

        def run_action_side_effect(action_cls, **kwargs):
            if action_cls is OpenCommentSectionAction:
                return True
            if action_cls is CommentLeadPmAction:
                pm_calls.append(kwargs.get("lead_comment_text"))
                return {"pm_sent": True, "reason": "ok"}
            return False

        # _check_stop 第 2 次调用时抛 InterruptedError
        check_stop_calls = [0]
        def check_stop_side_effect():
            check_stop_calls[0] += 1
            # 第 1 次：Phase A+B 前的 _check_stop（在 ProcessCommentSectionAction 之前）
            # 第 2 次：Phase 2 第 1 条 PM 入口的 _check_stop → 抛错
            if check_stop_calls[0] >= 2:
                raise InterruptedError("用户手动结束了任务")

        tf = _make_tiktok_flow(run_action_side_effect, check_stop_side_effect=check_stop_side_effect)

        with self.assertRaises(InterruptedError):
            tr.TikTokTaskFlow._run_comment_lead_safely(
                tf, "title", "keyword",
                enable_lead_pm=True, video_started_at=None, already_open=True,
            )

        # 第 1 条 PM 入口即抛错 → 0 条 PM 执行
        self.assertEqual(pm_calls, [],
            f"InterruptedError 应在 Phase 2 入口立即终止，实际 PM 调用 {pm_calls}")

    # ── Case 5: 调用顺序验证 ──
    @patch('dy.task_runner.ProcessCommentSectionAction')
    def test_case5_phase2_call_order_matches_expected(self, mock_process_action):
        """验证完整调用序列：open→Process→recover→(open→PM→recover)×N。

        already_open=True 跳过 Phase A+B 入口的 open，直接 ProcessCommentSectionAction。
        Phase B 后 ProcessCommentSectionAction 内部关闭评论区（Issue 1）。
        Phase 2 每条：open→PM→recover_after_comment_pm。
        """
        import dy.task_runner as tr
        from dy.actions.commenting import OpenCommentSectionAction, CommentLeadPmAction

        intent_items = [
            {"text": "text1", "author": "u1"},
            {"text": "text2", "author": "u2"},
        ]
        mock_process_action.return_value = _mock_process_action(intent_items)

        call_log = []

        def run_action_side_effect(action_cls, **kwargs):
            if action_cls is OpenCommentSectionAction:
                call_log.append(("OpenCommentSectionAction",))
                return True
            if action_cls is CommentLeadPmAction:
                call_log.append(("CommentLeadPmAction", kwargs.get("lead_comment_text")))
                return {"pm_sent": True, "reason": "ok"}
            return False

        def recover_side_effect():
            call_log.append(("_recover_after_comment_pm",))

        tf = _make_tiktok_flow(run_action_side_effect, recover_side_effect=recover_side_effect)

        tr.TikTokTaskFlow._run_comment_lead_safely(
            tf, "title", "keyword",
            enable_lead_pm=True, video_started_at=None, already_open=True,
        )

        # already_open=True → 跳过 Phase A+B 入口的 open
        # Phase 2 每条：open→PM→recover
        expected_log = [
            ("OpenCommentSectionAction",),        # Phase 2 PM #1 open
            ("CommentLeadPmAction", "text1"),     # Phase 2 PM #1
            ("_recover_after_comment_pm",),       # PM #1 后恢复
            ("OpenCommentSectionAction",),        # Phase 2 PM #2 open
            ("CommentLeadPmAction", "text2"),     # Phase 2 PM #2
            ("_recover_after_comment_pm",),       # PM #2 后恢复
        ]
        self.assertEqual(call_log, expected_log,
            f"调用顺序不符\n期望: {expected_log}\n实际: {call_log}")

    # ── Case 6: 回归 — Phase A+B 不受影响 ──
    @patch('dy.task_runner.ProcessCommentSectionAction')
    def test_case6_phase_ab_unaffected_by_refactor(self, mock_process_action):
        """Phase A（收集）和 Phase B（回复）的行为不变。

        验证 _run_comment_lead_safely 返回值中 lead_reply_sent=True，
        且 ProcessCommentSectionAction 收到正确的参数（video_title/keyword）。
        """
        import dy.task_runner as tr
        from dy.actions.commenting import OpenCommentSectionAction, CommentLeadPmAction

        intent_items = [{"text": "意向1", "author": "u1"}]
        mock_process_action.return_value = _mock_process_action(
            intent_items, lead_reply_sent=True, lead_comment_text="意向1"
        )

        def run_action_side_effect(action_cls, **kwargs):
            if action_cls is OpenCommentSectionAction:
                return True
            if action_cls is CommentLeadPmAction:
                return {"pm_sent": True, "reason": "ok"}
            return False

        tf = _make_tiktok_flow(run_action_side_effect)

        result = tr.TikTokTaskFlow._run_comment_lead_safely(
            tf, "视频标题", "关键词",
            enable_lead_pm=True, video_started_at=None, already_open=True,
        )

        # Phase A+B 输出保留
        self.assertTrue(result.get("lead_reply_sent"),
            f"Phase B 应设置 lead_reply_sent=True，实际 {result.get('lead_reply_sent')}")
        self.assertEqual(result.get("lead_comment_text"), "意向1",
            f"lead_comment_text 应保留，实际 {result.get('lead_comment_text')}")
        self.assertEqual(result.get("lead_pm_success_count"), 1,
            f"Phase 2 应有 1 条 PM 成功，实际 {result.get('lead_pm_success_count')}")

        # ProcessCommentSectionAction 收到正确的 video_title/keyword
        _, kwargs = mock_process_action.call_args
        self.assertEqual(kwargs.get("video_title"), "视频标题",
            f"应传递 video_title，实际 {kwargs.get('video_title')}")
        self.assertEqual(kwargs.get("keyword"), "关键词",
            f"应传递 keyword，实际 {kwargs.get('keyword')}")
        self.assertEqual(kwargs.get("keep_open_after_lead"), False,
            f"Issue 1: 应传 keep_open_after_lead=False，实际 {kwargs.get('keep_open_after_lead')}")


if __name__ == "__main__":
    unittest.main()
