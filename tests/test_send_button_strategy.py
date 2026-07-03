"""测试 _pick_send_button_from_infos 纯函数的 behavior。

背景：F4 CS4 宽松策略 100% 触发，因为抖音新版本发送按钮 clickable=false。
现有 _find_clickable_send_button 有 4 级策略回退（标准→resource-id→宽松→坐标）。
此测试锁住策略选择核心：标准 clickable=true 失败时回退到宽松策略。
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dy.actions.commenting import _pick_send_button_from_infos, _info_visible_enabled


def _info(clickable, visible=True, enabled=True, bottom=100):
    """构造测试用 info 字典。"""
    return {
        "clickable": clickable,
        "visibleToUser": visible,
        "enabled": enabled,
        "bounds": {"bottom": bottom},
    }


class TestPickSendButtonFromInfos:
    """通过 public 纯函数验证发送按钮策略回退 behavior。"""

    def test_strict_strategy_prefers_clickable_true(self):
        """策略1: clickable=true + visible 的节点优先被选中。"""
        infos = [
            _info(clickable=False, bottom=200),  # 宽松候选
            _info(clickable=True, bottom=100),   # 严格候选
        ]
        strategy, picked = _pick_send_button_from_infos(infos)
        assert strategy == "strict"
        assert picked["clickable"] is True

    def test_loose_strategy_fallback_when_no_clickable(self):
        """策略3(宽松): 无 clickable=true 时回退到宽松策略。

        复现：F4 实测抖音新版本发送按钮 clickable=false，100% 走宽松策略。
        """
        infos = [
            _info(clickable=False, bottom=100),
            _info(clickable=False, bottom=200),
        ]
        strategy, picked = _pick_send_button_from_infos(infos)
        assert strategy == "loose"
        assert picked["bounds"]["bottom"] == 200  # 取最底部

    def test_returns_none_when_all_invisible(self):
        """全部不可见时返回 (None, None)。"""
        infos = [
            _info(clickable=True, visible=False, bottom=100),
            _info(clickable=False, visible=False, bottom=200),
        ]
        strategy, picked = _pick_send_button_from_infos(infos)
        assert strategy is None
        assert picked is None

    def test_returns_none_for_empty_infos(self):
        """空 infos 返回 (None, None)。"""
        strategy, picked = _pick_send_button_from_infos([])
        assert strategy is None
        assert picked is None

    def test_strict_picks_bottommost_among_multiple(self):
        """策略1 多个候选时取最底部。"""
        infos = [
            _info(clickable=True, bottom=150),
            _info(clickable=True, bottom=300),
            _info(clickable=True, bottom=100),
        ]
        strategy, picked = _pick_send_button_from_infos(infos)
        assert strategy == "strict"
        assert picked["bounds"]["bottom"] == 300

    def test_loose_picks_bottommost_among_visible(self):
        """策略3 多个宽松候选时取最底部。"""
        infos = [
            _info(clickable=False, bottom=150),
            _info(clickable=False, bottom=300),
        ]
        strategy, picked = _pick_send_button_from_infos(infos)
        assert strategy == "loose"
        assert picked["bounds"]["bottom"] == 300

    def test_handles_none_elements_in_infos(self):
        """REVIEW: infos 含 None 时不崩溃，跳过 None 元素。"""
        infos = [None, _info(clickable=True, bottom=100), None]
        strategy, picked = _pick_send_button_from_infos(infos)
        assert strategy == "strict"
        assert picked["clickable"] is True


class TestInfoVisibleEnabled:
    """验证 _info_visible_enabled 纯函数（CS4 策略的前置判断）。"""

    def test_visible_and_enabled_returns_true(self):
        assert _info_visible_enabled(_info(clickable=True, visible=True, enabled=True)) is True

    def test_invisible_returns_false(self):
        assert _info_visible_enabled(_info(clickable=True, visible=False, enabled=True)) is False

    def test_disabled_returns_false(self):
        assert _info_visible_enabled(_info(clickable=True, visible=True, enabled=False)) is False

    def test_missing_visible_defaults_false(self):
        """缺失 visibleToUser 时默认 False（安全失败）。"""
        assert _info_visible_enabled({"clickable": True, "enabled": True}) is False

    def test_legacy_visible_key_compat(self):
        """老版本 visible 键兼容。"""
        assert _info_visible_enabled({"clickable": True, "visible": True, "enabled": True}) is True
