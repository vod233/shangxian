"""Slice C: 私信软封禁全局降级判定（纯函数）。

复现：zoom-out 报告发现"由于对方的隐私设置，你无法发送消息"
反复出现（3次才停止重试），且无全局降级——每视频独立重试加剧封禁。
本测试锁定"连续软封禁 N 次后触发全局降级"的判定逻辑。
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dy.actions.interaction import _should_global_cooldown_pm, _classify_pm_failure


class TestClassifyPmFailure:
    def test_privacy_settings_is_soft_ban(self):
        """隐私设置失败归类为软封禁。"""
        assert _classify_pm_failure("由于对方的隐私设置，你无法发送消息") == "soft_ban"

    def test_operation_frequent_is_soft_ban(self):
        """操作频繁归类为软封禁。"""
        assert _classify_pm_failure("操作频繁，请稍后再试") == "soft_ban"

    def test_blocked_is_hard_fail(self):
        """被对方拉黑归类为硬失败（非全局降级信号）。"""
        assert _classify_pm_failure("被对方拉黑") == "hard_fail"

    def test_send_failed_is_hard_fail(self):
        """发送失败归类为硬失败。"""
        assert _classify_pm_failure("发送失败") == "hard_fail"

    def test_empty_text_is_no_failure(self):
        """空文本不是失败。"""
        assert _classify_pm_failure("") == "no_failure"

    def test_normal_text_is_no_failure(self):
        """正常文本不是失败。"""
        assert _classify_pm_failure("你好") == "no_failure"


class TestShouldGlobalCooldownPm:
    def test_below_threshold_no_cooldown(self):
        """软封禁次数低于阈值（默认3）时不降级。"""
        assert _should_global_cooldown_pm(2) is False

    def test_at_threshold_triggers_cooldown(self):
        """软封禁次数达阈值（默认3）时触发降级。"""
        assert _should_global_cooldown_pm(3) is True

    def test_above_threshold_triggers_cooldown(self):
        """超过阈值时触发降级。"""
        assert _should_global_cooldown_pm(5) is True

    def test_custom_threshold(self):
        """自定义阈值。"""
        assert _should_global_cooldown_pm(2, threshold=2) is True

    def test_zero_count_no_cooldown(self):
        """0 次不降级。"""
        assert _should_global_cooldown_pm(0) is False

    def test_real_case_3_privacy_failures_triggers(self):
        """真实样本：连续3次"由于对方的隐私设置"应触发降级。"""
        # 复现 15:14:06-07 三次失败提示
        soft_ban_count = 0
        failures = [
            "由于对方的隐私设置，你无法发送消息",
            "由于对方的隐私设置，你无法发送消息",
            "由于对方的隐私设置，你无法发送消息",
        ]
        for f in failures:
            if _classify_pm_failure(f) == "soft_ban":
                soft_ban_count += 1
        assert _should_global_cooldown_pm(soft_ban_count) is True
