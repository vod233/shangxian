import unittest
from unittest.mock import patch, MagicMock

from dy.actions.commenting import (
    OpenCommentSectionAction,
    PostCommentAction,
    ProcessCommentSectionAction,
)
from dy.actions.interaction import (
    DoubleClickLikeAction,
    FollowAuthorAction,
    GetCurrentVideoLinkAction,
)
from dy.actions.navigation import SwipeNextVideoAction
from dy.task_runner import TikTokTaskFlow


class FakeRunner:
    def __init__(self):
        self.device = object()
        self.calls = []
        self.state = "video_page"
        # _run_comment_lead_safely 手动实例化 ProcessCommentSectionAction 时取 app_mgr
        self.app_mgr = None

    def run_action(self, action_class, *args, **kwargs):
        self.calls.append((action_class, args, kwargs))
        if action_class is GetCurrentVideoLinkAction:
            return ("https://v.douyin.com/test/", "share-token", "这是一个用于测试的视频标题")
        if action_class is FollowAuthorAction:
            return {"followed": True, "private_message_sent": kwargs.get("private_message_allowed", False)}
        if action_class is OpenCommentSectionAction:
            self.state = "comment_panel"
            return True
        if action_class is ProcessCommentSectionAction:
            self.state = "video_page"
            return True
        return True


class FakeDB:
    def __init__(self):
        self.interactions = []

    def get_daily_stats(self):
        return {"videos": 0, "likes": 0, "comments": 0, "follows": 0, "private_messages": 0}

    def record_video(self, *args, **kwargs):
        return True

    def update_interaction(self, video_id, action_type):
        self.interactions.append(action_type)
        return True

    def save_ai_reply(self, *args, **kwargs):
        return True

    def update_video_detail(self, video_id, **kwargs):
        # _video_loop 在各阶段记录详细状态，测试只关心 interactions/calls
        return True


class FakeAnti:
    def __init__(self, private_message_allowed=True):
        self.private_message_allowed = private_message_allowed

    def can_do(self, action_type):
        if action_type == "private_message":
            return self.private_message_allowed
        return True

    def should_interact(self, action_type):
        if action_type == "long_watch":
            return False
        raise AssertionError(f"interactive action should not use probability gate: {action_type}")


class FakeReplyAgent:
    def generate_reply(self, **kwargs):
        return "测试评论"

    def is_enabled(self):
        return True


def make_fake_process_action():
    """构造 FakeProcessCommentSectionAction 工厂。

    用真实空值属性（lead_comment_node=None, intent_items=[]）替代 MagicMock，
    让 _run_comment_lead_safely 的属性读取逻辑真实运行，避免 MagicMock 触发
    len(intent_items) 抛 TypeError 被 except Exception 吞掉（假绿）。
    返回 (FakeAction类, instances列表) 供测试断言实例化与 perform 调用。
    """
    instances = []

    class FakeProcessCommentSectionAction:
        def __init__(self, **kwargs):
            self.lead_comment_node = None
            self.lead_reply_sent = False
            self.intent_items = []
            self.inline_pm_completed = False
            self.lead_pm_sent_count = 0
            self.lead_reply_fallback_count = 0
            self.lead_comment_text = ""
            self.lead_reply_text = ""
            self.perform_called = False
            instances.append(self)

        def perform(self):
            self.perform_called = True
            return True

        def _close_comment_section(self):
            pass

        def _return_from_profile_to_comments(self, max_back=4):
            return True

        def _comment_panel_open(self):
            return True

    return FakeProcessCommentSectionAction, instances


def build_flow(interaction_config, private_message_allowed=True):
    flow = TikTokTaskFlow.__new__(TikTokTaskFlow)
    flow.runner = FakeRunner()
    flow.config = {
        "crawler": {
            "max_videos_per_keyword": 1,
            "max_daily_videos": 100,
            "min_video_stay": 0,
            "max_video_stay": 0,
        },
        "interaction": interaction_config,
    }
    flow.db = FakeDB()
    flow.reply_agent = FakeReplyAgent()
    flow.anti = FakeAnti(private_message_allowed=private_message_allowed)
    flow.last_share_token = None
    flow.last_description = None
    flow.current_keyword = "测试关键词"
    flow.is_stopped = False
    flow.is_paused = False
    # _video_loop 内部状态：__new__ 绕过 __init__，需手动补齐（task_runner.py:81-82）
    flow.keyword_index = 0
    flow.video_index = 0
    flow._interruptible_sleep = lambda seconds: None
    flow._recover_to_video_page = lambda reason, max_back=5: True
    flow._detect_page_state = lambda: flow.runner.state
    flow._dismiss_video_context_menu_if_present = lambda: False
    return flow


class TestDouyinInteractionSwitches(unittest.TestCase):
    def run_flow(self, flow):
        with patch("dy.task_runner.BehaviorRandomizer.maybe_fast_scroll", return_value=False), \
             patch("dy.task_runner.BehaviorRandomizer.maybe_rewind", return_value=False), \
             patch("dy.task_runner.BehaviorRandomizer.maybe_browse_home_feed", return_value=False), \
             patch("dy.task_runner.BehaviorRandomizer.maybe_pause_and_think", return_value=False):
            flow._video_loop()

    def test_mode1_loads_author_follow_and_pm_without_probability_gate(self):
        """business_mode=1 → 走作者私信流：B.1 点赞 + B.2 关注+私信。V+C 不调用。

        ProcessCommentSectionAction 在 mode1 下不应被实例化（它绕过 run_action，
        简单 assertNotIn 测不到，需 patch 验证 instances 为空）。
        """
        flow = build_flow({
            "business_mode": 1,
            "enable_like": True,
            "enable_author_follow": True,
            "enable_private_message": True,
            "enable_video_comment": True,  # mode=1 时被忽略
            "enable_comment_lead": True,
        })

        FakeAction, instances = make_fake_process_action()
        with patch("dy.task_runner.ProcessCommentSectionAction", FakeAction):
            self.run_flow(flow)

        called_actions = [call[0] for call in flow.runner.calls]
        self.assertIn(DoubleClickLikeAction, called_actions)
        self.assertIn(FollowAuthorAction, called_actions)
        self.assertIn(SwipeNextVideoAction, called_actions)
        self.assertIn("private_message", flow.db.interactions)
        # mode=1 互斥：评论区链路不应被调用
        self.assertNotIn(PostCommentAction, called_actions)
        self.assertNotIn(OpenCommentSectionAction, called_actions)
        # ProcessCommentSectionAction 绕过 run_action，需显式验证未被实例化
        self.assertEqual(0, len(instances), "mode=1 不应实例化 ProcessCommentSectionAction")

    def test_mode2_loads_comment_ecosystem_without_probability_gate(self):
        """business_mode=2 → 走评论区截流：B.1 点赞 + B.3 主评 + B.4 截流。F 不调用。

        ProcessCommentSectionAction 在 _run_comment_lead_safely 中直接实例化
        并 perform()，不走 run_action，故用 FakeAction 替代并验证 perform 被调用。
        FakeAction 属性返回真实空值，确保 perform 之后的属性读取逻辑真实运行。
        """
        flow = build_flow({
            "business_mode": 2,
            "enable_like": True,
            "enable_author_follow": True,  # mode=2 时被忽略
            "enable_private_message": True,
            "enable_video_comment": True,
            "enable_comment_lead": True,
        })

        FakeAction, instances = make_fake_process_action()
        with patch("dy.task_runner.ProcessCommentSectionAction", FakeAction):
            self.run_flow(flow)

        called_actions = [call[0] for call in flow.runner.calls]
        self.assertIn(DoubleClickLikeAction, called_actions)
        self.assertIn(PostCommentAction, called_actions)
        self.assertIn(OpenCommentSectionAction, called_actions)
        self.assertIn(SwipeNextVideoAction, called_actions)
        # ProcessCommentSectionAction 直接实例化，验证 perform 被调用
        self.assertEqual(1, len(instances), "ProcessCommentSectionAction 应被实例化一次")
        self.assertTrue(instances[0].perform_called, "perform() 应被调用")
        # mode=2 互斥：作者关注/私信不应被调用
        self.assertNotIn(FollowAuthorAction, called_actions)
        self.assertNotIn("follow", flow.db.interactions, "mode=2 不应记录作者关注")
        self.assertNotIn("private_message", flow.db.interactions, "mode=2 不应记录作者私信")

    def test_mode0_only_likes_without_follow_or_comment(self):
        """business_mode=0 → 仅点赞，不调用关注/评论/截流任何 action。

        mode=0 显式指定 + 所有互动开关关闭 → _resolve_business_mode 返回 0，
        _video_loop 模式分流不进任何 pipeline 分支，只执行全局前置点赞。
        """
        flow = build_flow({
            "business_mode": 0,
            "enable_like": True,
            "enable_author_follow": False,
            "enable_private_message": False,
            "enable_video_comment": False,
            "enable_comment_lead": False,
        })

        FakeAction, instances = make_fake_process_action()
        with patch("dy.task_runner.ProcessCommentSectionAction", FakeAction):
            self.run_flow(flow)

        called_actions = [call[0] for call in flow.runner.calls]
        self.assertIn(DoubleClickLikeAction, called_actions)
        self.assertNotIn(FollowAuthorAction, called_actions)
        self.assertNotIn(PostCommentAction, called_actions)
        self.assertNotIn(OpenCommentSectionAction, called_actions)
        self.assertEqual(0, len(instances), "mode=0 不应实例化 ProcessCommentSectionAction")
        self.assertNotIn("follow", flow.db.interactions)
        self.assertNotIn("private_message", flow.db.interactions)

    def test_disabled_switches_skip_unselected_actions(self):
        flow = build_flow({
            "enable_like": False,
            "enable_author_follow": False,
            "enable_private_message": True,
            "enable_video_comment": False,
            "enable_comment_lead": False,
        })

        self.run_flow(flow)

        called_actions = [call[0] for call in flow.runner.calls]
        self.assertNotIn(DoubleClickLikeAction, called_actions)
        self.assertNotIn(FollowAuthorAction, called_actions)
        self.assertNotIn(PostCommentAction, called_actions)
        self.assertNotIn(OpenCommentSectionAction, called_actions)
        self.assertNotIn(ProcessCommentSectionAction, called_actions)

    def test_private_message_limit_is_passed_into_author_action(self):
        flow = build_flow({
            "enable_like": False,
            "enable_author_follow": True,
            "enable_private_message": True,
            "enable_video_comment": False,
            "enable_comment_lead": False,
        }, private_message_allowed=False)

        self.run_flow(flow)

        follow_calls = [call for call in flow.runner.calls if call[0] is FollowAuthorAction]
        self.assertEqual(1, len(follow_calls))
        self.assertFalse(follow_calls[0][2]["private_message_allowed"])
        self.assertNotIn("private_message", flow.db.interactions)


if __name__ == "__main__":
    unittest.main()
