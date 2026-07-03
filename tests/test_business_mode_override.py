"""TDD: Bug 4 — business_mode 不应静默覆盖用户显式关闭的开关。

Behavior（spec）：
- business_mode=1 时，如果用户显式设置 enable_author_follow=false，应报告配置冲突。
- business_mode=2 时，如果用户显式设置 enable_video_comment=false 或
  enable_comment_lead=false，应报告配置冲突。
- 当前行为仅 logger.warning 然后继续执行（静默覆盖）。
- 修复后应 fail-fast：通过 resolve_business_mode_conflicts 报告冲突。

测试 extracted function resolve_business_mode_conflicts。
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from dy.task_runner import resolve_business_mode_conflicts


class TestBusinessModeNoSilentOverride:
    """business_mode 不应静默覆盖用户显式关闭的开关。"""

    def test_mode1_conflicts_with_author_follow_disabled(self):
        """mode=1 + enable_author_follow=false → 应报告冲突。"""
        conflicts = resolve_business_mode_conflicts(
            mode=1,
            enable_author_follow=False,
        )

        assert len(conflicts) == 1
        assert "enable_author_follow=false" in conflicts[0]

    def test_mode2_conflicts_with_video_comment_disabled(self):
        """mode=2 + enable_video_comment=false → 应报告冲突。"""
        conflicts = resolve_business_mode_conflicts(
            mode=2,
            enable_video_comment=False,
            enable_comment_lead=True,
        )

        assert len(conflicts) == 1
        assert "enable_video_comment=false" in conflicts[0]

    def test_mode2_conflicts_with_comment_lead_disabled(self):
        """mode=2 + enable_comment_lead=false → 应报告冲突。"""
        conflicts = resolve_business_mode_conflicts(
            mode=2,
            enable_video_comment=True,
            enable_comment_lead=False,
        )

        assert len(conflicts) == 1
        assert "enable_comment_lead=false" in conflicts[0]

    def test_mode2_conflicts_with_both_disabled(self):
        """mode=2 + 两个开关都关 → 应报告两个冲突。"""
        conflicts = resolve_business_mode_conflicts(
            mode=2,
            enable_video_comment=False,
            enable_comment_lead=False,
        )

        assert len(conflicts) == 2

    def test_mode1_no_conflict_when_enabled(self):
        """mode=1 + enable_author_follow=true → 无冲突。"""
        conflicts = resolve_business_mode_conflicts(
            mode=1,
            enable_author_follow=True,
        )

        assert len(conflicts) == 0

    def test_mode2_no_conflict_when_enabled(self):
        """mode=2 + 所有开关打开 → 无冲突。"""
        conflicts = resolve_business_mode_conflicts(
            mode=2,
            enable_author_follow=True,
            enable_video_comment=True,
            enable_comment_lead=True,
        )

        assert len(conflicts) == 0

    def test_mode0_no_conflicts(self):
        """mode=0（仅点赞）→ 无冲突。"""
        conflicts = resolve_business_mode_conflicts(
            mode=0,
            enable_author_follow=False,
            enable_video_comment=False,
            enable_comment_lead=False,
        )

        assert len(conflicts) == 0

    def test_mode_none_no_conflicts(self):
        """mode=None 时视为无冲突。"""
        conflicts = resolve_business_mode_conflicts(
            mode=None,
            enable_author_follow=False,
        )

        assert len(conflicts) == 0
