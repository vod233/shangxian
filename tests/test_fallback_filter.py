"""测试 _filter_out_main_comment 纯函数的 behavior。

背景：diagnose 发现 v13 兜底处理 [1/3] 的目标是刚发送的主评文本
"之前交的税够买百个..."，因为 self_nickname 误检为"4条评论"导致
self-filter 失效，系统对自己的主评做楼中楼回复+进自己主页私信（F7）。

修复：_collect_top_level_targets 收集后，用主评文本做硬过滤，
独立于 self_nickname，确保即使 self_nickname 失效也不会处理自己。
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dy.actions.commenting import _filter_out_main_comment


class TestFilterOutMainComment:
    """通过 public 纯函数验证主评过滤 behavior。"""

    def test_excludes_exact_main_comment_match(self):
        """主评文本完全匹配时应被排除。

        复现：v13 兜底[1/3] 目标 = 主评文本"之前交的税够买百个..."。
        """
        main = "之前交的税够买百个 瞎琢磨后终于摸透 碰巧整理了实操记录"
        targets = [
            {'text': main, 'author': '我'},
            {'text': '好想吃 [舔屏]', 'author': '路人A'},
        ]
        result = _filter_out_main_comment(targets, main)
        assert len(result) == 1
        assert result[0]['text'] == '好想吃 [舔屏]'

    def test_keeps_targets_when_main_comment_absent(self):
        """主评不在 targets 中时全部保留。"""
        main = "不存在的主评"
        targets = [
            {'text': '评论1', 'author': 'A'},
            {'text': '评论2', 'author': 'B'},
        ]
        result = _filter_out_main_comment(targets, main)
        assert len(result) == 2

    def test_returns_all_when_main_comment_empty(self):
        """主评文本为空时返回全部（未发主评或主评为空）。"""
        targets = [{'text': '评论1', 'author': 'A'}]
        result = _filter_out_main_comment(targets, "")
        assert len(result) == 1

    def test_excludes_when_target_is_prefix_of_main(self):
        """目标是主评前缀时排除（UI 截断导致目标比主评短）。

        复现：v13 B.5 重定位时文本被截断为"之前交的税够买百个 瞎琢磨后终于摸透 碰"。
        """
        main = "之前交的税够买百个 瞎琢磨后终于摸透 碰巧整理了实操记录"
        truncated = "之前交的税够买百个 瞎琢磨后终于摸透 碰"
        targets = [{'text': truncated, 'author': '我'}]
        result = _filter_out_main_comment(targets, main)
        assert len(result) == 0

    def test_excludes_when_main_is_prefix_of_target(self):
        """主评是目标前缀时排除（目标比主评长，含尾部多余字符）。"""
        main = "主评文本"
        targets = [{'text': '主评文本展开', 'author': '我'}]
        result = _filter_out_main_comment(targets, main)
        assert len(result) == 0

    def test_does_not_mutate_input(self):
        """不修改输入列表（返回新列表）。"""
        main = "主评"
        targets = [{'text': '主评', 'author': 'A'}, {'text': '其他', 'author': 'B'}]
        original_len = len(targets)
        _ = _filter_out_main_comment(targets, main)
        assert len(targets) == original_len

    def test_handles_target_with_empty_text(self):
        """目标 text 为空时不崩溃，保留（过滤逻辑只针对主评匹配）。"""
        main = "主评"
        targets = [{'text': '', 'author': 'A'}, {'text': '主评', 'author': 'B'}]
        result = _filter_out_main_comment(targets, main)
        assert len(result) == 1
        assert result[0]['text'] == ''
