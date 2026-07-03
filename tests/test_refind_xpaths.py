"""测试 _build_refind_xpaths 纯函数的 behavior。

背景：F2 兜底评论滑走的根因是 PhaseA 扫描时滑动导致评论滚出可视区，
_refind_comment_node_by_text 用文本重定位失败时返回 None，
触发跳过逻辑（第 1372-1375 行）。此测试锁住 xpath 构建逻辑，
确保文本能正确转为可重定位的 xpath。
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dy.actions.commenting import _build_refind_xpaths


class TestBuildRefindXpaths:
    """通过 public 纯函数验证 xpath 构建 behavior。"""

    def test_normal_text_generates_contains_xpath(self):
        """正常文本生成 contains(@text, "...") xpath。"""
        xpaths = _build_refind_xpaths("好想吃")
        assert len(xpaths) >= 1
        assert 'contains(@text, "好想吃")' in xpaths[0]

    def test_empty_text_returns_empty_list(self):
        """空文本返回空列表（无法重定位，触发跳过）。"""
        assert _build_refind_xpaths("") == []
        assert _build_refind_xpaths("   ") == []

    def test_long_text_generates_two_xpaths(self):
        """长文本（>15字符）生成两个 xpath：全文 + 前15字符。

        复现：v13 主评"之前交的税够买百个..."被截断为"之前交的税够买百个 瞎琢磨后终于摸透 碰"，
        需要用前缀 xpath 兜底重定位。
        """
        long_text = "之前交的税够买百个 瞎琢磨后终于摸透 碰巧整理了实操记录"
        xpaths = _build_refind_xpaths(long_text)
        assert len(xpaths) == 2

    def test_short_text_generates_one_xpath(self):
        """短文本（<=15字符）只生成一个 xpath。"""
        xpaths = _build_refind_xpaths("短评论")
        assert len(xpaths) == 1

    def test_text_with_double_quote_uses_single_quote_wrapper(self):
        """含双引号的文本用单引号包裹 xpath。"""
        xpaths = _build_refind_xpaths('含"引号"的评论')
        # 应存在用单引号包裹的 xpath
        assert any("contains(@text, '" in x for x in xpaths)

    def test_all_xpaths_are_valid_contains_expressions(self):
        """所有生成的 xpath 都是 contains(@text, ...) 形式。"""
        xpaths = _build_refind_xpaths("正常评论文本足够长用于测试")
        for x in xpaths:
            assert 'contains(@text,' in x
