"""TDD: Bug 2 — DoubleClickLikeAction 重命名为 SingleClickLikeAction。

Behavior（spec）：
- 类名应准确描述行为：该类执行的是单次点击（single click），不是双击。
- SingleClickLikeAction.execute 中 self.human_click(x, y, jitter_range=5) 仅调用一次，
  用旧类名 "DoubleClick" 严重误导代码阅读者。
- 修复：重命名为 SingleClickLikeAction。
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from dy.actions.interaction import SingleClickLikeAction, DoubleClickLikeAction


class TestSingleClickLikeActionNaming:
    """验证点赞动作类名正确反映其行为。"""

    def test_class_name_is_single_click(self):
        """类名应为 SingleClickLikeAction。"""
        assert SingleClickLikeAction.__name__ == "SingleClickLikeAction"

    def test_backward_compatibility_alias_exists(self):
        """旧名称 DoubleClickLikeAction 仍可导入（向后兼容）。"""
        assert DoubleClickLikeAction is SingleClickLikeAction

    def test_old_name_resolves_to_new_class(self):
        """旧名称指向同一个类。"""
        assert DoubleClickLikeAction.__name__ == "SingleClickLikeAction"
