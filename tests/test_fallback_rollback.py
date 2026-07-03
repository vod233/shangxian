"""Slice B: 兜底评论滑走回滚判定（纯函数）。

复现：zoom-out 报告发现兜底 5 条目标 4 条滑走（80%），
系统机械跳过，无累计信号、无回滚重收集。
本测试锁定"连续滑走达到阈值时触发回滚"的判定逻辑。
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dy.actions.commenting import _should_rollback_fallback


class TestShouldRollbackFallback:
    def test_no_skips_no_rollback(self):
        """无滑走时不触发回滚。"""
        results = [
            {"text": "A", "handled": True},
            {"text": "B", "handled": True},
        ]
        assert _should_rollback_fallback(results) is False

    def test_below_threshold_no_rollback(self):
        """滑走数低于阈值（默认3）时不回滚。"""
        results = [
            {"text": "A", "skipped": True},
            {"text": "B", "handled": True},
        ]
        assert _should_rollback_fallback(results) is False

    def test_consecutive_skips_at_threshold_triggers_rollback(self):
        """连续3条滑走触发回滚。"""
        results = [
            {"text": "A", "skipped": True},
            {"text": "B", "skipped": True},
            {"text": "C", "skipped": True},
        ]
        assert _should_rollback_fallback(results) is True

    def test_non_consecutive_skips_no_rollback(self):
        """滑走不连续（中间有成功）时不触发回滚——证明是"连续"判定而非"总数"。"""
        results = [
            {"text": "A", "skipped": True},
            {"text": "B", "handled": True},
            {"text": "C", "skipped": True},
            {"text": "D", "skipped": True},
        ]
        assert _should_rollback_fallback(results) is False

    def test_custom_threshold(self):
        """自定义阈值。"""
        results = [
            {"text": "A", "skipped": True},
            {"text": "B", "skipped": True},
        ]
        assert _should_rollback_fallback(results, threshold=2) is True

    def test_empty_results_no_rollback(self):
        """空结果不回滚。"""
        assert _should_rollback_fallback([]) is False

    def test_real_case_4_of_5_skipped_rollback(self):
        """真实样本：5条中前4条连续滑走，应触发回滚。"""
        results = [
            {"text": "好久没见林林了？", "skipped": True},
            {"text": "我想问林林同学去哪儿了", "skipped": True},
            {"text": "林林呢？好久没看到了", "skipped": True},
            {"text": "有没有诗婷的账号？", "skipped": True},
            {"text": "林林呐，想林林", "handled": True},
        ]
        assert _should_rollback_fallback(results) is True
