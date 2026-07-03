"""TDD: Bug 3 暗引流词黑名单 — _is_valid_lead_reply 缺少"背景墙"等词。

Behavior（spec）：
- _is_valid_lead_reply 应拒绝暗引流话术，包括"背景墙"、"主页"、"详情"等。
- 当前代码已含微信/电话/链接等 ban 词，但缺少"背景墙"。
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from dy.ai_reply_agent import DYReplyAgent


class TestLeadReplyBannedPatterns:
    """验证兜底回复黑名单过滤。"""

    @pytest.fixture
    def agent(self):
        return DYReplyAgent(config={})

    # ─── RED: 以下话术当前不被拦截（测试会 FAIL 直到添加黑名单） ───

    @pytest.mark.parametrize("text", [
        "背景墙有说明",
        "背景墙有全套资料",
        "看背景墙详情",
        "背景墙有联系方式",  # 暗示联系方式
        "主页有详情",
        "详情请看主页",
        "看我主页",       # "主页" + "我" 暗引流
        "背景墙",
    ])
    def test_blacklist_blocks_dark_traffic_phrases(self, text):
        """暗引流话术应被黑名单拦截。"""
        agent = DYReplyAgent(config={})
        # RED: 当前代码中"背景墙"不在黑名单，此断言会 FAIL
        # 修复后应: assert not agent._is_valid_lead_reply(text)
        assert not agent._is_valid_lead_reply(text), (
            f"'{text}' 是暗引流话术，应被黑名单拦截"
        )

    # ─── 这些应该正常通过（确保不过滤） ───

    @pytest.mark.parametrize("text", [
        "这个建议很不错，可以试试看",
        "我觉得你的想法很好",
        "说得有道理，支持一下",
        "请问这个在哪里买",
    ])
    def test_legitimate_text_passes(self, text):
        """正常回复文本应通过验证。"""
        agent = DYReplyAgent(config={})
        assert agent._is_valid_lead_reply(text), (
            f"'{text}' 是正常回复，不应被拦截"
        )
