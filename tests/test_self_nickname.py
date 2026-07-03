"""测试 _select_self_nickname 纯函数的 behavior。

背景：diagnose 发现 _resolve_self_nickname 在评论区打开时，
通过 id/title 取首个匹配节点的 text，但该节点在评论数>=2 时是
"X条评论"计数标识（如"3376条评论"），导致 self-filter 失效，
进而触发 F7（兜底误处理自己主评）。

修复：提取 _select_self_nickname(candidates, config_nick) 纯函数，
过滤掉评论数计数标识。
"""
import sys
import os

# 让 tests 能导入 dy.actions.commenting
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dy.actions.commenting import _select_self_nickname


class TestSelectSelfNickname:
    """通过 public 纯函数验证昵称选择 behavior。"""

    def test_ignores_comment_count_label(self):
        """评论数计数标识（"X条评论"）不应被识别为账号昵称。

        复现：v5 实测 self_nickname 被误检为"3376条评论"。
        """
        candidates = ["3376条评论"]
        assert _select_self_nickname(candidates) == ""

    def test_selects_real_nickname(self):
        """真实账号名应被正确选中。

        复现：v12 实测 self_nickname 正确检测为"宜都市夏陶百货店（个人独资）"。
        """
        candidates = ["宜都市夏陶百货店（个人独资）"]
        assert _select_self_nickname(candidates) == "宜都市夏陶百货店（个人独资）"

    def test_config_nickname_takes_priority(self):
        """配置中的 self_nickname 优先级最高，跳过 UI 检测。"""
        candidates = ["3376条评论", "某路人"]
        assert _select_self_nickname(candidates, config_nick="我的账号") == "我的账号"

    def test_returns_empty_when_all_candidates_are_count_labels(self):
        """所有候选都是评论数标识时返回空字符串（self-filter 不生效）。"""
        candidates = ["3376条评论", "285条评论", "4条评论"]
        assert _select_self_nickname(candidates) == ""

    def test_selects_first_valid_among_mixed_candidates(self):
        """混合候选时取第一个有效昵称（跳过评论数标识）。

        复现：评论区 id/title 同时匹配评论数标识与账号昵称，
        应跳过标识取真实昵称。
        """
        candidates = ["3376条评论", "宜都市夏陶百货店（个人独资）"]
        assert _select_self_nickname(candidates) == "宜都市夏陶百货店（个人独资）"

    def test_returns_empty_for_empty_candidates(self):
        """无候选时返回空字符串。"""
        assert _select_self_nickname([]) == ""

    def test_returns_empty_when_all_too_short(self):
        """长度<2的候选被视为无效。"""
        candidates = ["a", ""]
        assert _select_self_nickname(candidates) == ""

    def test_ignores_comment_count_label_with_wan_unit(self):
        r"""评论数带"万"单位时也应被识别为计数标识。

        复现：zoom-out 报告发现 self_nickname 被误检为"1.9万条评论"，
        原正则 ^\d+\s*条评论$ 不匹配"万"字单位。
        """
        candidates = ["1.9万条评论"]
        assert _select_self_nickname(candidates) == ""

    def test_ignores_comment_count_label_with_yi_unit(self):
        """评论数带"亿"单位时也应被识别为计数标识。"""
        candidates = ["2.3亿条评论"]
        assert _select_self_nickname(candidates) == ""

    def test_ignores_various_count_label_formats(self):
        """多种格式的评论数标识都应被过滤。"""
        candidates = [
            "3376条评论",
            "1.9万条评论",
            "285条评论",
            "0条评论",
            "10万条评论",
        ]
        assert _select_self_nickname(candidates) == ""

    def test_selects_real_nickname_among_wan_unit_labels(self):
        """混合场景：评论数标识带"万"字 + 真实昵称，应选真实昵称。"""
        candidates = ["1.9万条评论", "宜都市夏陶百货店（个人独资）"]
        assert _select_self_nickname(candidates) == "宜都市夏陶百货店（个人独资）"
