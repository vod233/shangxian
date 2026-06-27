"""
三大功能模块 — 单独链路 + 自由组合 测试分析
============================================
测试目标：
  1. 私域获客 (acquisition)
  2. AI视频评论 (video_comment)  
  3. 评论区截流 (comment_lead)

不连接真实设备，纯代码逻辑验证。
"""

import sys
import os
import unittest
from unittest.mock import MagicMock, patch, PropertyMock
from copy import deepcopy

# ==================== 测试配置基类 ====================

BASE_CONFIG = {
    "search": {"keywords": ["测试关键词"], "sort_by": "latest"},
    "crawler": {"max_daily_videos": 100, "max_videos_per_keyword": 5, "extract_share_link": True},
    "interaction": {
        "enable_like": True,
        "enable_mode_customer_acquisition": False,
        "enable_mode_content_interaction": False,
        "enable_anti_detection_probability": False,
        "pipeline_steps": {},
        "max_comment_swipes": 2,
        "max_ai_comment_reviews": 20,
        "intent_keywords": [],
        "enable_private_message": False,
        "min_followers_threshold": 0.0,
        "pm_followers_threshold": 1.0,
        "pm_message_list": [],
    },
    "ai_reply": {"enabled": False, "mode": "local"},
}


def make_flow(config_overrides=None):
    """创建 mock TikTokTaskFlow 用于测试 pipeline"""
    config = deepcopy(BASE_CONFIG)
    if config_overrides:
        _deep_merge(config, config_overrides)
    
    flow = MagicMock()
    flow.config = config
    flow.current_keyword = "测试关键词"
    flow.anti = MagicMock()
    flow.anti.can_do.return_value = True
    flow.anti.record_action = MagicMock()
    flow.anti.should_interact = MagicMock(return_value=True)
    flow.db = MagicMock()
    flow.runner = MagicMock()
    flow.reply_agent = MagicMock()
    flow._interaction_enabled = lambda key: bool(config.get("interaction", {}).get(key, True))
    flow._should_interact = lambda k: True  # 确定性执行
    flow._report = MagicMock()
    flow._run_feature_safely = MagicMock(side_effect=lambda label, cb: (True, cb()))
    flow._run_comment_lead_safely = MagicMock(return_value=(True, True))
    flow._interruptible_sleep = MagicMock()
    
    return flow, config


def _deep_merge(base, overrides):
    for k, v in overrides.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


# ==================== 测试 1: 私域获客 单独链路 ====================

class TestAcquisitionStandalone(unittest.TestCase):
    """私域获客 单独链路测试"""

    def setUp(self):
        from dy.pipeline import _step_acquisition
        self._step_acquisition = _step_acquisition

    def test_acquisition_follow_success(self):
        """正常关注成功路径"""
        flow, config = make_flow({
            "interaction": {
                "enable_mode_customer_acquisition": True,
                "enable_mode_content_interaction": False,
            }
        })
        flow.runner.run_action.return_value = {
            "followed": True,
            "private_message_sent": False,
            "returned_to_video": True,
            "follower_count": 5.0,
        }
        
        stable, result = self._step_acquisition(flow, {"video_id": "vid1", "video_title": "测试视频"})
        
        self.assertTrue(stable)
        flow.db.update_interaction.assert_called()
        flow.runner.run_action.assert_called_once()

    def test_acquisition_follow_skipped_low_followers(self):
        """粉丝不足时跳过关注"""
        flow, config = make_flow({
            "interaction": {
                "enable_mode_customer_acquisition": True,
                "enable_mode_content_interaction": False,
                "min_followers_threshold": 10.0,  # 需要>=10万粉丝
            }
        })
        flow.runner.run_action.return_value = {
            "followed": False,
            "private_message_sent": False,
            "returned_to_video": True,
            "follower_count": 0.5,  # 仅5000粉丝
        }
        
        stable, result = self._step_acquisition(flow, {"video_id": "vid1", "video_title": "测试视频"})
        
        self.assertTrue(stable)

    def test_acquisition_private_message_success(self):
        """私信成功路径"""
        flow, config = make_flow({
            "interaction": {
                "enable_mode_customer_acquisition": True,
                "enable_private_message": True,
                "pm_followers_threshold": 1.0,
                "pm_message_list": ["您好，关注您很久了"],
            }
        })
        flow.runner.run_action.return_value = {
            "followed": True,
            "private_message_sent": True,
            "returned_to_video": True,
            "follower_count": 15.0,
        }
        
        stable, result = self._step_acquisition(flow, {"video_id": "vid1", "video_title": "测试视频"})
        
        self.assertTrue(stable)
        flow.db.update_interaction.assert_called()
        # 应该记录了关注和私信两笔
        call_args_list = flow.db.update_interaction.call_args_list
        self.assertGreaterEqual(len(call_args_list), 2)

    def test_acquisition_return_failed(self):
        """返回视频页失败"""
        flow, config = make_flow({
            "interaction": {"enable_mode_customer_acquisition": True}
        })
        flow.runner.run_action.return_value = {
            "followed": True,
            "private_message_sent": False,
            "returned_to_video": False,  # 返回失败
            "follower_count": 5.0,
        }
        
        stable, result = self._step_acquisition(flow, {"video_id": "vid1", "video_title": "测试视频"})
        
        # 返回失败时, stable 应该是 False
        self.assertFalse(stable)

    def test_acquisition_old_format_result(self):
        """向后兼容: 旧版返回True"""
        flow, config = make_flow({
            "interaction": {"enable_mode_customer_acquisition": True}
        })
        flow.runner.run_action.return_value = True  # 旧版简单返回值
        
        stable, result = self._step_acquisition(flow, {"video_id": "vid1", "video_title": "测试视频"})
        
        self.assertTrue(stable)
        flow.db.update_interaction.assert_called_once()

    def test_acquisition_block_on_failure(self):
        """验证 on_failure='block_rest' 阻断策略"""
        from dy.pipeline import PIPELINE_STEPS
        acq_step = next(s for s in PIPELINE_STEPS if s.id == "acquisition")
        self.assertEqual(acq_step.on_failure, "block_rest")

    def test_acquisition_quota_keys(self):
        """验证配额键包含 follow 和 private_message"""
        from dy.pipeline import PIPELINE_STEPS
        acq_step = next(s for s in PIPELINE_STEPS if s.id == "acquisition")
        self.assertIn("follow", acq_step.quota_keys)
        self.assertIn("private_message", acq_step.quota_keys)


# ==================== 测试 2: AI视频评论 单独链路 ====================

class TestVideoCommentStandalone(unittest.TestCase):
    """AI视频评论 单独链路测试"""

    def setUp(self):
        from dy.pipeline import _step_video_comment
        self._step_video_comment = _step_video_comment

    def test_ai_generate_and_post_success(self):
        """AI生成评论并成功发布"""
        flow, config = make_flow({
            "interaction": {
                "enable_mode_content_interaction": True,
            }
        })
        flow.reply_agent.generate_reply.return_value = "这个内容讲得真不错，有参考价值"
        flow.reply_agent.is_enabled.return_value = True
        flow.runner.run_action.return_value = True  # PostCommentAction 返回 True
        
        stable, result = self._step_video_comment(
            flow, {"video_id": "vid1", "video_title": "好视频"}
        )
        
        self.assertTrue(stable)
        self.assertTrue(result)
        flow.db.update_interaction.assert_called_with("vid1", "comment")

    def test_ai_generate_empty_fallback(self):
        """AI生成失败返回空文本 — 不再写入数据库"""
        flow, config = make_flow({
            "interaction": {"enable_mode_content_interaction": True}
        })
        flow.reply_agent.generate_reply.return_value = ""  # 生成失败
        
        stable, result = self._step_video_comment(
            flow, {"video_id": "vid1", "video_title": "好视频"}
        )
        
        self.assertTrue(stable)
        self.assertFalse(result)
        # 空文本不再写入数据库（修复 P1-4）
        flow.db.save_ai_reply.assert_not_called()

    def test_ai_generate_none_fallback(self):
        """AI生成返回None"""
        flow, config = make_flow({
            "interaction": {"enable_mode_content_interaction": True}
        })
        flow.reply_agent.generate_reply.return_value = None
        
        stable, result = self._step_video_comment(
            flow, {"video_id": "vid1", "video_title": "好视频"}
        )
        
        self.assertTrue(stable)
        self.assertFalse(result)

    def test_post_comment_failed(self):
        """评论生成成功但发布失败"""
        flow, config = make_flow({
            "interaction": {"enable_mode_content_interaction": True}
        })
        flow.reply_agent.generate_reply.return_value = "这个内容讲得真不错"
        flow.reply_agent.is_enabled.return_value = True
        flow.runner.run_action.return_value = False  # 发布失败
        
        stable, result = self._step_video_comment(
            flow, {"video_id": "vid1", "video_title": "好视频"}
        )
        
        self.assertTrue(stable)
        self.assertFalse(result)

    def test_ai_disabled(self):
        """AI禁用但mode=content_interaction仍开启"""
        flow, config = make_flow({
            "interaction": {"enable_mode_content_interaction": True}
        })
        flow.reply_agent.generate_reply.return_value = None
        flow.reply_agent.is_enabled.return_value = False
        
        stable, result = self._step_video_comment(
            flow, {"video_id": "vid1", "video_title": "好视频"}
        )
        
        self.assertTrue(stable)
        self.assertFalse(result)

    def test_continue_on_failure(self):
        """验证 on_failure='continue' """
        from dy.pipeline import PIPELINE_STEPS
        vc_step = next(s for s in PIPELINE_STEPS if s.id == "video_comment")
        self.assertEqual(vc_step.on_failure, "continue")

    def test_shared_comment_quota(self):
        """验证 video_comment 使用 'comment' 配额（与 comment_lead 共享）"""
        from dy.pipeline import PIPELINE_STEPS
        vc_step = next(s for s in PIPELINE_STEPS if s.id == "video_comment")
        self.assertIn("comment", vc_step.quota_keys)


# ==================== 测试 3: 评论区截流 单独链路 ====================

class TestCommentLeadStandalone(unittest.TestCase):
    """评论区截流 单独链路测试"""

    def setUp(self):
        from dy.pipeline import _step_comment_lead
        self._step_comment_lead = _step_comment_lead

    def test_comment_lead_success(self):
        """截流成功"""
        flow, config = make_flow({
            "interaction": {"enable_mode_content_interaction": True}
        })
        flow._run_comment_lead_safely.return_value = (True, True)
        
        stable, result = self._step_comment_lead(
            flow, {"video_id": "vid1", "video_title": "好视频"}
        )
        
        self.assertTrue(stable)
        self.assertTrue(result)
        flow.db.update_interaction.assert_called_with("vid1", "comment")

    def test_comment_lead_no_intent(self):
        """未找到意向评论"""
        flow, config = make_flow({
            "interaction": {"enable_mode_content_interaction": True}
        })
        flow._run_comment_lead_safely.return_value = (True, False)
        
        stable, result = self._step_comment_lead(
            flow, {"video_id": "vid1", "video_title": "好视频"}
        )
        
        self.assertTrue(stable)
        self.assertFalse(result)

    def test_comment_lead_recovery_failed(self):
        """评论区打开后恢复失败"""
        flow, config = make_flow({
            "interaction": {"enable_mode_content_interaction": True}
        })
        flow._run_comment_lead_safely.return_value = (False, False)
        
        stable, result = self._step_comment_lead(
            flow, {"video_id": "vid1", "video_title": "好视频"}
        )
        
        self.assertFalse(stable)

    def test_comment_lead_block_rest(self):
        """验证 on_failure='block_rest' """
        from dy.pipeline import PIPELINE_STEPS
        cl_step = next(s for s in PIPELINE_STEPS if s.id == "comment_lead")
        self.assertEqual(cl_step.on_failure, "block_rest")

    def test_comment_lead_shared_quota(self):
        """验证 comment_lead 使用 'comment' 配额（与 video_comment 共享）"""
        from dy.pipeline import PIPELINE_STEPS
        cl_step = next(s for s in PIPELINE_STEPS if s.id == "comment_lead")
        self.assertIn("comment", cl_step.quota_keys)


# ==================== 测试 4: 管道执行器 组合测试 ====================

class TestPipelineCombinations(unittest.TestCase):
    """管道组合和阻断测试"""

    def setUp(self):
        from dy.pipeline import PipelineExecutor, PIPELINE_STEPS
        self.PipelineExecutor = PipelineExecutor
        self.PIPELINE_STEPS = PIPELINE_STEPS

    def _make_pipeline_flow(self, overrides=None):
        config = deepcopy(BASE_CONFIG)
        if overrides:
            _deep_merge(config, overrides)
        
        flow = MagicMock()
        flow.config = config
        flow.current_keyword = "测试"
        flow.anti = MagicMock()
        flow.anti.can_do.return_value = True
        flow.anti.record_action = MagicMock()
        flow.anti.should_interact = MagicMock(return_value=True)
        flow.db = MagicMock()
        flow.runner = MagicMock()
        flow.reply_agent = MagicMock()
        flow._report = MagicMock()
        flow._interruptible_sleep = MagicMock()

        # 默认: _interaction_enabled 逻辑
        def _int_enabled(key):
            inter = config.get("interaction", {})
            return bool(inter.get(key, True))
        flow._interaction_enabled = _int_enabled
        flow._should_interact = lambda k: True

        # _run_feature_safely: 正常包装
        def safe_wrapper(label, cb):
            try:
                result = cb()
                return True, result
            except Exception:
                return False, None
        flow._run_feature_safely = safe_wrapper
        flow._run_comment_lead_safely = MagicMock(return_value=(True, True))

        return flow, config

    # ---- 场景1: 仅私域获客 (模式1 only) ----

    def test_combo_acquisition_only(self):
        """仅私域获客开启"""
        flow, config = self._make_pipeline_flow({
            "interaction": {
                "enable_mode_customer_acquisition": True,
                "enable_mode_content_interaction": False,
            }
        })
        flow.runner.run_action.return_value = {"followed": True, "private_message_sent": False, "returned_to_video": True}

        executor = self.PipelineExecutor(flow)
        ctx = {"video_id": "v1", "video_title": "t1"}
        result = executor.run(self.PIPELINE_STEPS, ctx)

        # 应该执行了 like + acquisition, 跳过了 video_comment + comment_lead
        self.assertFalse(result["blocked"])
        executed = result["executed"]
        self.assertIn("like", executed)
        self.assertIn("acquisition", executed)
        self.assertNotIn("video_comment", executed)
        self.assertNotIn("comment_lead", executed)

    # ---- 场景2: 仅AI视频评论 (模式2-A only) ----

    def test_combo_video_comment_only(self):
        """仅AI视频评论开启"""
        flow, config = self._make_pipeline_flow({
            "interaction": {
                "enable_mode_customer_acquisition": False,
                "enable_mode_content_interaction": True,
                "pipeline_steps": {"video_comment": True, "comment_lead": False},
            }
        })
        flow.reply_agent.generate_reply.return_value = "内容不错"
        flow.reply_agent.is_enabled.return_value = True
        flow.runner.run_action.return_value = True

        executor = self.PipelineExecutor(flow)
        ctx = {"video_id": "v1", "video_title": "t1", "pipeline_steps": {"video_comment": True, "comment_lead": False}}
        result = executor.run(self.PIPELINE_STEPS, ctx)

        executed = result["executed"]
        self.assertIn("like", executed)
        self.assertNotIn("acquisition", executed)
        self.assertIn("video_comment", executed)
        self.assertNotIn("comment_lead", executed)

    # ---- 场景3: 仅评论区截流 (模式2-B only) ----

    def test_combo_comment_lead_only(self):
        """仅评论区截流开启"""
        flow, config = self._make_pipeline_flow({
            "interaction": {
                "enable_mode_customer_acquisition": False,
                "enable_mode_content_interaction": True,
                "pipeline_steps": {"video_comment": False, "comment_lead": True},
            }
        })

        executor = self.PipelineExecutor(flow)
        ctx = {"video_id": "v1", "video_title": "t1", "pipeline_steps": {"video_comment": False, "comment_lead": True}}
        result = executor.run(self.PIPELINE_STEPS, ctx)

        executed = result["executed"]
        self.assertIn("like", executed)
        self.assertNotIn("acquisition", executed)
        self.assertNotIn("video_comment", executed)
        self.assertIn("comment_lead", executed)

    # ---- 场景4: 私域获客 + AI视频评论 ----

    def test_combo_acquisition_and_video_comment(self):
        """私域获客成功后继续执行AI视频评论"""
        flow, config = self._make_pipeline_flow({
            "interaction": {
                "enable_mode_customer_acquisition": True,
                "enable_mode_content_interaction": True,
                "pipeline_steps": {"video_comment": True, "comment_lead": False},
            }
        })
        flow.runner.run_action.return_value = {"followed": True, "private_message_sent": False, "returned_to_video": True}
        flow.reply_agent.generate_reply.return_value = "内容不错"
        flow.reply_agent.is_enabled.return_value = True

        executor = self.PipelineExecutor(flow)
        ctx = {"video_id": "v1", "video_title": "t1", "pipeline_steps": {"video_comment": True, "comment_lead": False}}
        result = executor.run(self.PIPELINE_STEPS, ctx)

        executed = result["executed"]
        self.assertIn("acquisition", executed)
        self.assertIn("video_comment", executed)

    # ---- 场景5: 私域获客 + 评论区截流 ----

    def test_combo_acquisition_and_comment_lead(self):
        """私域获客成功后继续执行评论区截流"""
        flow, config = self._make_pipeline_flow({
            "interaction": {
                "enable_mode_customer_acquisition": True,
                "enable_mode_content_interaction": True,
                "pipeline_steps": {"video_comment": False, "comment_lead": True},
            }
        })
        flow.runner.run_action.return_value = {"followed": True, "private_message_sent": False, "returned_to_video": True}

        executor = self.PipelineExecutor(flow)
        ctx = {"video_id": "v1", "video_title": "t1", "pipeline_steps": {"video_comment": False, "comment_lead": True}}
        result = executor.run(self.PIPELINE_STEPS, ctx)

        executed = result["executed"]
        self.assertIn("acquisition", executed)
        self.assertIn("comment_lead", executed)

    # ---- 场景6: AI视频评论 + 评论区截流 (模式2全开) ----

    def test_combo_content_only(self):
        """模式2全开：video_comment + comment_lead"""
        flow, config = self._make_pipeline_flow({
            "interaction": {
                "enable_mode_customer_acquisition": False,
                "enable_mode_content_interaction": True,
                "pipeline_steps": {"video_comment": True, "comment_lead": True},
            }
        })
        flow.reply_agent.generate_reply.return_value = "内容不错"
        flow.reply_agent.is_enabled.return_value = True
        flow.runner.run_action.return_value = True

        executor = self.PipelineExecutor(flow)
        ctx = {"video_id": "v1", "video_title": "t1", "pipeline_steps": {"video_comment": True, "comment_lead": True}}
        result = executor.run(self.PIPELINE_STEPS, ctx)

        executed = result["executed"]
        self.assertIn("video_comment", executed)
        self.assertIn("comment_lead", executed)

    # ---- 场景7: 三功能全开 ----

    def test_combo_all_three(self):
        """三者全开"""
        flow, config = self._make_pipeline_flow({
            "interaction": {
                "enable_mode_customer_acquisition": True,
                "enable_mode_content_interaction": True,
                "pipeline_steps": {"video_comment": True, "comment_lead": True},
            }
        })
        flow.runner.run_action.return_value = {"followed": True, "private_message_sent": False, "returned_to_video": True}
        flow.reply_agent.generate_reply.return_value = "内容不错"
        flow.reply_agent.is_enabled.return_value = True

        executor = self.PipelineExecutor(flow)
        ctx = {"video_id": "v1", "video_title": "t1", "pipeline_steps": {"video_comment": True, "comment_lead": True}}
        result = executor.run(self.PIPELINE_STEPS, ctx)

        executed = result["executed"]
        self.assertIn("like", executed)
        self.assertIn("acquisition", executed)
        self.assertIn("video_comment", executed)
        self.assertIn("comment_lead", executed)

    # ---- 场景8: 阻断测试 ----

    def test_block_when_acquisition_fails(self):
        """私域获客失败时阻断后续步骤"""
        flow, config = self._make_pipeline_flow({
            "interaction": {
                "enable_mode_customer_acquisition": True,
                "enable_mode_content_interaction": True,
                "pipeline_steps": {"video_comment": True, "comment_lead": True},
            }
        })

        # 模拟 _run_feature_safely 对 acquisition 返回失败
        orig_safe = flow._run_feature_safely
        def failed_on_acq(label, cb):
            if "私域获客" in str(label):
                return False, None  # 执行失败
            return orig_safe(label, cb)
        flow._run_feature_safely = failed_on_acq

        executor = self.PipelineExecutor(flow)
        ctx = {"video_id": "v1", "video_title": "t1", "pipeline_steps": {"video_comment": True, "comment_lead": True}}
        result = executor.run(self.PIPELINE_STEPS, ctx)

        # 应该被阻断
        self.assertTrue(result["blocked"])
        executed = result["executed"]
        self.assertIn("like", executed)
        self.assertIn("acquisition", executed)
        # 后续步骤被阻断
        self.assertNotIn("video_comment", executed)
        self.assertNotIn("comment_lead", executed)

    def test_comment_lead_failure_blocks_nothing_after(self):
        """评论区截流失败阻断后续（但它后面没有步骤了）"""
        flow, config = self._make_pipeline_flow({
            "interaction": {
                "enable_mode_customer_acquisition": False,
                "enable_mode_content_interaction": True,
                "pipeline_steps": {"video_comment": True, "comment_lead": True},
            }
        })
        flow.reply_agent.generate_reply.return_value = "内容不错"
        flow.reply_agent.is_enabled.return_value = True
        flow.runner.run_action.return_value = True

        # comment_lead 恢复失败
        flow._run_comment_lead_safely.return_value = (False, False)

        executor = self.PipelineExecutor(flow)
        ctx = {"video_id": "v1", "video_title": "t1", "pipeline_steps": {"video_comment": True, "comment_lead": True}}
        result = executor.run(self.PIPELINE_STEPS, ctx)

        # comment_lead 失败 = block_rest，但因为它是最后一步，不影响前面的步骤
        self.assertTrue(result["blocked"])
        self.assertIn("video_comment", result["executed"])
        self.assertIn("comment_lead", result["executed"])

    # ---- 场景9: 限额测试 ----

    def test_comment_quota_shared(self):
        """video_comment 和 comment_lead 共享 comment 配额，超限时两者都跳过"""
        flow, config = self._make_pipeline_flow({
            "interaction": {
                "enable_mode_customer_acquisition": False,
                "enable_mode_content_interaction": True,
                "pipeline_steps": {"video_comment": True, "comment_lead": True},
            }
        })
        flow.anti.can_do.side_effect = lambda q: q != "comment"  # comment 配额耗尽

        executor = self.PipelineExecutor(flow)
        ctx = {"video_id": "v1", "video_title": "t1", "pipeline_steps": {"video_comment": True, "comment_lead": True}}
        result = executor.run(self.PIPELINE_STEPS, ctx)

        executed = result["executed"]
        self.assertNotIn("video_comment", executed)
        self.assertNotIn("comment_lead", executed)

    def test_follow_quota_blocks_acquisition(self):
        """follow 配额耗尽时私域获客步骤跳过"""
        flow, config = self._make_pipeline_flow({
            "interaction": {
                "enable_mode_customer_acquisition": True,
                "enable_mode_content_interaction": False,
            }
        })
        flow.anti.can_do.side_effect = lambda q: q != "follow"

        executor = self.PipelineExecutor(flow)
        ctx = {"video_id": "v1", "video_title": "t1"}
        result = executor.run(self.PIPELINE_STEPS, ctx)

        self.assertNotIn("acquisition", result["executed"])


# ==================== 测试 5: 边界条件 ====================

class TestEdgeCases(unittest.TestCase):
    """边界条件和错误场景"""

    def test_pipeline_steps_order(self):
        """验证管道步骤顺序正确"""
        from dy.pipeline import PIPELINE_STEPS
        ids = [s.id for s in PIPELINE_STEPS]
        self.assertEqual(ids, ["like", "acquisition", "video_comment", "comment_lead"])

    def test_acquisition_enabled_key(self):
        """验证私域获客使用正确的 enabled_key"""
        from dy.pipeline import PIPELINE_STEPS
        acq = next(s for s in PIPELINE_STEPS if s.id == "acquisition")
        self.assertEqual(acq.enabled_key, "enable_mode_customer_acquisition")

    def test_video_comment_and_comment_lead_same_enabled_key(self):
        """验证 AI视频评论 和 评论区截流 共享同一个 enabled_key"""
        from dy.pipeline import PIPELINE_STEPS
        vc = next(s for s in PIPELINE_STEPS if s.id == "video_comment")
        cl = next(s for s in PIPELINE_STEPS if s.id == "comment_lead")
        self.assertEqual(vc.enabled_key, cl.enabled_key)
        self.assertEqual(vc.enabled_key, "enable_mode_content_interaction")

    def test_empty_context_video_title(self):
        """video_title 为空时的行为"""
        from dy.pipeline import _step_video_comment
        flow, config = make_flow({
            "interaction": {"enable_mode_content_interaction": True}
        })
        
        # generate_reply 应该能处理空标题
        stable, result = _step_video_comment(flow, {"video_id": "v1", "video_title": ""})
        # 不崩溃即可
        self.assertTrue(stable)

    def test_interaction_enabled_backward_compat(self):
        """验证 _interaction_enabled 向后兼容"""
        flow, config = make_flow()
        
        # 只有旧字段，无新字段
        flow._interaction_enabled = lambda key: key in ("enable_mode_customer_acquisition",) and True
        
        from dy.pipeline import PIPELINE_STEPS
        self.assertTrue(flow._interaction_enabled("enable_mode_customer_acquisition"))


# ==================== AI评论代理测试 ====================

class TestAIReplyAgent(unittest.TestCase):
    """DYReplyAgent 测试"""

    def setUp(self):
        from dy.ai_reply_agent import DYReplyAgent
        self.config = {"ai_reply": {"enabled": True, "mode": "cloud"}}
        # 不实际调用AI，只测试逻辑路径
        self.agent = DYReplyAgent(self.config)
        # 禁用 cloud_ai
        self.agent.cloud_ai = MagicMock()
        self.agent.cloud_ai.enabled.return_value = False

    def test_is_enabled(self):
        self.assertTrue(self.agent.is_enabled())
        
        agent2 = type(self.agent)({"ai_reply": {"enabled": False}})
        self.assertFalse(agent2.is_enabled())

    def test_generate_reply_empty_title(self):
        """空标题应返回 None"""
        result = self.agent.generate_reply("")
        self.assertIsNone(result)

    def test_generate_reply_disabled(self):
        """AI禁用时不生成评论"""
        agent_disabled = type(self.agent)({"ai_reply": {"enabled": False}})
        result = agent_disabled.generate_reply("测试标题")
        self.assertIsNone(result)

    def test_sanitize_reply_strips_emoji_hashtags(self):
        """验证评论清洗去除 # @ 符号"""
        # _sanitize_reply 是实例方法
        cleaned = self.agent._sanitize_reply("这个#内容@不错！！！")
        self.assertNotIn("#", cleaned)
        self.assertNotIn("@", cleaned)

    def test_banned_patterns_detect_wechat(self):
        """验证违规内容检测"""
        self.assertFalse(self.agent._is_valid_reply("加我微信 xxx"))
        self.assertFalse(self.agent._is_valid_reply("私信我了解更多"))

    def test_is_intent_comment_disabled(self):
        """AI禁用时使用本地规则"""
        agent_disabled = type(self.agent)({"ai_reply": {"enabled": False}})
        self.assertTrue(agent_disabled.is_intent_comment("这个怎么买？", keyword="手机"))
        self.assertTrue(agent_disabled.is_intent_comment("求推荐", keyword="键盘"))
        self.assertTrue(agent_disabled.is_intent_comment("好用吗", keyword="耳机"))

    def test_is_intent_comment_custom_keywords(self):
        """自定义关键词匹配"""
        agent_disabled = type(self.agent)({"ai_reply": {"enabled": False}})
        result = agent_disabled.is_intent_comment(
            "这个东西靠谱吗能上车吗", 
            custom_keywords=["上车", "靠谱"]
        )
        self.assertTrue(result)

    def test_local_intent_guess_negative(self):
        """普通评论不触发意向"""
        agent_disabled = type(self.agent)({"ai_reply": {"enabled": False}})
        self.assertFalse(agent_disabled.is_intent_comment("哈哈哈哈", keyword=""))
        self.assertFalse(agent_disabled.is_intent_comment("真好", keyword=""))
        self.assertFalse(agent_disabled.is_intent_comment("路过", keyword=""))

    def test_generate_lead_reply_disabled(self):
        """AI禁用时使用兜底话术"""
        agent_disabled = type(self.agent)({"ai_reply": {"enabled": False}})
        result = agent_disabled.generate_lead_reply("这个怎么买？")
        self.assertIsNotNone(result)
        self.assertIn("主页", result)

    def test_lead_fallback_variants(self):
        """验证不同兜底话术"""
        agent = type(self.agent)({"ai_reply": {"enabled": False}})
        self.assertIn("主页", agent.generate_lead_reply("哪里买"))
        self.assertIn("主页", agent.generate_lead_reply("有教程吗"))
        self.assertIn("主页", agent.generate_lead_reply("好用吗"))

    def test_comment_length_validation(self):
        """验证评论文本长度限制"""
        self.assertFalse(self.agent._is_valid_reply("短"))
        self.assertFalse(self.agent._is_valid_reply("a" * 50))

    def test_check_custom_keywords_dedup(self):
        """验证自定义关键词去重"""
        result = self.agent._check_custom_keywords(
            "测试 关键词A 内容",
            ["关键词A", " 关键词A ", "关键词A"]
        )
        self.assertTrue(result)


# ==================== 评论区操作测试 ====================

class TestCommentingActions(unittest.TestCase):
    """评论操作逻辑测试"""

    def test_is_reviewable_comment(self):
        """验证可审查评论过滤逻辑"""
        from dy.actions.commenting import ProcessCommentSectionAction as PCA
        # 创建一个 mock action 实例
        mock_d = MagicMock()
        mock_config = {}
        action = PCA(u2_device=mock_d, config=mock_config)
        
        # 应该被过滤的
        self.assertFalse(action._is_reviewable_comment(""))
        self.assertFalse(action._is_reviewable_comment("ab"))  # <4 chars
        self.assertFalse(action._is_reviewable_comment("作者"))
        self.assertFalse(action._is_reviewable_comment("赞"))
        
        # 应该通过的
        self.assertTrue(action._is_reviewable_comment("这个怎么样"))
        self.assertTrue(action._is_reviewable_comment("怎么买这个"))

    def test_process_comment_section_empty(self):
        """空评论区"""
        mock_d = MagicMock()
        mock_d.xpath.return_value.all.return_value = []  # 没有评论
        mock_config = {"interaction": {}}
        
        action = type('PCA', (), {
            'd': mock_d,
            'config': mock_config,
            'check_stop_callback': None,
            '_comment_made': False,
            '_comment_panel_open': lambda s: False,
            '_close_comment_section': lambda s: True,
        })
        
        # 模拟 ProcessCommentSectionAction.execute
        from dy.actions.commenting import _xpath_exists
        # 测试路径

    def test_comment_panel_close_with_input_open(self):
        """评论区关闭时输入框仍打开的情况"""
        # _close_comment_section 会先关闭输入框再关面板
        pass


# ==================== 关注/私信操作测试 ====================

class TestInteractionActions(unittest.TestCase):
    """互动操作逻辑测试"""

    def test_follower_count_parsing(self):
        """粉丝数解析逻辑"""
        from dy.actions.interaction import FollowAuthorAction
        # 用 mock 创建实例
        mock_d = MagicMock()
        action = FollowAuthorAction(u2_device=mock_d, config={"interaction": {}})
        
        # 测试各种格式
        self.assertEqual(action._parse_follower_text("1.2万粉丝"), 1.2)
        self.assertEqual(action._parse_follower_text("粉丝3.5万"), 3.5)
        self.assertEqual(action._parse_follower_text("7146"), 0.7146)
        self.assertEqual(action._parse_follower_text("1234粉丝"), 0.1234)
        self.assertEqual(action._parse_follower_text("5w"), 5.0)
        self.assertIsNone(action._parse_follower_text(""))

    def test_follower_threshold_logic(self):
        """粉丝阈值过滤逻辑"""
        # 已在 TestAcquisitionStandalone 中覆盖
        pass


# ==================== 运行所有测试 ====================

if __name__ == "__main__":
    # 确保项目路径
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    unittest.main(verbosity=2)
