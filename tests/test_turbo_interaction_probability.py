"""TDD: Bug 2 — turbo 模式不应短路 InteractionProbability。

Behavior（spec）：
- turbo_test_mode 应只加速 HumanSleep（缩短等待时间）。
- turbo_test_mode 不应绕过 InteractionProbability（概率决策是防风控核心机制）。
- 当前代码: InteractionProbability._turbo_enabled = True 时，should_interact 为所有
  action_type 返回 True（除了 long_watch），完全绕过概率计算。这是风控风险。
- 修复后：turbo 只影响 HumanSleep，InteractionProbability.should_interact 始终
  按配置的概率决策（turbo_enabled 不影响概率判断）。
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from unittest.mock import patch
from dy.anti_detection import (
    HumanSleep,
    InteractionProbability,
    BehaviorRandomizer,
)


class TestTurboDoesNotBypassInteractionProbability:
    """turbo 模式不应绕过 InteractionProbability 的概率决策。"""

    def setup_method(self):
        # 确保每个测试前重置类变量
        InteractionProbability._turbo_enabled = False
        HumanSleep._turbo_enabled = False
        BehaviorRandomizer._turbo_enabled = False

    def teardown_method(self):
        InteractionProbability._turbo_enabled = False
        HumanSleep._turbo_enabled = False
        BehaviorRandomizer._turbo_enabled = False

    # ── RED: 当前 turbo 短路概率决策，以下测试应 FAIL ──

    def test_turbo_does_not_affect_interaction_probability(self):
        """turbo 启用时，InteractionProbability 仍应执行概率决策。

        RED: 当前代码中 turbo=True 时 should_interact 返回 True 忽略概率。
        """
        InteractionProbability._turbo_enabled = True

        # 模拟一个极低概率的配置
        config = {
            'anti_detection': {
                'interaction_probability': {
                    'enabled': True,
                    'like': 0.0,  # 概率为 0，应永不执行
                }
            }
        }

        # 当前行为: turbo 下总是返回 True（即使概率=0）
        # 正确行为: 应返回 False（概率=0）
        result = InteractionProbability.should_interact('like', config)

        # 断言：即使 turbo 启用，概率决策仍应生效
        # 概率=0 时应返回 False
        assert result is False, (
            f"turbo 模式下 InteractionProbability 仍应遵守概率决策。"
            f"like 概率=0.0，期望返回 False，实际返回 {result}"
        )

    def test_human_sleep_is_affected_by_turbo(self):
        """turbo 应缩短 HumanSleep（这是 turbo 的正确用途）。"""
        HumanSleep._turbo_enabled = True
        # turbo 模式下 sleep 应返回 0.05
        result = HumanSleep.sleep('normal', custom_range=(2.0, 5.0))
        assert result == 0.05, (
            f"turbo 模式下 HumanSleep 应返回 0.05，实际返回 {result}"
        )

    def test_turbo_off_probability_works_normally(self):
        """turbo 关闭时概率决策正常工作。"""
        InteractionProbability._turbo_enabled = False

        config = {
            'anti_detection': {
                'interaction_probability': {
                    'enabled': True,
                    'like': 1.0,  # 概率 100%
                }
            }
        }

        # 概率=1.0 时肯定返回 True
        result = InteractionProbability.should_interact('like', config)
        assert result is True

    def test_interaction_probability_respects_config_when_turbo_on(self):
        """turbo 启用时仍应读取配置中的概率值。"""
        InteractionProbability._turbo_enabled = True

        config = {
            'anti_detection': {
                'interaction_probability': {
                    'enabled': True,
                    'lead_pm': 0.0,  # 0% 概率
                }
            }
        }

        result = InteractionProbability.should_interact('lead_pm', config)
        # 概率=0 时应返回 False
        assert result is False

    def test_turbo_still_skips_long_watch(self):
        """long_watch 在 turbo 下仍应被跳过（不延长停留时间）。"""
        InteractionProbability._turbo_enabled = True

        result = InteractionProbability.should_interact('long_watch', {})
        # long_watch 在 turbo 下应跳过（即使修复后也应保持）
        assert result is False
