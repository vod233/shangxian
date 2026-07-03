"""TDD: Bug 3 — _scroll_to_reveal_top 滑动方向修复。

Behavior（spec）：
- _scroll_to_reveal_top 的目标是把评论区顶部内容拉回可见区域。
- Android 坐标：(0,0) 左上角，y 越大越靠下。
- 手指从下往上滑（sy > ey）→ 内容向下滚动 → 顶部内容重新可见。
- 手指从上往下滑（sy < ey）→ 内容向上滚动 → 顶部内容被推得更远。
- 当前已修复：compute_scroll_to_reveal_top 返回 sy > ey（手指上滑）。

测试纯函数 compute_scroll_to_reveal_top，不依赖 Android 设备。
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from dy.actions.commenting import compute_scroll_to_reveal_top


class TestScrollToRevealTopDirection:
    """验证 _scroll_to_reveal_top 滑动方向：手指应向上滑以显示顶部内容。"""

    @pytest.mark.parametrize("height,distance_px", [
        (800, 120),    # 小屏, distance_px=120（兜底场景 i==0 时）
        (1080, 250),   # 中屏, distance_px=250（默认值）
        (1440, 250),   # 大屏
        (800, 250),    # 小屏 + 大距离
        (400, 120),    # 极小屏幕
    ])
    def test_finger_moves_up_to_reveal_top(self, height, distance_px):
        """手指应向上滑（sy > ey），让内容向下滚动以显示顶部。"""
        _sx, sy, _ex, ey = compute_scroll_to_reveal_top(height, distance_px)

        assert sy > ey, (
            f"高度={height}, distance={distance_px}: "
            f"sy={sy} <= ey={ey}，方向反了！"
        )

    def test_coordinates_are_integers(self):
        """坐标应为整数。"""
        sx, sy, ex, ey = compute_scroll_to_reveal_top(1080, 250)
        assert isinstance(sx, int)
        assert isinstance(sy, int)
        assert isinstance(ex, int)
        assert isinstance(ey, int)

    def test_ey_does_not_go_off_screen_top(self):
        """ey（手指终点）不应超出屏幕上沿（设为 >= 10）。"""
        _sx, sy, _ex, ey = compute_scroll_to_reveal_top(800, 250)
        # sy=360, ey=110
        assert ey >= 0, f"ey={ey} 不应为负数"
        assert isinstance(ey, int)

    def test_ey_keeps_reasonable_margin(self):
        """手指终点应保留合理操作空间（>= 10px）。"""
        _sx, sy, _ex, ey = compute_scroll_to_reveal_top(1080, 250)
        assert ey >= 10, f"ey={ey} 太靠近屏幕顶部"

    def test_multiple_calls_give_same_result(self):
        """纯函数：相同输入应返回相同输出。"""
        r1 = compute_scroll_to_reveal_top(1080, 250)
        r2 = compute_scroll_to_reveal_top(1080, 250)
        assert r1 == r2

    def test_default_distance_is_250(self):
        """默认 distance_px 应为 250。"""
        sx, sy, ex, ey = compute_scroll_to_reveal_top(1080)
        assert sy - ey == 250, f"sy={sy}, ey={ey}, diff={sy-ey}, 期望 250"

    def test_sy_start_at_45_percent(self):
        """sy 应在屏幕 45% 位置。"""
        sx, sy, ex, ey = compute_scroll_to_reveal_top(1000, 200)
        assert sy == 450, f"sy={sy}, 期望 450"

    def test_small_distance_works(self):
        """极小距离不应出界。"""
        sx, sy, ex, ey = compute_scroll_to_reveal_top(400, 300)
        # sy=180, ey=-120 但应被截断到 10
        assert ey == 10, f"ey={ey}, 期望 10（被截断至安全边界）"
