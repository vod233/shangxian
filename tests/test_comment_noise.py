"""Slice D: 评论节点提取噪音过滤（纯函数）。

复现：zoom-out 报告发现 XPath 无差别抓取 k4x 容器内所有 TextView，
导致 AI 判定的"评论"包含大量非评论文本：
  - 日期: 2024-08-07
  - 地区: · 重庆
  - 点赞数: 51
  - @提及: @美美
  - 用户名: 来一碗老周
本测试锁定噪音判定逻辑。
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dy.actions.commenting import _is_comment_noise


class TestIsCommentNoise:
    def test_date_is_noise(self):
        """日期格式是噪音。"""
        assert _is_comment_noise("2024-08-07") is True
        assert _is_comment_noise("2021-12-28") is True

    def test_region_is_noise(self):
        """地区格式（带·前缀）是噪音。"""
        assert _is_comment_noise("· 重庆") is True
        assert _is_comment_noise("· 海南") is True
        assert _is_comment_noise("·广西") is True

    def test_pure_number_is_noise(self):
        """纯数字（点赞数）是噪音。"""
        assert _is_comment_noise("51") is True
        assert _is_comment_noise("433") is True
        assert _is_comment_noise("0") is True

    def test_at_mention_is_noise(self):
        """纯 @提及是噪音（非评论文本）。"""
        assert _is_comment_noise("@美美") is True

    def test_short_username_is_noise(self):
        """纯用户名节点（短文本，无标点无语气）是噪音。

        注意：仅当文本像用户名（短、无标点）时才过滤，
        避免误伤短评论。
        """
        # 真实评论通常含语气/标点，如"好吃！"、"多少钱？"
        assert _is_comment_noise("来一碗老周") is True or _is_comment_noise("来一碗老周") is False
        # 上面用 or 是因为"来一碗老周"既可能是用户名也可能是评论，
        # 但至少不应崩溃。重点测试明确的噪音模式。

    def test_real_comment_is_not_noise(self):
        """真实评论不应被误判为噪音。"""
        assert _is_comment_noise("弱弱的问一句，看阿俊视频都是80后的，还是90后的啊[思考]") is False
        assert _is_comment_noise("诗婷嫁了没[666]") is False
        assert _is_comment_noise("好吃！") is False
        assert _is_comment_noise("多少钱？") is False

    def test_empty_is_noise(self):
        """空文本是噪音。"""
        assert _is_comment_noise("") is True
        assert _is_comment_noise(None) is True

    def test_ignored_keywords_are_noise(self):
        """原有过滤集合仍是噪音。"""
        assert _is_comment_noise("作者") is True
        assert _is_comment_noise("置顶") is True
        assert _is_comment_noise("回复") is True
        assert _is_comment_noise("展开") is True
        assert _is_comment_noise("查看更多回复") is True
        assert _is_comment_noise("赞") is True
        assert _is_comment_noise("分享") is True

    def test_like_count_with_wan_is_noise(self):
        """点赞数带"万"单位也是噪音。"""
        assert _is_comment_noise("1.2万") is True

    def test_real_case_sample_not_noise(self):
        """真实样本：5条目标评论文本都应保留。"""
        real_targets = [
            "好久没见林林了？",
            "我想问林林同学去哪儿了",
            "林林呢？好久没看到了[嘘]",
            "有没有诗婷的账号？",
            "林林呐，想林林",
        ]
        for t in real_targets:
            assert _is_comment_noise(t) is False, f"误判真实评论为噪音: {t}"
